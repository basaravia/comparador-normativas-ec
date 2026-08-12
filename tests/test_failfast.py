"""Ítem 1 — la corrida se detiene cuando el modelo cae, y lo dice.

El defecto original: cualquier excepción acababa produciendo `nivel_cumplimiento="no_aplica"`
con el texto del error dentro de `analisis_general`. El auditor recibía un papel de trabajo
que afirmaba "no aplica" sobre secciones que el modelo nunca llegó a leer.

Lo que estas pruebas fijan:
  · un fallo de infraestructura aborta y cancela lo pendiente
  · un fallo de contenido degrada solo su fila
  · ninguna fila fallida sale como `no_aplica`
  · ningún mensaje de error acaba dentro de un campo de análisis
"""
from __future__ import annotations

import openai
import pytest
from langchain_core.exceptions import OutputParserException

from src.comparator import DocumentComparator
from src.errors import (
    AnalysisParseError,
    GradingParseError,
    LLMUnavailableError,
    ModelNotFoundError,
    RunAbortedError,
    classify_llm_exception,
)
from tests.fixtures import FakeGrader, FakeIndex


class TestClasificacion:
    """`classify_llm_exception` decide abortar o degradar. Es la bisagra del ítem."""

    def test_error_de_conexion_es_infraestructura(self):
        exc = openai.APIConnectionError(request=None)  # type: ignore[arg-type]
        assert isinstance(classify_llm_exception(exc), LLMUnavailableError)

    def test_modelo_que_no_carga_se_detecta_por_texto(self):
        """El caso de la captura 1 del informe: llega como error genérico y el único
        indicio está en el mensaje."""
        exc = RuntimeError('error while getting model "docker.io/ai/smollm2-vllm:1.7B"')
        error = classify_llm_exception(exc, modelo="smollm2", url="http://localhost:12434")
        assert isinstance(error, ModelNotFoundError)
        assert "smollm2" in str(error)
        assert "localhost:12434" in str(error), "el mensaje debe decir qué endpoint falló"

    def test_fallo_de_parseo_es_contenido(self):
        exc = OutputParserException("no se pudo parsear el JSON")
        error = classify_llm_exception(exc)
        assert isinstance(error, GradingParseError)
        assert not isinstance(error, LLMUnavailableError), (
            "un fallo de parseo no debe abortar la corrida entera"
        )

    def test_lo_desconocido_se_trata_como_infraestructura(self):
        """Ante la duda, detener. Lo contrario es el defecto original: seguir
        produciendo veredictos sobre secciones que nadie analizó."""
        assert isinstance(classify_llm_exception(ValueError("vaya")), LLMUnavailableError)

    def test_la_clasificacion_es_idempotente(self):
        original = LLMUnavailableError("caído")
        assert classify_llm_exception(original) is original


class TestAbortoEnCascada:

    @pytest.fixture
    def comparator_que_cae(self, normativa_df):
        grader = FakeGrader(
            fallar_en=lambda row: openai.APIConnectionError(request=None)  # type: ignore[arg-type]
        )
        return DocumentComparator(
            normativa_index=FakeIndex(normativa_df=normativa_df, plan={}),
            llm_grader=grader,
        )

    def test_relanza_run_aborted(self, comparator_que_cae, manual_df, normativa_df):
        with pytest.raises(RunAbortedError) as exc:
            comparator_que_cae.run(manual_df, normativa_df, max_workers=1)
        assert exc.value.total == len(manual_df)

    def test_no_procesa_todas_las_filas(self, comparator_que_cae, manual_df, normativa_df):
        """Lo que el defecto no hacía: dejar de gastar tiempo en un backend caído."""
        with pytest.raises(RunAbortedError):
            comparator_que_cae.run(manual_df, normativa_df, max_workers=1)
        assert comparator_que_cae.grader.llamadas_analyze < len(manual_df), (
            "con el backend caído se siguió llamando al modelo en todas las secciones"
        )

    def test_conserva_los_parciales(self, comparator_que_cae, manual_df, normativa_df):
        with pytest.raises(RunAbortedError) as exc:
            comparator_que_cae.run(manual_df, normativa_df, max_workers=1)
        parciales = exc.value.parciales
        assert parciales is not None and len(parciales) == len(manual_df)

    def test_ninguna_fila_sale_como_no_aplica(self, comparator_que_cae, manual_df, normativa_df):
        """El corazón del ítem 1."""
        with pytest.raises(RunAbortedError) as exc:
            comparator_que_cae.run(manual_df, normativa_df, max_workers=1)
        niveles = set(exc.value.parciales["nivel_cumplimiento"].dropna())
        assert "no_aplica" not in niveles, (
            "una corrida abortada volvió a producir veredictos 'no_aplica'"
        )

    def test_las_filas_no_procesadas_quedan_como_omitidas(
        self, comparator_que_cae, manual_df, normativa_df
    ):
        with pytest.raises(RunAbortedError) as exc:
            comparator_que_cae.run(manual_df, normativa_df, max_workers=1)
        estados = set(exc.value.parciales["estado_analisis"])
        assert "omitido" in estados
        assert "error_modelo" in estados, "la fila que provocó el aborto debe distinguirse"


class TestDegradacionPorFila:

    def test_un_fallo_de_parseo_no_detiene_la_corrida(self, normativa_df, manual_df):
        objetivo = manual_df.iloc[1]["jerarquia"]
        grader = FakeGrader(
            fallar_en=lambda row: (
                AnalysisParseError("json inválido") if row.get("jerarquia") == objetivo else None
            )
        )
        comparator = DocumentComparator(
            normativa_index=FakeIndex(normativa_df=normativa_df, plan={}),
            llm_grader=grader,
        )
        out = comparator.run(manual_df, normativa_df, max_workers=1)

        assert len(out) == len(manual_df), "la corrida debía terminar pese al fallo de una fila"
        fallida = out[out["jerarquia"] == objetivo].iloc[0]
        assert fallida["estado_analisis"] == "error_parseo"
        assert fallida["nivel_cumplimiento"] is None

    def test_tres_fallos_seguidos_abortan(self, normativa_df, manual_df):
        """Varios fallos consecutivos dejan de parecer casualidad.

        La cota no es exactamente `max_fallos`: el envío mantiene una ventana de tareas
        en vuelo (`max_workers * 2`) y el trabajo ya despachado no se puede des-ejecutar.
        Lo que la corrida garantiza es cortar poco después del umbral, no en el instante
        exacto — y sobre todo, no llegar hasta el final.
        """
        max_fallos, workers = 3, 1
        ventana = max(workers * 2, 2)

        grader = FakeGrader(fallar_en=lambda row: AnalysisParseError("json inválido"))
        comparator = DocumentComparator(
            normativa_index=FakeIndex(normativa_df=normativa_df, plan={}),
            llm_grader=grader,
            max_fallos_consecutivos=max_fallos,
        )
        with pytest.raises(RunAbortedError):
            comparator.run(manual_df, normativa_df, max_workers=workers)

        assert grader.llamadas_analyze <= max_fallos + ventana, (
            "se siguió llamando al modelo mucho después de alcanzar el umbral de fallos"
        )
        assert grader.llamadas_analyze < len(manual_df), (
            "la corrida recorrió el manual entero pese a fallar en todas las filas"
        )


class TestSinErroresEnLosCamposDeAnalisis:

    def test_el_texto_del_error_no_viaja_en_analisis_general(self, normativa_df, manual_df):
        """El Excel y el JSON nunca deben contener un mensaje de excepción."""
        marca = "TRAZA-UNICA-DEL-ERROR-9271"
        grader = FakeGrader(fallar_en=lambda row: AnalysisParseError(marca))
        comparator = DocumentComparator(
            normativa_index=FakeIndex(normativa_df=normativa_df, plan={}),
            llm_grader=grader,
            max_fallos_consecutivos=999,   # que degrade todas, sin abortar
        )
        out = comparator.run(manual_df, normativa_df, max_workers=1)

        for col in ("analisis_general", "analisis_lexico",
                    "analisis_semantico_top1", "analisis_semantico_top2",
                    "analisis_semantico_top3"):
            textos = " ".join(str(v) for v in out[col].tolist())
            assert marca not in textos, f"el error se filtró dentro de '{col}'"

    def test_el_excel_exportado_tampoco_lo_lleva(self, tmp_path, normativa_df, manual_df):
        import pandas as pd

        marca = "TRAZA-UNICA-DEL-ERROR-9271"
        grader = FakeGrader(fallar_en=lambda row: AnalysisParseError(marca))
        comparator = DocumentComparator(
            normativa_index=FakeIndex(normativa_df=normativa_df, plan={}),
            llm_grader=grader,
            max_fallos_consecutivos=999,
        )
        out = comparator.run(manual_df, normativa_df, max_workers=1)
        destino = comparator.export_excel(out, tmp_path / "reporte.xlsx")

        contenido = pd.read_excel(destino).astype(str).to_string()
        assert marca not in contenido

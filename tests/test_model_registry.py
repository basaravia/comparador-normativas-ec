"""Ítem 4 — validar el modelo antes de gastar un token, y no colar falsos positivos.

Dos mitades que atacan el mismo riesgo desde extremos opuestos:

  · el **preflight**, para que un modelo mal configurado se descubra antes de arrancar y
    no a mitad de una corrida de horas;
  · la **degradación del grading**, para que un parseo roto nunca se traduzca en
    candidatos marcados como relevantes.

La segunda es la más importante. Es el riesgo espejo del ítem 1: allí se perdían secciones
de forma ruidosa; aquí se afirmaba haber verificado algo que nadie verificó, en silencio.

Ninguna prueba toca la red: `list_models` se sustituye por monkeypatch.
"""
from __future__ import annotations

import openai
import pytest

from src.errors import LLMUnavailableError, ModelNotFoundError
from src.llm_grader import LLMGrader
from src.model_registry import (
    limpiar_cache,
    modelos_disponibles,
    preflight,
    validar_modelo,
)
from src.providers import Provider, ProviderSpec
from tests.fixtures import FakeChatModel

SPEC = ProviderSpec(proveedor=Provider.DMR)
MODELOS = ["ai/granite-embedding:latest", "docker.io/ai/gemma4:latest"]


@pytest.fixture(autouse=True)
def _sin_cache():
    limpiar_cache()
    yield
    limpiar_cache()


@pytest.fixture
def listado(monkeypatch):
    """Sustituye el listado real. Devuelve un contador para afirmar sobre la caché."""
    llamadas = {"n": 0}

    def _fake(spec):
        llamadas["n"] += 1
        return list(MODELOS)

    monkeypatch.setattr("src.model_registry.list_models", _fake)
    return llamadas


class TestListado:

    def test_devuelve_los_modelos_ordenados(self, listado):
        assert modelos_disponibles(SPEC) == sorted(MODELOS)

    def test_cachea_para_no_golpear_el_endpoint_en_cada_rerun(self, listado):
        """Streamlit reejecuta el script en cada interacción; sin caché, mover un
        slider consultaría el proveedor."""
        modelos_disponibles(SPEC)
        modelos_disponibles(SPEC)
        assert listado["n"] == 1

    def test_un_endpoint_caido_devuelve_vacio_en_vez_de_lanzar(self, monkeypatch):
        """Esto alimenta los desplegables: una excepción aquí dejaría la app sin
        arrancar por algo que solo debería degradar la experiencia."""
        def _explota(spec):
            raise openai.APIConnectionError(request=None)  # type: ignore[arg-type]

        monkeypatch.setattr("src.model_registry.list_models", _explota)
        assert modelos_disponibles(SPEC) == []


class TestValidacion:

    def test_un_modelo_existente_pasa(self, listado):
        validar_modelo(SPEC, "docker.io/ai/gemma4:latest")   # no lanza

    def test_un_modelo_inexistente_lanza_con_la_lista_real(self, listado):
        with pytest.raises(ModelNotFoundError) as exc:
            validar_modelo(SPEC, "modelo-que-no-existe")

        mensaje = str(exc.value)
        assert "modelo-que-no-existe" in mensaje
        assert "gemma4" in mensaje, (
            "el error debe decir qué modelos SÍ hay; 'no existe' a secas obliga a adivinar"
        )

    def test_si_no_se_puede_listar_se_aborta_en_vez_de_asumir(self, monkeypatch):
        monkeypatch.setattr("src.model_registry.list_models", lambda spec: [])
        with pytest.raises(LLMUnavailableError):
            validar_modelo(SPEC, "cualquiera")

    def test_un_proveedor_sin_listado_no_inventa_un_error(self):
        """Sin endpoint de listado no hay evidencia de que falte: callar es correcto."""
        validar_modelo(ProviderSpec(proveedor=Provider.LOCAL_ST), "lo-que-sea")


class TestPreflight:

    def test_ok_cuando_todo_existe(self, listado):
        r = preflight(SPEC, "docker.io/ai/gemma4:latest", SPEC, "ai/granite-embedding:latest")
        assert r and r.ok and not r.mensajes

    def test_detecta_el_modelo_de_embeddings_tambien(self, listado):
        """Un embeddings mal configurado construye un índice inservible y el fallo
        aparece cuando ya se pagó el tiempo de indexación."""
        r = preflight(SPEC, "docker.io/ai/gemma4:latest", SPEC, "embeddings-fantasma")
        assert not r.ok
        assert any("embeddings" in m for m in r.mensajes)

    def test_reporta_los_dos_problemas_a_la_vez(self, listado):
        """Uno por intento obligaría a arrancar varias veces para descubrirlos todos."""
        r = preflight(SPEC, "llm-fantasma", SPEC, "embeddings-fantasma")
        assert len(r.mensajes) == 2


class TestGradingNuncaAsumeRelevante:
    """El corazón del ítem 4."""

    CANDIDATOS = [
        {"element_id": "a1", "numero": "5", "contenido": "texto a"},
        {"element_id": "a2", "numero": "8", "contenido": "texto b"},
    ]

    def _grader(self, respuestas):
        return LLMGrader(
            chat_grader=FakeChatModel(respuestas=respuestas),
            chat_analyst=FakeChatModel(),
        )

    def test_un_json_irreparable_deja_los_candidatos_indeterminados(self):
        grader = self._grader(["esto no es JSON ni de lejos"] * 6)
        salida = grader.grade_candidates("sección del manual", self.CANDIDATOS)

        assert len(salida) == 2
        for c in salida:
            assert c["relevante"] is None, (
                "un parseo roto marcó candidatos como relevantes: eso es un falso "
                "positivo de cumplimiento en el papel de trabajo"
            )
            assert c["requiere_revision"] is True
            assert c["motivo_revision"] == "grading_no_parseable"

    def test_ningun_candidato_sale_como_relevante_true(self):
        grader = self._grader(["{ roto"] * 6)
        salida = grader.grade_candidates("sección", self.CANDIDATOS)
        assert not any(c["relevante"] is True for c in salida)

    def test_un_candidato_ausente_de_la_respuesta_no_se_asume_relevante(self):
        """El modelo parseó bien pero se dejó uno fuera. Ausencia de juicio no es
        juicio favorable — y es más difícil de ver porque el resto es válido."""
        solo_a1 = (
            '{"candidatos": [{"element_id": "a1", "relevante": true, '
            '"score": 0.9, "razon": "regula lo mismo"}]}'
        )
        salida = self._grader([solo_a1]).grade_candidates("sección", self.CANDIDATOS)
        por_id = {c["element_id"]: c for c in salida}

        assert por_id["a1"]["relevante"] is True
        assert por_id["a2"]["relevante"] is None
        assert por_id["a2"]["motivo_revision"] == "candidato_ausente_del_grading"

    def test_una_respuesta_valida_funciona_normalmente(self):
        ambos = (
            '{"candidatos": ['
            '{"element_id": "a1", "relevante": true, "score": 0.9, "razon": "sí"},'
            '{"element_id": "a2", "relevante": false, "score": 0.1, "razon": "no"}]}'
        )
        salida = self._grader([ambos]).grade_candidates("sección", self.CANDIDATOS)
        por_id = {c["element_id"]: c for c in salida}

        assert por_id["a1"]["relevante"] is True
        assert por_id["a2"]["relevante"] is False
        assert all(c["requiere_revision"] is False for c in salida)

    def test_un_fallo_de_infraestructura_sigue_abortando(self):
        """La degradación es para fallos de contenido. Si el backend cae, manda el
        ítem 1: se detiene la corrida."""
        grader = LLMGrader(
            chat_grader=FakeChatModel(excepcion=openai.APIConnectionError(request=None)),  # type: ignore[arg-type]
            chat_analyst=FakeChatModel(),
        )
        with pytest.raises(LLMUnavailableError):
            grader.grade_candidates("sección", self.CANDIDATOS)


class TestPropagacionAlPipeline:

    def test_los_indeterminados_no_entran_al_analisis_pero_se_cuentan(
        self, normativa_df, manual_df
    ):
        """No basta con excluirlos: si desaparecen sin dejar rastro, el auditor no
        sabe que hubo candidatos sin evaluar."""
        from src.comparator import DocumentComparator
        from tests.fixtures import FakeIndex

        art = normativa_df.iloc[0]["element_id"]
        plan = {fila["embed_text"]: [art] for _, fila in manual_df.iterrows()}

        class GraderIndeterminado:
            llamadas_analyze = 0

            def grade_candidates(self, texto, candidatos):
                return [{**c, "relevante": None, "requiere_revision": True,
                         "motivo_revision": "grading_no_parseable"} for c in candidatos]

            def analyze_comparison(self, row, lexicos, validados):
                GraderIndeterminado.llamadas_analyze += 1
                from src.llm_grader import ComparisonResult
                assert validados == [], (
                    "un candidato indeterminado llegó al análisis como si estuviera validado"
                )
                return ComparisonResult(
                    tipo_coincidencia="ninguna", nivel_cumplimiento="no_aplica",
                    analisis_general="sin candidatos determinados",
                )

        comparator = DocumentComparator(
            normativa_index=FakeIndex(normativa_df=normativa_df, plan=plan),
            llm_grader=GraderIndeterminado(),
        )
        out = comparator.run(manual_df, normativa_df, max_workers=1)

        assert out["requiere_revision"].any()
        assert (out["candidatos_indeterminados"] > 0).any()

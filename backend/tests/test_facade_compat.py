"""Fija el contrato público que consume `master.ipynb` (supuesto S5 del plan).

El ítem 5 convierte el resultado de `run()` en un modelo N:N y `results_df` pasa a ser una
propiedad derivada. El plan promete que el notebook seguirá funcionando, pero hasta ahora
nada lo verificaba: se comprobaba a mano, abriendo el notebook.

Estas pruebas existen para que ese refactor rompa **aquí** y no en la sesión de trabajo de
alguien. El contrato es deliberadamente pequeño — es exactamente lo que el notebook llama:

    normativa_parser.parse_pdf(...)   ManualParser.parse_pdf(...)
    comparator.run_sample(...)        comparator.export_excel(...)

No se prueba el comportamiento interno: se prueba la **forma** de la fachada. Si el ítem 5
cambia lo que hay dentro pero conserva la superficie, estas pruebas deben seguir en verde.
"""
from __future__ import annotations

import inspect

import pandas as pd
import pytest

from src import DocumentComparator, ManualParser, NormativaParser
from tests.fixtures import FakeGrader, FakeIndex


class TestSuperficiePublica:
    """Los métodos que el notebook invoca existen y aceptan lo que él les pasa."""

    def test_los_parsers_exponen_parse_pdf(self):
        for cls in (NormativaParser, ManualParser):
            assert hasattr(cls, "parse_pdf"), f"{cls.__name__}.parse_pdf desapareció"
            params = inspect.signature(cls.parse_pdf).parameters
            assert "pdf_path" in params or len(params) >= 2, (
                f"{cls.__name__}.parse_pdf ya no acepta una ruta posicional"
            )

    def test_comparator_expone_run_sample_y_export_excel(self):
        for nombre in ("run", "run_sample", "export_excel", "summary"):
            assert hasattr(DocumentComparator, nombre), (
                f"DocumentComparator.{nombre} desapareció; el notebook lo usa"
            )

    def test_run_sample_acepta_n_y_max_workers(self):
        params = inspect.signature(DocumentComparator.run_sample).parameters
        for esperado in ("manual_df", "normativa_df", "n", "max_workers"):
            assert esperado in params, f"run_sample perdió el parámetro '{esperado}'"


class TestFormaDelResultado:
    """`run_sample` devuelve algo que el notebook pueda tratar como DataFrame."""

    @pytest.fixture
    def comparator(self, normativa_df, manual_df):
        plan = {
            fila["embed_text"]: ["LEY-A-2026.pdf_0003"]
            for _, fila in manual_df.iterrows()
        }
        indice = FakeIndex(normativa_df=normativa_df, plan=plan)
        return DocumentComparator(normativa_index=indice, llm_grader=FakeGrader())

    def test_run_sample_devuelve_dataframe(self, comparator, manual_df, normativa_df):
        out = comparator.run_sample(manual_df, normativa_df, n=3, max_workers=1)
        assert isinstance(out, pd.DataFrame), (
            "run_sample dejó de devolver un DataFrame: el notebook hace .head() sobre esto"
        )
        assert len(out) == 3

    def test_conserva_las_columnas_de_analisis(self, comparator, manual_df, normativa_df):
        out = comparator.run_sample(manual_df, normativa_df, n=2, max_workers=1)
        # Las que el notebook muestra y sobre las que agrupa.
        for col in ("nivel_cumplimiento", "tipo_coincidencia", "analisis_general", "brechas"):
            assert col in out.columns, f"el resultado perdió la columna '{col}'"

    def test_conserva_las_columnas_de_entrada_del_manual(self, comparator, manual_df, normativa_df):
        out = comparator.run_sample(manual_df, normativa_df, n=2, max_workers=1)
        for col in ("jerarquia", "titulo_seccion", "chunk_id"):
            assert col in out.columns, (
                f"el resultado ya no arrastra '{col}' del manual; el notebook la usa para "
                "identificar la sección"
            )

    def test_summary_agrupa_por_nivel(self, comparator, manual_df, normativa_df):
        out = comparator.run_sample(manual_df, normativa_df, n=4, max_workers=1)
        resumen = DocumentComparator.summary(out)
        assert isinstance(resumen, pd.DataFrame)
        assert "secciones" in resumen.columns and "porcentaje" in resumen.columns


class TestExportacionExcel:
    """El Excel se genera y se puede volver a leer. El notebook lo abre a mano después."""

    def test_export_excel_escribe_un_archivo_legible(self, tmp_path, normativa_df, manual_df):
        indice = FakeIndex(normativa_df=normativa_df, plan={})
        comparator = DocumentComparator(normativa_index=indice, llm_grader=FakeGrader())
        out = comparator.run_sample(manual_df, normativa_df, n=3, max_workers=1)

        destino = tmp_path / "reporte.xlsx"
        devuelto = comparator.export_excel(out, destino)

        assert devuelto == destino and destino.exists()
        vuelta = pd.read_excel(destino)
        assert len(vuelta) == 3, "el Excel no conserva una fila por sección analizada"
        assert "nivel_cumplimiento" in vuelta.columns

    def test_export_excel_aplana_las_listas(self, tmp_path, normativa_df, manual_df):
        """openpyxl no puede escribir listas; si el aplanado desaparece, falla al exportar."""
        indice = FakeIndex(normativa_df=normativa_df, plan={})
        comparator = DocumentComparator(normativa_index=indice, llm_grader=FakeGrader())
        out = comparator.run_sample(manual_df, normativa_df, n=2, max_workers=1)

        assert isinstance(out.iloc[0]["brechas"], list), (
            "el DataFrame en memoria debe seguir llevando listas; aplanar es cosa del export"
        )
        vuelta = pd.read_excel(comparator.export_excel(out, tmp_path / "r.xlsx"))
        assert not isinstance(vuelta.iloc[0]["brechas"], list)

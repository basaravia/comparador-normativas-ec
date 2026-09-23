"""Pruebas funcionales de DocumentComparator.run() — sin red, sin LLM real.

Usa stubs de NormativaIndex y LLMGrader que replican su interfaz pública
(lexical_scan/semantic_search/rerank y grade_candidates/analyze_comparison)
sin tocar FAISS, el reranker CrossEncoder ni Docker Model Runner. El objetivo
es validar el orquestador (concurrencia, merge de resultados, y el nuevo
``progress_callback``), no la calidad de la búsqueda o el LLM — eso lo cubre
la prueba E2E con DMR real.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.comparator import DocumentComparator
from src.llm_grader import ComparisonResult


class _StubIndex:
    """Reemplaza NormativaIndex: misma interfaz pública, sin FAISS ni reranker."""

    def lexical_scan(self, text: str, normativa_df: pd.DataFrame) -> list[dict]:
        return []

    def semantic_search(self, query: str, top_k: int = 5, min_score: float = 0.30) -> list[dict]:
        return []

    def rerank(self, query: str, candidates: list[dict], top_n: int = 3) -> list[dict]:
        return candidates[:top_n]


class _StubGrader:
    """Reemplaza LLMGrader: mismo contrato público, respuestas fijas sin llamar a DMR."""

    def __init__(self, nivel: str = "no_aplica"):
        self._nivel = nivel
        self.analyze_calls: list[dict] = []

    def grade_candidates(self, manual_text: str, candidates: list[dict]) -> list[dict]:
        return []

    def analyze_comparison(self, manual_row, lexical_matches, validated_candidates) -> ComparisonResult:
        self.analyze_calls.append(dict(manual_row))
        return ComparisonResult(
            tipo_coincidencia="ninguna",
            nivel_cumplimiento=self._nivel,
            analisis_general=f"stub para {manual_row.get('jerarquia')}",
        )


@pytest.fixture
def manual_df() -> pd.DataFrame:
    return pd.DataFrame([
        {"texto": "Sección sobre gestión de riesgos.", "jerarquia": "1.1"},
        {"texto": "Sección sobre control interno.", "jerarquia": "1.2"},
        {"texto": "Sección sobre reporte de incidentes.", "jerarquia": "1.3"},
    ])


@pytest.fixture
def normativa_df() -> pd.DataFrame:
    return pd.DataFrame([{"numero": "1", "tipo_elemento": "articulo", "encabezado": "Objeto"}])


def test_run_invokes_progress_callback_once_per_row_with_correct_counters(manual_df, normativa_df):
    comparator = DocumentComparator(normativa_index=_StubIndex(), llm_grader=_StubGrader())

    calls: list[tuple[int, int, str]] = []

    def on_progress(done: int, total: int, row: dict) -> None:
        calls.append((done, total, row.get("jerarquia")))

    result_df = comparator.run(
        manual_df=manual_df, normativa_df=normativa_df, max_workers=1, progress_callback=on_progress
    )

    assert len(calls) == 3, "progress_callback debe invocarse exactamente una vez por fila"
    assert [c[0] for c in calls] == [1, 2, 3], "el contador 'completadas' debe ser secuencial con 1 hilo"
    assert all(c[1] == 3 for c in calls), "el contador 'total' debe ser constante e igual al total de filas"
    assert {c[2] for c in calls} == {"1.1", "1.2", "1.3"}, "cada fila procesada debe reportarse"
    assert len(result_df) == 3


def test_run_without_progress_callback_does_not_raise(manual_df, normativa_df):
    """progress_callback es opcional (Optional[Callable] = None) — el pipeline
    original (usado en master.ipynb) no debe romperse por el nuevo parámetro."""
    comparator = DocumentComparator(normativa_index=_StubIndex(), llm_grader=_StubGrader())

    result_df = comparator.run(manual_df=manual_df, normativa_df=normativa_df, max_workers=1)

    assert len(result_df) == 3


def test_run_output_contains_expected_analysis_columns(manual_df, normativa_df):
    comparator = DocumentComparator(normativa_index=_StubIndex(), llm_grader=_StubGrader(nivel="cumple"))

    result_df = comparator.run(manual_df=manual_df, normativa_df=normativa_df, max_workers=1)

    expected_cols = {
        "articulos_lexicos", "articulos_semanticos_raw", "articulos_validados",
        "tipo_coincidencia", "nivel_cumplimiento", "analisis_general",
        "brechas", "ner_general", "entidades_financieras", "entidades_normativas",
    }
    assert expected_cols.issubset(result_df.columns)
    assert set(result_df["nivel_cumplimiento"]) == {"cumple"}
    # las columnas originales del manual (p.ej. jerarquia) se preservan por fila
    assert set(result_df["jerarquia"]) == {"1.1", "1.2", "1.3"}


def test_run_calls_analyze_comparison_exactly_once_per_row_with_concurrency(manual_df, normativa_df):
    grader = _StubGrader()
    comparator = DocumentComparator(normativa_index=_StubIndex(), llm_grader=grader)

    comparator.run(manual_df=manual_df, normativa_df=normativa_df, max_workers=2)

    assert len(grader.analyze_calls) == 3
    assert {c.get("jerarquia") for c in grader.analyze_calls} == {"1.1", "1.2", "1.3"}

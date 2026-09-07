"""Prueba de evaluación de retrieval en español (ítem 8).

Verifica que el arnés de evaluación funcione correctamente sobre el dataset
dorado `tests/data/retrieval_gold_es.yaml` y produzca métricas válidas.
"""
from __future__ import annotations

import pandas as pd
import pytest

from scripts.eval_retrieval import (
    calcular_metricas,
    cargar_dataset_oro,
    evaluar_configuracion,
)
from tests.fixtures import FakeEmbeddingBackend, normativa_df


@pytest.mark.retrieval
def test_arnes_de_evaluacion_de_retrieval():
    df = normativa_df()
    backend = FakeEmbeddingBackend(dim=16)

    reporte = evaluar_configuracion(df, backend, usar_chunking=True, top_k=5)

    assert "metricas" in reporte
    metricas = reporte["metricas"]
    assert "recall@1" in metricas
    assert "recall@5" in metricas
    assert "mrr" in metricas

    assert reporte["n_consultas"] > 0
    assert 0.0 <= metricas["recall@5"] <= 1.0
    assert 0.0 <= metricas["mrr"] <= 1.0


def test_calcular_metricas_con_datos_conocidos():
    resultados = [
        {
            "id": "q1",
            "esperados": [{"doc_id": "D1", "numero": "1"}],
            "recuperados": [
                {"doc_id": "D1", "numero": "1"},
                {"doc_id": "D2", "numero": "2"},
            ],
        },
        {
            "id": "q2",
            "esperados": [{"doc_id": "D2", "numero": "2"}],
            "recuperados": [
                {"doc_id": "D1", "numero": "1"},
                {"doc_id": "D2", "numero": "2"},
            ],
        },
    ]
    m = calcular_metricas(resultados, k_list=(1, 2))
    assert m["recall@1"] == 0.5
    assert m["recall@2"] == 1.0
    assert m["mrr"] == 0.75  # (1/1 + 1/2) / 2 = 0.75

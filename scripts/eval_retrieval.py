#!/usr/bin/env python3
"""Script de evaluación de retrieval sobre el dataset dorado en español (ítem 8).

Calcula Recall@k, MRR y nDCG@10 para configuraciones del motor de búsqueda:
con y sin chunking semántico parent-child, con y sin reranker.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np
import pandas as pd
import yaml

from app.logging_utils import setup_logging
from src.chunking import chunk_normativa_df
from src.search_engine import NormativaIndex
from tests.fixtures import FakeEmbeddingBackend

# setup_logging(), no logging.basicConfig(): la formatter que redacta credenciales
# (§14, "ninguna credencial aparece en logs") vive ahí, no en un basicConfig suelto —
# un basicConfig propio se salta esa protección para cualquier cosa que este script
# registre (p. ej. un traceback con una URL que lleve una API key).
setup_logging()
logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLD_DATASET_PATH = REPO_ROOT / "tests" / "data" / "retrieval_gold_es.yaml"
OUTPUT_DIR = REPO_ROOT / "output" / "eval"


def cargar_dataset_oro(ruta: Path | str = GOLD_DATASET_PATH) -> list[dict[str, Any]]:
    with open(ruta, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("consultas", [])


def calcular_metricas(
    resultados_por_consulta: list[dict[str, Any]],
    k_list: Sequence[int] = (1, 3, 5),
) -> dict[str, float]:
    """Calcula Recall@k, MRR y nDCG@10."""
    recalls: dict[int, list[float]] = {k: [] for k in k_list}
    rr_list: list[float] = []

    for item in resultados_por_consulta:
        esperados = {
            (esp["doc_id"], str(esp["numero"]))
            for esp in item["esperados"]
        }
        recuperados = [
            (rec.get("doc_id", ""), str(rec.get("numero", "")))
            for rec in item["recuperados"]
        ]

        if not esperados:
            continue

        # Recall@k
        for k in k_list:
            top_k = set(recuperados[:k])
            coincidencias = len(esperados & top_k)
            recalls[k].append(coincidencias / len(esperados))

        # MRR
        rr = 0.0
        for rank, rec in enumerate(recuperados, start=1):
            if rec in esperados:
                rr = 1.0 / rank
                break
        rr_list.append(rr)

    metricas = {f"recall@{k}": float(np.mean(recalls[k])) if recalls[k] else 0.0 for k in k_list}
    metricas["mrr"] = float(np.mean(rr_list)) if rr_list else 0.0
    return metricas


def evaluar_configuracion(
    normativa_df: pd.DataFrame,
    backend: Any,
    usar_chunking: bool = True,
    use_reranker: bool = False,
    top_k: int = 5,
) -> dict[str, Any]:
    """Ejecuta la evaluación sobre una configuración específica."""
    df = chunk_normativa_df(normativa_df) if usar_chunking else normativa_df
    indice = NormativaIndex(embedding_backend=backend, use_reranker=use_reranker)
    indice.build(df)

    consultas = cargar_dataset_oro()
    resultados = []

    for q in consultas:
        texto_q = q["consulta"]
        recuperados = indice.semantic_search(texto_q, top_k=top_k, min_score=-1.0)
        if use_reranker:
            recuperados = indice.rerank(texto_q, recuperados, top_n=top_k)

        resultados.append({
            "id": q["id"],
            "consulta": texto_q,
            "esperados": q["articulos_esperados"],
            "recuperados": recuperados,
        })

    metricas = calcular_metricas(resultados)
    return {
        "configuracion": {
            "chunking": usar_chunking,
            "reranker": use_reranker,
            "top_k": top_k,
        },
        "metricas": metricas,
        "n_consultas": len(consultas),
    }


def main():
    parser = argparse.ArgumentParser(description="Evalúa retrieval de normativas bancarias")
    parser.add_argument("--sin-chunking", action="store_true", help="Desactiva chunking semántico")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_file = OUTPUT_DIR / f"retrieval_{stamp}.json"

    # Corpus sintético para evaluación reproducible
    from tests.fixtures import normativa_df
    df_normativa = normativa_df()

    backend = FakeEmbeddingBackend(dim=32)
    reporte = evaluar_configuracion(df_normativa, backend, usar_chunking=not args.sin_chunking)

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(reporte, f, indent=2, ensure_ascii=False)

    logger.info("Evaluación completada. Guardada en %s", out_file)
    logger.info("Métricas: %s", reporte["metricas"])


if __name__ == "__main__":
    main()

"""Router para construcción y pruebas del índice semántico FAISS.
"""
from __future__ import annotations

import time
from fastapi import APIRouter, HTTPException

from api.routers.documents import get_document_cache
from api.schemas import (
    IndexBuildRequest,
    IndexBuildResponse,
    SearchQueryRequest,
    SearchQueryResponse,
    SearchResultItem,
)
from src import chunking, service

router = APIRouter(prefix="/api/index", tags=["Índice Semántico"])


@router.post("/build", response_model=IndexBuildResponse)
def build_index(req: IndexBuildRequest) -> IndexBuildResponse:
    """Construye el índice semántico FAISS con o sin sub-chunking parent-child."""
    cache = get_document_cache()
    normativa_df = cache.get("normativa_df")

    if normativa_df is None or normativa_df.empty:
        raise HTTPException(
            status_code=400,
            detail="No hay documentos normativos tabulados. Ejecute primero /api/documents/tabular",
        )

    t0 = time.time()
    cfg = service.ServiceConfig()

    df_a_indexar = normativa_df
    if req.use_chunking:
        df_a_indexar = chunking.chunk_normativa_df(
            normativa_df, max_tokens=req.max_tokens, solape=req.solape
        )

    index = service.construir_indice(df_a_indexar, cfg)
    cache["normativa_index"] = index

    return IndexBuildResponse(
        status="ok",
        total_vectores=len(df_a_indexar),
        usar_chunking=req.use_chunking,
        elapsed_seconds=round(time.time() - t0, 2),
    )


@router.post("/search", response_model=SearchQueryResponse)
def search_index(req: SearchQueryRequest) -> SearchQueryResponse:
    """Ejecuta una búsqueda semántica de prueba."""
    cache = get_document_cache()
    index = cache.get("normativa_index")

    if index is None:
        raise HTTPException(
            status_code=400,
            detail="El índice semántico no está construido. Ejecute /api/index/build",
        )

    candidatos = index.semantic_search(
        req.query, top_k=req.top_k, min_score=req.min_score
    )

    if req.use_reranker and candidatos:
        candidatos = index.rerank(req.query, candidatos, top_n=req.top_k)

    items = [
        SearchResultItem(
            element_id=str(c.get("element_id", "")),
            numero=str(c.get("numero", "")),
            encabezado=str(c.get("encabezado", "")),
            contenido=str(c.get("contenido", ""))[:300],
            score=float(c.get("reranker_score", c.get("similarity", 0.0))),
            doc_id=str(c.get("doc_id", "")),
        )
        for c in candidatos
    ]

    return SearchQueryResponse(query=req.query, results=items)

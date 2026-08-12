"""Phase 2: Motor de búsqueda — índice FAISS semántico + escaneo léxico.

NormativaIndex:
  - build()           → construye índice FAISS sobre artículos de la normativa
  - semantic_search() → Top-K por similitud coseno (IndexFlatIP + L2-norm)
  - rerank()          → reordena candidatos con CrossEncoder local (optional)
  - lexical_scan()    → detecta referencias explícitas a artículos normativos
"""
from __future__ import annotations

import re
import logging
from pathlib import Path
from typing import Optional

import pandas as pd

# faiss se importa lazy (en build/load) para evitar conflicto de libs nativas con Docling
from .embeddings import EmbeddingBackend
from .config import (
    FAISS_TOP_K,
    RERANKER_MODEL,
    RERANKER_TOP_N,
    MIN_SEMANTIC_SCORE,
)

logger = logging.getLogger(__name__)

# Detecta referencias explícitas del tipo "Art. 5", "Artículo 12a"
_PAT_ART_REF = re.compile(
    r'\b[Aa]rt(?:ículo|iculo)?\s*\.?\s*(\d+[\w]*)\b'
)
# Detecta referencias a resoluciones y circulares por número
_PAT_RESOL_REF = re.compile(
    r'\b(?:Resolución|Circular|Decreto|Norma)\s+(?:No\.?\s*)?([A-ZÁÉÍÓÚ\d\-\.]+)\b',
    re.IGNORECASE,
)


class NormativaIndex:
    """Índice FAISS sobre artículos normativos con búsqueda semántica y léxica.

    Workflow:
        index = NormativaIndex(backend)
        index.build(normativa_df)

        # Búsqueda semántica
        results = index.semantic_search("política de crédito", top_k=5)

        # Reranking opcional con CrossEncoder local
        results = index.rerank("política de crédito", results, top_n=3)

        # Escaneo léxico
        refs = index.lexical_scan("...según Art. 5 y Art. 12...")
    """

    def __init__(
        self,
        embedding_backend: EmbeddingBackend,
        use_reranker: bool = True,
        reranker_model: str = RERANKER_MODEL,
    ) -> None:
        self._backend = embedding_backend
        self._use_reranker = use_reranker
        self._index = None  # faiss.IndexFlatIP, lazy-loaded
        self._df: Optional[pd.DataFrame] = None
        self._cross_encoder = None

        if use_reranker:
            # DMR/vllm-metal no soporta reranking mode en Apple Silicon —
            # se usa un CrossEncoder local (sentence-transformers) en su lugar.
            import torch
            from sentence_transformers import CrossEncoder

            device = "mps" if torch.backends.mps.is_available() else "cpu"
            model_kwargs = {"dtype": torch.float32}
            if device == "mps":
                # Qwen3-Reranker produce NaN en MPS con el kernel de atención
                # optimizado (SDPA); "eager" evita ese bug de precisión.
                model_kwargs["attn_implementation"] = "eager"

            logger.info("Cargando reranker local: %s (device=%s)", reranker_model, device)
            self._cross_encoder = CrossEncoder(reranker_model, device=device, model_kwargs=model_kwargs)

    # ── Construcción del índice ───────────────────────────────────────────

    def build(
        self,
        normativa_df: pd.DataFrame,
        text_col: str = "embed_text",
    ) -> None:
        """Construye el índice FAISS a partir del DataFrame de normativa."""
        logger.info("Construyendo índice FAISS sobre %d elementos…", len(normativa_df))
        texts = normativa_df[text_col].fillna("").tolist()

        import faiss
        # Defecto 3 de §2.2 del plan: el prefijo lo decide el backend (vía
        # `passage_prefix`/`query_prefix`), no `search_engine.py`. DMR no lo
        # quiere (backend.passage_prefix == ""); el backend local de
        # sentence-transformers sí (necesita "passage: " para e5). `getattr`
        # con default "" cubre además cualquier backend/doble que no lo declare.
        prefix = getattr(self._backend, "passage_prefix", "")
        vecs = self._backend.encode(texts, prefix=prefix)
        dim = vecs.shape[1]

        self._index = faiss.IndexFlatIP(dim)
        self._index.add(vecs)
        self._df = normativa_df.reset_index(drop=True)
        logger.info("Índice listo: %d vectores, dim=%d", self._index.ntotal, dim)

    def save(self, path: str | Path) -> None:
        """Persiste el índice FAISS y los metadatos del DataFrame."""
        import faiss
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self._index, str(path / "index.faiss"))
        self._df.to_json(path / "normativa_meta.json", orient="records", force_ascii=False)
        logger.info("Índice guardado en %s", path)

    def load(self, path: str | Path) -> None:
        """Carga índice FAISS y metadatos desde disco."""
        import faiss
        path = Path(path)
        self._index = faiss.read_index(str(path / "index.faiss"))
        self._df = pd.read_json(path / "normativa_meta.json", orient="records")
        logger.info("Índice cargado: %d vectores", self._index.ntotal)

    # ── Búsqueda semántica ───────────────────────────────────────────────

    def semantic_search(
        self,
        query: str,
        top_k: int = FAISS_TOP_K,
        min_score: float = MIN_SEMANTIC_SCORE,
        source_filter: Optional[str] = None,
    ) -> list[dict]:
        """Retorna top-k artículos de la normativa más similares a la consulta."""
        self._require_index()

        # Ver comentario equivalente en build(): el prefijo de consulta también
        # depende del backend, no se fija a ciegas.
        prefix = getattr(self._backend, "query_prefix", "")
        vec = self._backend.encode([query], prefix=prefix)
        scores, indices = self._index.search(vec, top_k)
        scores = scores[0].tolist()
        indices = indices[0].tolist()

        results = []
        for score, idx in zip(scores, indices):
            if idx < 0 or score < min_score:
                continue
            row = self._df.iloc[idx].to_dict()
            if source_filter and row.get("doc_id") != source_filter:
                continue
            results.append({**row, "similarity": round(float(score), 4), "rank_faiss": len(results) + 1})

        return results

    # ── Reranking semántico ──────────────────────────────────────────────

    def rerank(
        self,
        query: str,
        candidates: list[dict],
        top_n: int = RERANKER_TOP_N,
    ) -> list[dict]:
        """Reordena candidatos FAISS con un CrossEncoder local."""
        if not candidates:
            return []

        if not self._use_reranker:
            return candidates[:top_n]

        documents = [
            f"Artículo {c.get('numero','?')}: {c.get('encabezado','')}\n"
            f"{str(c.get('contenido', c.get('texto', '')))[:600]}"
            for c in candidates
        ]

        scores = self._call_reranker(query, documents)

        ranked = sorted(zip(scores, candidates), key=lambda x: x[0], reverse=True)
        result = []
        for rank, (score, cand) in enumerate(ranked[:top_n], 1):
            result.append({**cand, "reranker_score": round(float(score), 4), "rank": rank})
        return result

    def _call_reranker(self, query: str, documents: list[str]) -> list[float]:
        """Puntúa cada documento contra la query con el CrossEncoder local."""
        pairs = [(query, doc) for doc in documents]
        return [float(s) for s in self._cross_encoder.predict(pairs)]

    # ── Escaneo léxico ───────────────────────────────────────────────────

    def lexical_scan(
        self,
        text: str,
        normativa_df: Optional[pd.DataFrame] = None,
    ) -> list[dict]:
        """Detecta referencias explícitas a artículos normativos en el texto del manual.

        Busca patrones como "Art. 5", "Artículo 12a", "artículo 3".

        Criterio de desambiguación entre normativas (defecto 2 de §2.2 del plan)
        --------------------------------------------------------------------
        Un número de artículo no identifica una normativa: "Art. 5" es solo un
        número. Con una única normativa cargada eso es inofensivo — solo hay un
        artículo con ese número. Con varias normativas cargadas a la vez puede
        haber más de un artículo con el mismo número (p. ej. el Art. 5 de una
        Ley y el Art. 5 de una Resolución distintas), y el texto del manual no
        siempre dice de cuál habla ("Conforme al Art. 5, se mantiene el
        registro…", sin nombrar la norma).

        Ante esa ambigüedad, esta función **no** devuelve los artículos de las
        dos normativas (generaría una arista de cobertura falsa hacia la
        normativa que el manual no citó) ni elige uno de forma arbitraria
        (fabricaría una cita que el texto no respalda: no hay ningún criterio
        textual para preferir una norma sobre otra). El criterio adoptado:

          · Si el número identifica un único artículo entre todas las
            normativas cargadas → hay match léxico, igual que antes.
          · Si el número lo comparten artículos de ≥2 normativas (`doc_id`)
            distintas → se descarta el match léxico para ese número: no queda
            ligado a ninguna. La sección no se queda sin analizar: la vía
            semántica (embeddings + reranker + grading LLM) sigue evaluándola
            contra el índice completo, y a diferencia del regex sí tiene el
            contenido del artículo — no solo su número — para decidir con
            evidencia trazable a cuál corresponde. Se prefiere "sin match
            léxico" a "match léxico equivocado o inventado".
        """
        df = normativa_df if normativa_df is not None else self._df
        if df is None:
            return []

        found_numbers = {m.group(1).strip() for m in _PAT_ART_REF.finditer(text)}
        if not found_numbers:
            return []

        df_arts = (
            df[df["tipo_elemento"] == "articulo"]
            if "tipo_elemento" in df.columns
            else df
        )
        if df_arts.empty:
            return []

        numeros = df_arts["numero"].astype(str).str.strip()

        # ¿Cuántas normativas distintas (doc_id) tienen un artículo con cada
        # número? Sin doc_id no hay forma de distinguir normativas: se asume
        # una sola fuente y no hay nada que desambiguar (comportamiento previo).
        docs_por_numero = (
            df_arts.assign(_numero=numeros).groupby("_numero")["doc_id"].nunique()
            if "doc_id" in df_arts.columns
            else None
        )

        matches: list[dict] = []
        ambiguos: set[str] = set()
        for (_, row), numero in zip(df_arts.iterrows(), numeros):
            if numero not in found_numbers:
                continue
            if docs_por_numero is not None and docs_por_numero.get(numero, 1) > 1:
                ambiguos.add(numero)
                continue
            matches.append({
                **row.to_dict(),
                "match_type": "exacto",
                "similarity": 1.0,
                "rank": len(matches) + 1,
            })

        if ambiguos:
            logger.info(
                "lexical_scan: %d número(s) de artículo ambiguo(s) entre "
                "normativas distintas, sin match léxico automático (%s). "
                "El texto cita el número pero no la normativa; queda a la "
                "vía semántica resolverlo con contexto.",
                len(ambiguos), ", ".join(sorted(ambiguos)),
            )

        return matches

    # ── Helpers ──────────────────────────────────────────────────────────

    def _require_index(self) -> None:
        if self._index is None or self._df is None:
            raise RuntimeError("Llama a build() antes de realizar búsquedas.")

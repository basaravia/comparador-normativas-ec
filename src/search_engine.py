"""Phase 2: Motor de búsqueda — índice FAISS semántico + escaneo léxico.

NormativaIndex:
  - build()           → construye índice FAISS sobre artículos de la normativa
  - semantic_search() → Top-K por similitud coseno (IndexFlatIP + L2-norm)
  - rerank()          → reordena candidatos con CrossEncoder local (optional)
  - lexical_scan()    → detecta referencias explícitas a artículos normativos
"""
from __future__ import annotations

import json
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
        vecs = self._backend.encode(texts, prefix="")
        dim = vecs.shape[1]

        self._index = faiss.IndexFlatIP(dim)
        self._index.add(vecs)
        self._df = normativa_df.reset_index(drop=True)
        logger.info("Índice listo: %d vectores, dim=%d", self._index.ntotal, dim)

    def _firma_backend(self) -> dict:
        """Con qué se construyó este índice. Es lo que permite rechazar una carga inválida."""
        from datetime import datetime, timezone

        backend = self._backend
        return {
            "backend": type(backend).__name__,
            "modelo": getattr(backend, "nombre_modelo", None) or getattr(backend, "_model", None)
                      or getattr(backend, "_model_name", None) or "desconocido",
            "dim": int(self._index.d) if self._index is not None else None,
            "prefijo_documento": getattr(backend, "prefijo_documento", ""),
            "fecha": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "version_esquema": 1,
        }

    def save(self, path: str | Path) -> None:
        """Persiste el índice FAISS, los metadatos del DataFrame y la firma del backend."""
        import faiss
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self._index, str(path / "index.faiss"))
        self._df.to_json(path / "normativa_meta.json", orient="records", force_ascii=False)
        (path / "index_meta.json").write_text(
            json.dumps(self._firma_backend(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info("Índice guardado en %s", path)

    def load(self, path: str | Path, *, estricto: bool = True) -> None:
        """Carga índice FAISS y metadatos desde disco.

        Rechaza el índice si se construyó con otro modelo de embeddings.

        Hoy, cargar un índice ajeno falla con un error críptico de dimensión — molesto,
        pero ruidoso. Con proveedores de nube el riesgo cambia de naturaleza: dos modelos
        distintos de **la misma dimensión** (1536 es un valor muy común) cargan sin
        protestar y devuelven vecinos sin sentido, en silencio. Un papel de trabajo
        construido sobre eso es indistinguible de uno correcto.

        `estricto=False` permite cargar de todas formas, avisando; existe para índices
        anteriores a esta versión, que no llevan firma.
        """
        import faiss
        path = Path(path)
        self._index = faiss.read_index(str(path / "index.faiss"))
        self._df = pd.read_json(path / "normativa_meta.json", orient="records")

        meta_path = path / "index_meta.json"
        if not meta_path.exists():
            logger.warning(
                "El índice de %s no lleva firma de backend (anterior a index_meta.json). "
                "No se puede verificar con qué modelo se construyó.", path,
            )
        else:
            guardada = json.loads(meta_path.read_text(encoding="utf-8"))
            actual = self._firma_backend()
            discrepancias = [
                f"{campo}: índice={guardada.get(campo)!r} actual={actual.get(campo)!r}"
                for campo in ("backend", "modelo", "dim")
                if guardada.get(campo) != actual.get(campo)
            ]
            if discrepancias:
                mensaje = (
                    f"El índice de {path} se construyó con otro backend de embeddings "
                    f"({'; '.join(discrepancias)}). Reconstrúyelo o carga con el mismo modelo."
                )
                if estricto:
                    raise ValueError(mensaje)
                logger.warning("%s (se carga igualmente: estricto=False)", mensaje)

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

        vec = self._backend.encode([query], prefix="")
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

        matches = []
        for _, row in df_arts.iterrows():
            if str(row.get("numero", "")).strip() in found_numbers:
                matches.append({
                    **row.to_dict(),
                    "match_type": "exacto",
                    "similarity": 1.0,
                    "rank": len(matches) + 1,
                })
        return matches

    # ── Helpers ──────────────────────────────────────────────────────────

    def _require_index(self) -> None:
        if self._index is None or self._df is None:
            raise RuntimeError("Llama a build() antes de realizar búsquedas.")

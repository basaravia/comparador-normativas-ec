"""Índice inverso sobre el manual: de un artículo a las secciones que podrían cubrirlo.

La Vía 1 pregunta *"¿qué normativa aplica a esta sección?"* y para eso basta con indexar la
normativa. La Vía 2 pregunta lo contrario — *"¿alguna sección cubre este artículo?"*— y esa
consulta no se puede responder con el mismo índice: recorrer todas las secciones por cada
artículo sería cuadrático y, sobre todo, no hay nada contra lo que buscar.

Por eso hace falta un segundo índice, sobre el manual.

**Por qué un módulo aparte y no una subclase de `NormativaIndex`.** Se consideró refactorizar
a un `SemanticIndex` genérico parametrizado por columnas, como sugería el plan. Pero
`NormativaIndex` arrastra cosas que aquí no aplican —`lexical_scan` busca citas *a*
artículos, la firma del backend, el filtro por `tipo_elemento`— y heredarlas obligaría a
neutralizarlas una por una. Un módulo pequeño que reutiliza el mismo backend de embeddings
es más corto que la jerarquía que lo evitaría, y deja `NormativaIndex` intacto: su API
pública no cambia y las 249 pruebas existentes no se tocan.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import pandas as pd

from .config import FAISS_TOP_K, MIN_SEMANTIC_SCORE
from .embeddings import EmbeddingBackend

logger = logging.getLogger(__name__)


class ManualIndex:
    """Índice FAISS sobre las secciones del manual.

        indice = ManualIndex(backend)
        indice.build(manual_df)
        secciones = indice.buscar_secciones(articulo["embed_text"], top_k=5)
    """

    def __init__(
        self,
        embedding_backend: EmbeddingBackend,
        vector_store_spec: object | None = None,
    ) -> None:
        self._backend = embedding_backend
        self._index = None
        self._df: Optional[pd.DataFrame] = None
        self._vector_store_spec = vector_store_spec

    # ── construcción ──────────────────────────────────────────────────────

    def build(self, manual_df: pd.DataFrame, text_col: str = "embed_text") -> None:
        logger.info("Construyendo índice del manual sobre %d secciones…", len(manual_df))
        textos = manual_df[text_col].fillna("").tolist()

        # El prefijo lo declara el backend, igual que en NormativaIndex: e5 lo exige y los
        # modelos servidos por endpoint no lo quieren (defecto 3 de §2.2).
        prefix = getattr(self._backend, "passage_prefix", "")
        vecs = self._backend.encode(textos, prefix=prefix)

        from .providers import Provider, ProviderSpec, build_vector_store

        spec = self._vector_store_spec or ProviderSpec(proveedor=Provider.FAISS_LOCAL)
        self._index = build_vector_store(spec, vecs.shape[1])
        self._index.add(vecs)
        self._df = manual_df.reset_index(drop=True)
        logger.info("Índice del manual listo: %d vectores, dim=%d",
                    self._index.ntotal, vecs.shape[1])

    @property
    def listo(self) -> bool:
        return self._index is not None and self._df is not None

    # ── búsqueda ──────────────────────────────────────────────────────────

    def buscar_secciones(
        self,
        texto_articulo: str,
        top_k: int = FAISS_TOP_K,
        min_score: float = MIN_SEMANTIC_SCORE,
    ) -> list[dict]:
        """Secciones del manual que podrían cubrir este artículo.

        Devuelve la fila completa del manual más `similarity`, para que quien llame tenga
        la jerarquía y el texto sin volver al DataFrame.
        """
        if not self.listo:
            raise RuntimeError("Llama a build() antes de buscar.")

        prefix = getattr(self._backend, "query_prefix", "")
        vec = self._backend.encode([texto_articulo], prefix=prefix)
        scores, indices = self._index.search(vec, top_k)

        resultados = []
        for score, idx in zip(scores[0].tolist(), indices[0].tolist()):
            if idx < 0 or score < min_score:
                continue
            fila = self._df.iloc[idx].to_dict()
            resultados.append({
                **fila,
                "similarity": round(float(score), 4),
                "rank_faiss": len(resultados) + 1,
            })
        return resultados

    # ── persistencia ──────────────────────────────────────────────────────

    def save(self, path: str | Path) -> None:
        import faiss

        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self._index, str(path / "manual.faiss"))
        self._df.to_json(path / "manual_meta.json", orient="records", force_ascii=False)

    def load(self, path: str | Path) -> None:
        import faiss

        path = Path(path)
        self._index = faiss.read_index(str(path / "manual.faiss"))
        self._df = pd.read_json(path / "manual_meta.json", orient="records")

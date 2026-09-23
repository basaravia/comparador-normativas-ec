"""Phase 2: Motor de búsqueda — índice FAISS semántico + escaneo léxico.

NormativaIndex:
  - build()           → construye índice FAISS sobre artículos de la normativa
  - semantic_search() → Top-K por similitud coseno (IndexFlatIP + L2-norm)
  - rerank()          → reordena candidatos con CrossEncoder local (optional)
  - lexical_scan()    → detecta referencias explícitas a artículos normativos

Chunking parent-child (ítem 8)
------------------------------
`build()` acepta indistintamente el DataFrame de artículos de siempre o el DataFrame de
sub-chunks que produce `chunking.chunk_normativa_df()`. La diferencia la detecta el propio
índice por la presencia de una columna padre (`articulo_element_id` / `parent_element_id`):
no hay bandera que pasar ni ruta que elegir desde fuera.

Cuando hay sub-chunks se **busca sobre fragmentos y se devuelven artículos**: los aciertos
se agrupan por artículo padre conservando el mejor score, de modo que la unidad de
resultado siga siendo el artículo completo (Bloque A) y `top_k` siga significando "k
artículos", no "k fragmentos". Sin esa agrupación, un artículo largo cuyos cinco numerales
puntúan alto ocuparía él solo el top-5 y desplazaría a los demás artículos aplicables.
"""
from __future__ import annotations

import json
import re
import logging
from pathlib import Path
from typing import Optional

import pandas as pd

# faiss se importa lazy (en build/load) para evitar conflicto de libs nativas con Docling
from .chunking import como_articulo_padre, detectar_columna_padre
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
        reranker_spec: object | None = None,
        vector_store_spec: object | None = None,
    ) -> None:
        self._backend = embedding_backend
        self._use_reranker = use_reranker
        self._index = None  # faiss.IndexFlatIP, lazy-loaded
        self._df: Optional[pd.DataFrame] = None
        self._vector_store_spec = vector_store_spec

        # Chunking parent-child: None mientras el índice contenga artículos enteros.
        # Lo fija `_registrar_df()` a partir de las columnas, en build() y en load().
        self._col_padre: Optional[str] = None
        self._max_chunks_por_padre = 1

        # El reranker se construye **cuando se usa**, no aquí.
        #
        # Antes este constructor importaba torch y sentence-transformers y descargaba
        # ~1.2 GB de pesos solo por crear un índice. Eso ataba dos cosas que no tienen
        # por qué ir juntas: no se podía indexar sin pagar la carga del reranker, ni
        # usar uno remoto. Y en la Fase 2 esa dependencia mete varios GB en el
        # contenedor para reordenar tres candidatos.
        self._reranker_spec = reranker_spec
        self._reranker_model = reranker_model
        self._puntuar = None

    # ── Construcción del índice ───────────────────────────────────────────

    def build(
        self,
        normativa_df: pd.DataFrame,
        text_col: str = "embed_text",
    ) -> None:
        """Construye el índice FAISS a partir del DataFrame de normativa."""
        logger.info("Construyendo índice FAISS sobre %d elementos…", len(normativa_df))
        texts = normativa_df[text_col].fillna("").tolist()

        # Defecto 3 de §2.2 del plan: el prefijo lo decide el backend (vía
        # `passage_prefix`/`query_prefix`), no `search_engine.py`. DMR no lo
        # quiere (backend.passage_prefix == ""); el backend local de
        # sentence-transformers sí (necesita "passage: " para e5). `getattr`
        # con default "" cubre además cualquier backend/doble que no lo declare.
        prefix = getattr(self._backend, "passage_prefix", "")
        vecs = self._backend.encode(texts, prefix=prefix)
        dim = vecs.shape[1]

        from .providers import Provider, ProviderSpec, build_vector_store

        spec = self._vector_store_spec or ProviderSpec(proveedor=Provider.FAISS_LOCAL)
        self._index = build_vector_store(spec, dim)
        self._index.add(vecs)
        self._registrar_df(normativa_df)
        logger.info("Índice listo: %d vectores, dim=%d", self._index.ntotal, dim)

    def _registrar_df(self, df: pd.DataFrame) -> None:
        """Guarda el DataFrame y deduce si lo indexado son sub-chunks o artículos.

        `_max_chunks_por_padre` es lo que hace exacta la agrupación de `semantic_search`:
        pedirle a FAISS `top_k * max_chunks` vecinos garantiza que, en el peor caso —los
        primeros aciertos son todos fragmentos del mismo artículo—, queden `top_k`
        artículos distintos. Un factor fijo (×4, ×10) no lo garantiza y devolvería menos
        resultados de los pedidos justo con los artículos más subdivididos.
        """
        self._df = df.reset_index(drop=True)
        self._col_padre = detectar_columna_padre(self._df)
        if self._col_padre is None:
            self._max_chunks_por_padre = 1
            return

        self._max_chunks_por_padre = max(1, int(self._df.groupby(self._col_padre).size().max()))
        logger.info(
            "Índice con chunking parent-child: %d sub-chunks sobre %d artículos "
            "(hasta %d por artículo); los resultados se agrupan por '%s'.",
            len(self._df), self._df[self._col_padre].nunique(),
            self._max_chunks_por_padre, self._col_padre,
        )

    def _firma_backend(self) -> dict:
        """Con qué se construyó este índice. Es lo que permite rechazar una carga inválida."""
        from datetime import datetime, timezone

        backend = self._backend

        # El nombre del modelo tiene que salir como STRING sí o sí.
        #
        # La versión anterior encadenaba `getattr(backend, "_model", None)` como fallback,
        # y en `SentenceTransformersEmbeddings` ese atributo **es el objeto
        # SentenceTransformer**, no su nombre: `save()` reventaba con
        # `TypeError: Object of type SentenceTransformer is not JSON serializable` por el
        # camino perfectamente alcanzable de elegir backend local y pulsar "Persistir
        # índice". Con DMR no se notaba porque ahí `_model` sí es un string.
        for atributo in ("nombre_modelo", "_model_name", "_model"):
            valor = getattr(backend, atributo, None)
            if isinstance(valor, str) and valor:
                modelo = valor
                break
        else:
            modelo = "desconocido"

        return {
            "backend": type(backend).__name__,
            "modelo": modelo,
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
        """Retorna top-k artículos de la normativa más similares a la consulta.

        Si el índice se construyó sobre sub-chunks (chunking semántico parent-child,
        ver `_registrar_df`), agrupa por artículo padre: antes esto pedía `top_k`
        vecinos sin más, así que un artículo muy subdividido podía copar el resultado
        con varios de sus propios fragmentos y desplazar artículos genuinamente
        distintos — contradiciendo la garantía documentada en `_registrar_df`
        ("top_k sigue significando k artículos, no k fragmentos"). Pedir
        `top_k * _max_chunks_por_padre` vecinos es lo que garantiza, en el peor caso
        (los primeros aciertos son todos del mismo artículo), que sobrevivan `top_k`
        artículos distintos.
        """
        self._require_index()

        # Ver comentario equivalente en build(): el prefijo de consulta también
        # depende del backend, no se fija a ciegas.
        prefix = getattr(self._backend, "query_prefix", "")
        vec = self._backend.encode([query], prefix=prefix)

        k_pedido = top_k * self._max_chunks_por_padre if self._col_padre else top_k
        scores, indices = self._index.search(vec, k_pedido)
        scores = scores[0].tolist()
        indices = indices[0].tolist()

        results = []
        padres_vistos: set = set()
        for score, idx in zip(scores, indices):
            if idx < 0 or score < min_score:
                continue
            row = self._df.iloc[idx].to_dict()
            if source_filter and row.get("doc_id") != source_filter:
                continue

            if self._col_padre:
                padre_id = row.get(self._col_padre)
                # FAISS ya devuelve los vecinos ordenados por score descendente, así
                # que el primer sub-chunk de un padre que se ve aquí es el de mejor
                # score de ese artículo — los siguientes del mismo padre se descartan.
                clave = padre_id if pd.notna(padre_id) else f"__sin_padre_{idx}"
                if clave in padres_vistos:
                    continue
                padres_vistos.add(clave)
                row = como_articulo_padre(row)

            results.append({**row, "similarity": round(float(score), 4), "rank_faiss": len(results) + 1})
            if len(results) >= top_k:
                break

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
        """Puntúa cada documento contra la query. Construye el reranker al primer uso."""
        if self._puntuar is None:
            from .providers import Provider, ProviderSpec, build_reranker

            spec = self._reranker_spec or ProviderSpec(
                proveedor=Provider.RERANK_LOCAL, modelo=self._reranker_model,
            )
            self._puntuar = build_reranker(spec)
        return self._puntuar(query, documents)

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

        Ante esa ambigüedad hay tres salidas, y dos son malas: devolver los
        artículos de las dos normativas como citas firmes genera una arista de
        cobertura falsa hacia la que el manual no citó; elegir una de forma
        arbitraria fabrica una cita que el texto no respalda. El criterio
        adoptado es la tercera:

          · Si el número identifica un único artículo entre todas las
            normativas cargadas → `match_type="exacto"`, `similarity=1.0`.
          · Si lo comparten artículos de ≥2 normativas (`doc_id`) distintas →
            se emiten igualmente, pero como `match_type="ambiguo"` con
            `similarity=0.5` y una `razon_match` que explica por qué.

        **Etiquetar, no descartar.** El motor de búsqueda no es la capa que
        debe decidir tirar evidencia. Descartar el match parece prudente pero
        borra el hecho de que el manual sí cita un artículo, y ese hecho le
        hace falta a quien viene después: al modelo N:N del ítem 5, que puede
        registrar la arista con origen y confianza propios; a la cobertura de
        la Vía 2 (ítem 6), donde un artículo realmente citado aparecería como
        huérfano y produciría una brecha inexistente contra la premisa de
        cobertura del Bloque A; y al flag de revisión manual del ítem 10, para
        el que una cita ambigua es exactamente el caso que debe marcarse.

        Es además lo que pide el Bloque A: la herramienta marca y explica, no
        resuelve automáticamente lo que no puede resolver con evidencia.

        La vía semántica sigue evaluando la sección con el contenido completo
        del artículo, no solo su número, así que la desambiguación real ocurre
        donde hay contexto para hacerla.
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

        # Antes de la reescritura para desambiguación, esto era `row.get("numero", "")`
        # por fila — tolerante a un DataFrame sin columna "numero". El acceso directo
        # `df_arts["numero"]` la exige, y un DataFrame construido a mano o mapeado
        # parcialmente (sin esa columna) revienta con KeyError en vez de, como antes,
        # devolver simplemente que no hay coincidencias.
        if "numero" not in df_arts.columns:
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

            es_ambiguo = docs_por_numero is not None and docs_por_numero.get(numero, 1) > 1
            if es_ambiguo:
                ambiguos.add(numero)

            matches.append({
                **row.to_dict(),
                "match_type": "ambiguo" if es_ambiguo else "exacto",
                # Un match ambiguo no puede valer lo mismo que una cita inequívoca:
                # con 1.0 competiría de tú a tú con la evidencia buena en el ranking.
                "similarity": 0.5 if es_ambiguo else 1.0,
                "rank": len(matches) + 1,
                "razon_match": (
                    f"El texto cita 'Art. {numero}' sin nombrar la normativa, y ese número "
                    f"existe en {docs_por_numero.get(numero)} normativas cargadas"
                    if es_ambiguo else ""
                ),
            })

        if ambiguos:
            logger.info(
                "lexical_scan: %d número(s) compartido(s) entre normativas (%s). "
                "Se emiten como match_type='ambiguo' para que quien decida tenga el dato, "
                "no como cita firme.",
                len(ambiguos), ", ".join(sorted(ambiguos)),
            )

        return matches

    # ── Helpers ──────────────────────────────────────────────────────────

    def _require_index(self) -> None:
        if self._index is None or self._df is None:
            raise RuntimeError("Llama a build() antes de realizar búsquedas.")

"""Inspector de chunks semánticos parent-child (``src/chunking.py``), vista Streamlit.

Réplica del propósito de ``ChunkInspector.vue`` en la SPA: dejar ver, artículo por
artículo, en qué sub-chunks lo partiría el chunking semántico —el contexto que
encabeza cada uno, el conteo de tokens y el texto exacto que se indexaría— antes de
confiar en que la recuperación semántica encuentre el numeral correcto.

Llama únicamente a la API pública de ``src/chunking.py`` (``chunk_articulo``,
``estimar_tokens``): no reimplementa ni modifica la lógica de chunking, solo la
muestra. Los sliders de `max_tokens`/`solape` son locales a este panel —no tocan la
configuración del pipeline en `service.py`— porque hoy `construir_indice` no
encadena `chunk_normativa_df` (ítem 8 preparado en `chunking.py`, aún no activado
en el servicio); este inspector deja explorar "qué produciría" sin depender de que
lo esté.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src import chunking

_MAX_TOKENS_MIN = 128
_MAX_TOKENS_MAX = 1024


def _etiqueta_fila(fila: pd.Series) -> str:
    numero = str(fila.get("numero") or "").strip()
    encabezado = str(fila.get("encabezado") or "").strip()
    prefijo = f"Art. {numero}" if fila.get("tipo_elemento") == "articulo" else numero
    return f"{prefijo} — {encabezado[:70]}" if encabezado else (prefijo or "(sin número)")


def render_chunk_inspector(normativa_df: pd.DataFrame) -> None:
    """Panel de inspección: elige un artículo/elemento normativo y muestra su chunking."""
    if normativa_df is None or normativa_df.empty:
        st.info("No hay elementos normativos tabulados todavía.")
        return

    docs = sorted(normativa_df["doc_id"].dropna().unique().tolist())
    col_doc, col_max, col_solape = st.columns([2, 1, 1])
    with col_doc:
        doc_elegido = st.selectbox("Documento normativo", docs, key="chunkinsp_doc")
    with col_max:
        max_tokens = st.number_input(
            "max_tokens", min_value=_MAX_TOKENS_MIN, max_value=_MAX_TOKENS_MAX,
            value=chunking.MAX_TOKENS_POR_DEFECTO, step=32, key="chunkinsp_max_tokens",
        )
    with col_solape:
        solape = st.number_input(
            "solape", min_value=0, max_value=int(max_tokens) - 1,
            value=min(chunking.SOLAPE_POR_DEFECTO, int(max_tokens) - 1), step=10,
            key="chunkinsp_solape",
        )

    df_doc = normativa_df[normativa_df["doc_id"] == doc_elegido]
    if df_doc.empty:
        st.warning("El documento elegido no tiene elementos.")
        return

    opciones = df_doc.index.tolist()
    idx_elegido = st.selectbox(
        "Artículo / elemento",
        opciones,
        format_func=lambda i: _etiqueta_fila(df_doc.loc[i]),
        key="chunkinsp_articulo",
    )
    fila = df_doc.loc[idx_elegido]

    sub_chunks = chunking.chunk_articulo(fila, max_tokens=int(max_tokens), solape=int(solape))
    padre_tokens = chunking.estimar_tokens(sub_chunks[0]["embed_text_padre"])
    es_subdividido = len(sub_chunks) > 1

    st.markdown("##### 📦 Artículo padre")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Tokens estimados", padre_tokens)
    c2.metric("Sub-chunks", len(sub_chunks))
    c3.metric("Presupuesto", int(max_tokens))
    c4.metric("Subdividido", "Sí" if es_subdividido else "No")
    st.caption(
        f"`{fila.get('doc_id', '')}` · sección: {fila.get('seccion') or '—'} · "
        f"elemento: `{sub_chunks[0]['parent_element_id']}`"
    )

    if not es_subdividido:
        st.success(
            "El artículo entra en el presupuesto configurado: se indexa como una sola "
            "pieza, con `embed_text` idéntico al original (`es_subchunk=False`)."
        )

    st.markdown("##### 🧩 Sub-chunks generados")
    for sc in sub_chunks:
        etiqueta = f"Chunk {sc['chunk_index'] + 1}/{sc['n_chunks']} — `{sc['chunk_id']}`"
        with st.expander(etiqueta, expanded=(len(sub_chunks) == 1)):
            tokens_chunk = chunking.estimar_tokens(sc["chunk_text"])
            st.caption(f"~{tokens_chunk} tokens estimados · cita: `{sc['chunk_id']}`")
            st.markdown("**Texto indexado (`embed_text`, contexto + cuerpo):**")
            st.code(sc["embed_text"], language="text")
            if sc["chunk_text"] != sc["embed_text"]:
                st.markdown("**Cuerpo del sub-chunk (`chunk_text`, sin el contexto repetido):**")
                st.code(sc["chunk_text"], language="text")

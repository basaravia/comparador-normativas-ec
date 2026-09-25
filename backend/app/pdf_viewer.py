"""Visor de PDF con render de página vía pypdfium2.

Streamlit no trae un widget nativo de PDF paginable: `st.pdf` incrusta el visor del
navegador entero, sin control de página/zoom desde Python y con soporte irregular
dentro del iframe de Databricks Apps. Renderizar la página elegida a PNG con
pypdfium2 (ya presente en el entorno como dependencia de Docling — ver
``dependencies/environment.yml``) da control total sobre página y zoom sin añadir
una dependencia nueva al proyecto.

Se renderiza una página a la vez, no el PDF completo: las normativas y manuales de
este proyecto llegan a varios cientos de páginas, y cargarlas todas de golpe en la
sesión de Streamlit no escala con lo que el auditor de verdad necesita ver (una
página cada vez, contrastada contra la fila tabulada).
"""
from __future__ import annotations

import io
from pathlib import Path

try:
    import pypdfium2 as pdfium
except ImportError:
    pdfium = None

import streamlit as st

DEFAULT_ZOOM = 1.5


def listar_pdfs(directorios: list[Path]) -> list[Path]:
    """PDFs existentes en cualquiera de los directorios dados, sin duplicar por nombre."""
    vistos: dict[str, Path] = {}
    for directorio in directorios:
        if not directorio.exists():
            continue
        for pdf in sorted(directorio.glob("*.pdf")):
            vistos.setdefault(pdf.name, pdf)
    return list(vistos.values())


@st.cache_data(show_spinner=False, max_entries=8)
def _num_paginas(ruta: str, mtime: float) -> int:
    doc = pdfium.PdfDocument(ruta)
    try:
        return len(doc)
    finally:
        doc.close()


@st.cache_data(show_spinner=False, max_entries=32)
def _render_pagina(ruta: str, mtime: float, pagina: int, zoom: float) -> bytes:
    """Página → PNG. `mtime` en la clave de caché invalida si el PDF se reemplaza."""
    doc = pdfium.PdfDocument(ruta)
    try:
        bitmap = doc[pagina - 1].render(scale=zoom)
        imagen = bitmap.to_pil()
    finally:
        doc.close()
    buffer = io.BytesIO()
    imagen.save(buffer, format="PNG")
    return buffer.getvalue()


def render_pdf_viewer(pdf_path: Path, key: str, pagina_defecto: int = 1) -> None:
    """Selector de página + zoom y la imagen de la página elegida de `pdf_path`."""
    if pdfium is None:
        st.warning(
            "El módulo `pypdfium2` no está instalado en este entorno. "
            "Instálalo con `pip install pypdfium2` para previsualizar páginas del PDF."
        )
        st.download_button(
            "⬇️ Descargar PDF", data=pdf_path.read_bytes(),
            file_name=pdf_path.name, mime="application/pdf", key=f"{key}_download_fallback",
        )
        return

    mtime = pdf_path.stat().st_mtime
    total = _num_paginas(str(pdf_path), mtime)

    col_pagina, col_zoom = st.columns([2, 1])
    with col_pagina:
        pagina = st.number_input(
            "Página", min_value=1, max_value=total,
            value=min(max(int(pagina_defecto), 1), total), key=f"{key}_pagina",
        )
    with col_zoom:
        zoom = st.slider("Zoom", 0.5, 3.0, DEFAULT_ZOOM, 0.25, key=f"{key}_zoom")

    st.caption(f"Página {int(pagina)} de {total} · `{pdf_path.name}`")
    png = _render_pagina(str(pdf_path), mtime, int(pagina), float(zoom))
    st.image(png, width="stretch")

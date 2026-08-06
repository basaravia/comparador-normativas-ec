"""Configuración de página y estilo visual — línea corporativa de la entidad.

No se pudo acceder al manual de marca oficial (brandfetch bloqueó la
petición y no había sesión de navegador disponible), así que la paleta es un
placeholder deliberadamente aislado en ``_PALETTE``: naranja corporativo +
azul marino, look bancario limpio. Si se cuenta con la guía de marca real,
basta con actualizar los valores hex de abajo.

El nombre de la entidad no se escribe en el código: sale de ``ORG_DISPLAY_NAME``
(vía ``.env``, que está en .gitignore). Sin esa variable la app arranca con un
título genérico, de modo que el repositorio no identifica al cliente.
"""
from __future__ import annotations

import os

import streamlit as st

_PALETTE = {
    "primary": "#EE6C0C",       # naranja corporativo (placeholder)
    "primary_dark": "#C6560A",
    "navy": "#0F2A43",          # azul marino institucional
    "bg": "#F5F6F8",
    "surface": "#FFFFFF",
    "text": "#1A2433",
    "muted": "#6B7280",
    "success": "#2E7D32",
    "success_bg": "#E2EFDA",
    "warning": "#B8860B",
    "warning_bg": "#FFF2CC",
    "danger": "#C0392B",
    "danger_bg": "#FCE4D6",
    "neutral_bg": "#F2F2F2",
}

# Colores por nivel de cumplimiento — coinciden con los fills usados en
# DocumentComparator.export_excel para que la UI y el Excel se lean igual.
NIVEL_COLORS = {
    "cumple":    {"fg": _PALETTE["success"], "bg": _PALETTE["success_bg"]},
    "parcial":   {"fg": _PALETTE["warning"], "bg": _PALETTE["warning_bg"]},
    "omision":   {"fg": _PALETTE["danger"],  "bg": _PALETTE["danger_bg"]},
    "no_aplica": {"fg": _PALETTE["muted"],   "bg": _PALETTE["neutral_bg"]},
}


_BASE_TITLE = "Comparador Normativo"


def page_title() -> str:
    """Título de la página. Se le añade el nombre de la entidad solo si está
    configurado en el entorno; en un clon limpio del repo queda el genérico."""
    org = os.getenv("ORG_DISPLAY_NAME", "").strip()
    return f"{_BASE_TITLE} — {org}" if org else _BASE_TITLE


def inject_theme() -> None:
    """Configura la página y aplica el CSS corporativo. Llamar una sola vez, primero."""
    st.set_page_config(
        page_title=page_title(),
        page_icon="🏦",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    p = _PALETTE
    st.markdown(
        f"""
        <style>
        :root {{
            --pb-primary: {p['primary']};
            --pb-primary-dark: {p['primary_dark']};
            --pb-navy: {p['navy']};
            --pb-bg: {p['bg']};
            --pb-surface: {p['surface']};
            --pb-text: {p['text']};
            --pb-muted: {p['muted']};
        }}

        html, body, [class*="css"] {{
            font-family: "Inter", "Segoe UI", "Helvetica Neue", Arial, sans-serif;
        }}

        .stApp {{
            background-color: var(--pb-bg);
        }}

        section[data-testid="stSidebar"] {{
            background-color: var(--pb-navy);
        }}
        section[data-testid="stSidebar"] * {{
            color: #EAF0F6 !important;
        }}
        section[data-testid="stSidebar"] .stButton>button {{
            background-color: var(--pb-primary);
            color: #FFFFFF !important;
            border: none;
        }}

        .pb-header {{
            background: linear-gradient(90deg, var(--pb-navy) 0%, #16406B 100%);
            border-left: 6px solid var(--pb-primary);
            border-radius: 10px;
            padding: 1.1rem 1.5rem;
            margin-bottom: 1.2rem;
        }}
        .pb-header h1 {{
            color: #FFFFFF;
            font-size: 1.5rem;
            margin: 0;
        }}
        .pb-header p {{
            color: #C9D6E3;
            margin: 0.2rem 0 0 0;
            font-size: 0.9rem;
        }}

        .stButton>button[kind="primary"] {{
            background-color: var(--pb-primary);
            border-color: var(--pb-primary);
        }}
        .stButton>button[kind="primary"]:hover {{
            background-color: var(--pb-primary-dark);
            border-color: var(--pb-primary-dark);
        }}

        div[data-testid="stMetric"] {{
            background-color: var(--pb-surface);
            border: 1px solid #E3E7EC;
            border-radius: 10px;
            padding: 0.8rem 1rem;
        }}

        .stTabs [data-baseweb="tab"] {{
            font-weight: 600;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_header(subtitle: str) -> None:
    st.markdown(
        f"""
        <div class="pb-header">
            <h1>🏦 Comparador Normativo vs. Manuales Internos</h1>
            <p>{subtitle}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

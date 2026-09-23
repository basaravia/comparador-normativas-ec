"""Configuración de página y estilo visual.

La paleta ya no se define aquí: sale de ``src.design_tokens``, que carga
``assets/brand/brand.json`` (fuera de git) o cae al placeholder neutro
versionado si no existe. Antes este módulo definía su propio ``_PALETTE`` —
un placeholder inventado a mano (naranja + azul marino) que además estaba
duplicado hex por hex en los ``PatternFill`` de ``src/comparator.py``. Cambiar
la identidad visual implicaba tocar los dos archivos, o dejarlos
desincronizados (PLAN_MEJORAS_ANEXO.md §2.2 defecto 5). Ahora cambiar un color
es cambiar un token en ``assets/brand/brand.json``, y la UI y el Excel se
actualizan juntos.

El nombre de la entidad tampoco se escribe en el código: sale de
``ORG_DISPLAY_NAME`` (vía ``.env``, que está en .gitignore). Sin esa variable
la app arranca con un título genérico, de modo que el repositorio no
identifica al cliente.
"""
from __future__ import annotations

import os

import streamlit as st

from src import design_tokens as tokens

# Colores por nivel de cumplimiento — misma fuente que los `PatternFill` de
# `DocumentComparator.export_excel` (src/comparator.py): cambiar un token en
# assets/brand/brand.json cambia la UI y el Excel a la vez.
#
# `bg` y `fg` apuntan al MISMO tinte desaturado de `estado.<nivel>.tinte`. Es
# deliberado, no un descuido: la regla cromo/dato (§8.2 del anexo) prohíbe que
# cualquier estado del semáforo use `tokens.PRIMARIO` o `tokens.ACENTO` — la
# marca es verde y un "cumple" verde saturado se confundiría con el cromo de
# la interfaz. El sistema de tokens no define un segundo color "vívido" por
# nivel para evitar precisamente la tentación de colar un verde ahí; el único
# tono por nivel es el tinte, y la distinción entre niveles la llevan además
# el ícono y la etiqueta (`tokens.icono` / `tokens.etiqueta`), nunca el color
# en solitario (daltonismo, ~8 % de los hombres).
# `fg` es el trazo saturado y `bg` el relleno desaturado. No son el mismo color y no
# pueden serlo: `fg` alimenta las barras de la gráfica de resultados, y con el tinte
# quedaban a ~1.2:1 sobre blanco — invisibles. `bg` pinta el fondo de las filas de la
# tabla, donde lo que necesita contraste es el texto oscuro que va encima.
NIVEL_COLORS = {
    nivel: {"fg": tokens.marca(nivel), "bg": tokens.tinte(nivel)}
    for nivel in tokens.NIVEL_ORDEN
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
    t = tokens
    st.markdown(
        f"""
        <style>
        :root {{
            --pb-primary: {t.PRIMARIO};
            --pb-primary-hover: {t.PRIMARIO_HOVER};
            --pb-accent: {t.ACENTO};
            --pb-secondary: {t.SECUNDARIO};
            --pb-bg: {t.FONDO};
            --pb-surface: {t.SUPERFICIE};
            --pb-divisor: {t.DIVISOR};
            --pb-text: {t.TEXTO};
            --pb-muted: {t.MUTED};
            --pb-radius: {t.RADIO_BASE};
        }}

        html, body, [class*="css"] {{
            font-family: {t.FUENTE_FAMILIA};
        }}

        .stApp {{
            background-color: var(--pb-bg);
        }}

        /* Cromo (§8.2): cabecera y navegación en el primario de marca, nunca
           en el acento (que no puede llevar texto — 2.20:1, falla AA). */
        section[data-testid="stSidebar"] {{
            background-color: var(--pb-primary);
        }}
        section[data-testid="stSidebar"] * {{
            color: var(--pb-surface) !important;
        }}
        /* Ítem 14 del anexo: la regla de arriba pintaba TAMBIÉN el texto
           DENTRO de los inputs, que tienen su propia superficie clara —
           texto claro sobre fondo claro, ilegible. Estos selectores son más
           específicos (atributo + descendiente extra), así que ganan sobre
           el `*` de arriba pese a que ambos usan `!important`. */
        section[data-testid="stSidebar"] input,
        section[data-testid="stSidebar"] textarea,
        section[data-testid="stSidebar"] select,
        section[data-testid="stSidebar"] [data-baseweb="input"] *,
        section[data-testid="stSidebar"] [data-baseweb="select"] *,
        section[data-testid="stSidebar"] [data-baseweb="textarea"] *,
        section[data-testid="stSidebar"] [data-baseweb="popover"] * {{
            color: var(--pb-text) !important;
        }}
        section[data-testid="stSidebar"] .stButton>button {{
            background-color: var(--pb-primary-hover);
            color: var(--pb-surface) !important;
            border: none;
        }}

        .pb-header {{
            background: linear-gradient(90deg, var(--pb-primary) 0%, var(--pb-primary-hover) 100%);
            /* Acento SOLO como borde decorativo, nunca con texto encima (§8.2/8.3:
               2.20:1, falla AA para cualquier texto). */
            border-left: 6px solid var(--pb-accent);
            border-radius: var(--pb-radius);
            padding: 1.1rem 1.5rem;
            margin-bottom: 1.2rem;
        }}
        .pb-header h1 {{
            color: var(--pb-surface);
            font-size: 1.5rem;
            margin: 0;
        }}
        .pb-header p {{
            color: var(--pb-surface);
            opacity: 0.85;
            margin: 0.2rem 0 0 0;
            font-size: 0.9rem;
        }}

        /* Titulares en el primario (6.18:1), nunca en el acento: el sitio de
           referencia usa el acento para h2 a 19px (2.19:1, falla AA — §8.3,
           "no_replicar"). No se replica ese fallo aquí. */
        h1, h2, h3 {{
            color: var(--pb-primary);
        }}

        .stButton>button[kind="primary"] {{
            background-color: var(--pb-primary);
            border-color: var(--pb-primary);
        }}
        .stButton>button[kind="primary"]:hover {{
            background-color: var(--pb-primary-hover);
            border-color: var(--pb-primary-hover);
        }}

        div[data-testid="stMetric"] {{
            background-color: var(--pb-surface);
            border: 1px solid var(--pb-divisor);
            /* Secundario como borde/icono (uso permitido, §8.3: 3.14:1, no
               alcanza para texto normal — nunca como color de texto aquí). */
            border-top: 3px solid var(--pb-secondary);
            border-radius: var(--pb-radius);
            padding: 0.8rem 1rem;
        }}

        .stTabs [data-baseweb="tab"] {{
            font-weight: 600;
            text-transform: {t.TRANSFORM_LABEL};
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

"""Fuente única de tokens de diseño — sustituye a la paleta duplicada a mano.

Antes de esta rama, ``app/theme.py`` (``NIVEL_COLORS``) y ``src/comparator.py``
(los ``PatternFill`` de ``export_excel``) repetían los mismos hex escritos a
mano; cambiar la identidad visual implicaba tocar dos archivos o dejar el
Excel y la UI leyéndose distinto (ver PLAN_MEJORAS_ANEXO.md §2.2 defecto 5).
Este módulo es el único lugar que sabe leer la guía de marca; los consumidores
(``app/theme.py``, ``src/comparator.py``, y en Fase 2 el frontend React vía el
contrato OpenAPI) importan de aquí y no vuelven a escribir un hex.

Carga ``assets/brand/brand.json`` (identidad real, fuera de git — S12) y, si
no existe o está incompleto, cae a
``assets/brand/_placeholder/brand.example.json`` (versionado, neutro), de
modo que un clon limpio del repositorio arranca sin ningún elemento del
cliente. Ambos archivos comparten la misma estructura: ``cromo``, ``neutros``,
``estado``, ``tipografia``, ``forma``, ``logos``, ``contraste_minimo``.

Regla cromo/dato (§8.2 del anexo), aplicada en el propio ``brand.json`` y
re-verificada en ``tests/test_design_tokens.py`` — no solo confiada al dato de
origen:

  - ``cromo`` (primario / primario_hover / acento / secundario) es EXCLUSIVO
    de cabecera, navegación, botón primario, estado activo. Nunca para datos.
  - ``estado`` (cumple / parcial / omision / no_aplica) son tintes
    desaturados que NUNCA coinciden con ``cromo.primario`` ni
    ``cromo.acento`` — si coincidieran, un "cumple" verde se confundiría con
    el cromo de marca (que también es verde). El texto sobre esos tintes va
    siempre en ``neutros.texto`` (el gris más oscuro), nunca en un color de
    marca.
  - ``cromo.acento`` no pasa ningún mínimo de contraste como texto (2.20:1 en
    la guía real) — es intencional: solo sirve para bordes y estados
    decorativos sin texto encima (§8.3).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
BRAND_PATH = REPO_ROOT / "assets" / "brand" / "brand.json"
PLACEHOLDER_PATH = REPO_ROOT / "assets" / "brand" / "_placeholder" / "brand.example.json"

# Claves de primer nivel que cualquier fuente de tokens (real o placeholder)
# debe traer. Si faltan, el archivo se trata como no utilizable.
_CLAVES_REQUERIDAS = frozenset({
    "cromo", "neutros", "estado", "tipografia", "forma", "logos", "contraste_minimo",
})


def load_tokens(
    brand_path: Path = BRAND_PATH,
    placeholder_path: Path = PLACEHOLDER_PATH,
) -> tuple[dict[str, Any], Path]:
    """Carga los tokens de marca. ``brand_path`` gana si existe, es JSON válido
    y trae las claves requeridas; si no, cae a ``placeholder_path``.

    Función pura (no toca estado global) para que
    ``tests/test_design_tokens.py`` pueda probar el fallback sin reimportar
    el módulo ni tocar el sistema de archivos real.

    Devuelve ``(tokens, ruta_usada)``. Lanza si ni siquiera el placeholder es
    utilizable — eso sí es un error de repositorio, no un caso esperado.
    """
    for candidato, es_placeholder in ((brand_path, False), (placeholder_path, True)):
        if not candidato.exists():
            continue
        try:
            datos = json.loads(candidato.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            if es_placeholder:
                raise RuntimeError(f"Placeholder de marca ilegible ({candidato}): {exc}") from exc
            logger.warning("brand.json ilegible (%s); usando el placeholder de marca.", exc)
            continue
        faltantes = _CLAVES_REQUERIDAS - datos.keys()
        if faltantes:
            if es_placeholder:
                raise RuntimeError(f"Placeholder de marca incompleto: faltan claves {sorted(faltantes)}")
            logger.warning("brand.json incompleto (faltan %s); usando el placeholder de marca.", sorted(faltantes))
            continue
        return datos, candidato
    raise FileNotFoundError(
        f"Ni la marca real ({brand_path}) ni el placeholder ({placeholder_path}) están disponibles."
    )


TOKENS, SOURCE_PATH = load_tokens()
USANDO_PLACEHOLDER = SOURCE_PATH == PLACEHOLDER_PATH

CROMO: dict[str, Any] = TOKENS["cromo"]
NEUTROS: dict[str, Any] = TOKENS["neutros"]
ESTADO: dict[str, Any] = TOKENS["estado"]
TIPOGRAFIA: dict[str, Any] = TOKENS["tipografia"]
FORMA: dict[str, Any] = TOKENS["forma"]
LOGOS: dict[str, str] = TOKENS["logos"]
CONTRASTE_MINIMO: dict[str, float] = TOKENS["contraste_minimo"]

NIVEL_ORDEN: tuple[str, ...] = ("cumple", "parcial", "omision", "no_aplica")


def _hex(nodo: dict[str, Any]) -> str:
    return nodo["hex"]


# ── Accesores planos — los hex que usan los consumidores (theme.py, comparator.py) ──
# Cromo: SOLO interfaz (cabecera, navegación, botón primario, estado activo). Nunca datos.
PRIMARIO = _hex(CROMO["primario"])
PRIMARIO_HOVER = _hex(CROMO["primario_hover"])
ACENTO = _hex(CROMO["acento"])  # nunca lleva texto — ver docstring del módulo
SECUNDARIO = _hex(CROMO["secundario"])

# Neutros
FONDO = NEUTROS["fondo"]
SUPERFICIE = NEUTROS["superficie"]
DIVISOR = NEUTROS["divisor"]
MUTED = _hex(NEUTROS["muted"])
TEXTO = _hex(NEUTROS["texto"])

# Forma y tipografía (§8.1)
RADIO_BASE = FORMA["radio_base"]
RADIO_ALTERNO = FORMA["radio_alterno"]
RADIO_CIRCULAR = FORMA["radio_circular"]
FUENTE_FAMILIA = TIPOGRAFIA["familia"]
PESO_LABEL = TIPOGRAFIA["peso_label"]
TRANSFORM_LABEL = TIPOGRAFIA["transform_label"]


def tinte(nivel: str) -> str:
    """Color de DATO para un nivel de cumplimiento — un tinte desaturado.

    Nunca devuelve ``PRIMARIO`` ni ``ACENTO``: esa garantía la impone el
    propio ``brand.json`` (ver su nota en ``estado._doc``) y la re-verifica
    ``tests/test_design_tokens.py`` comparando los hex reales, no solo
    confiando en el dato de origen.
    """
    return ESTADO[nivel]["tinte"]


def marca(nivel: str) -> str:
    """Color de TRAZO saturado del nivel — para marcas de gráfica.

    Distinto de ``tinte()`` y por un motivo medible, no estético: un tinte queda a
    ~1.2:1 sobre blanco, así que una barra pintada con él es invisible. WCAG exige
    ≥3:1 para componentes no textuales, y una barra de gráfica lo es.

    Reparto de responsabilidades:
      · ``tinte(nivel)``  → relleno de fondo con texto oscuro encima (tablas, Excel)
      · ``marca(nivel)``  → trazo o relleno de marca gráfica sobre fondo claro

    Tampoco puede ser ``PRIMARIO`` ni ``ACENTO``: sigue rigiendo la regla cromo/dato.
    """
    return ESTADO[nivel]["marca"]


def etiqueta(nivel: str) -> str:
    """Etiqueta textual del nivel — obligatoria junto al color (§8.2: el color
    nunca va solo, por daltonismo)."""
    return ESTADO[nivel]["etiqueta"]


def icono(nivel: str) -> str:
    """Nombre simbólico del icono del nivel (check/alert/x/minus)."""
    return ESTADO[nivel]["icono"]


def logo_path(nombre: str) -> Path:
    """Ruta absoluta al logotipo ``nombre`` (banner/mark/membrete/mono/favicon),
    resuelta sobre la fuente de tokens activa (marca real o placeholder)."""
    return REPO_ROOT / LOGOS[nombre]


def hex_sin_almohadilla(valor: str) -> str:
    """``openpyxl`` espera 'RRGGBB' sin '#' en ``PatternFill``/``Font``."""
    return valor.lstrip("#").upper()


# ── Contraste WCAG 2.1 ───────────────────────────────────────────────────────
# https://www.w3.org/TR/WCAG21/#dfn-relative-luminance
# https://www.w3.org/TR/WCAG21/#dfn-contrast-ratio

def _canal_lineal(valor_8bit: int) -> float:
    c = valor_8bit / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminancia_relativa(hex_color: str) -> float:
    """Luminancia relativa WCAG 2.1 de un color '#RRGGBB' (0.0 = negro, 1.0 = blanco)."""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    r_lin, g_lin, b_lin = _canal_lineal(r), _canal_lineal(g), _canal_lineal(b)
    return 0.2126 * r_lin + 0.7152 * g_lin + 0.0722 * b_lin


def ratio_contraste(hex_a: str, hex_b: str) -> float:
    """Ratio de contraste WCAG 2.1 entre dos colores '#RRGGBB' (1.0–21.0).

    Simétrico: el orden de los argumentos no importa (la fórmula del W3C lo
    es — el color más claro siempre va en el numerador).
    """
    l1, l2 = luminancia_relativa(hex_a), luminancia_relativa(hex_b)
    claro, oscuro = max(l1, l2), min(l1, l2)
    return (claro + 0.05) / (oscuro + 0.05)

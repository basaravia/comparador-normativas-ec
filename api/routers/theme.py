"""Router para entrega de tokens de diseño y variables CSS al frontend.
"""
from __future__ import annotations

from typing import Any, Dict
from fastapi import APIRouter

from src.design_tokens import (
    ACENTO,
    CONTRASTE_MINIMO,
    ESTADO,
    FONDO,
    NEUTROS,
    NIVEL_ORDEN,
    PRIMARIO,
    PRIMARIO_HOVER,
    SUPERFICIE,
    TEXTO,
    TIPOGRAFIA,
    marca,
    tinte,
)

router = APIRouter(prefix="/api/theme", tags=["Diseño y Tokens"])


@router.get("/tokens")
def get_theme_tokens() -> Dict[str, Any]:
    """Retorna los tokens de diseño y las variables CSS para estilizar la aplicación."""
    css_vars = {
        "--color-primary": PRIMARIO,
        "--color-primary-hover": PRIMARIO_HOVER,
        "--color-accent": ACENTO,
        "--color-surface": SUPERFICIE,
        "--color-background": FONDO,
        "--color-text-main": TEXTO,
        "--color-border": "#e2e8f0",
    }

    # Estados de cumplimiento (cumple, parcial, omision, no_aplica)
    for n in NIVEL_ORDEN:
        css_vars[f"--color-state-{n}-bg"] = tinte(n)
        css_vars[f"--color-state-{n}-fg"] = marca(n)

    return {
        "cromo": {
            "primario": PRIMARIO,
            "primario_hover": PRIMARIO_HOVER,
            "acento": ACENTO,
            "superficie": SUPERFICIE,
            "fondo": FONDO,
            "texto": TEXTO,
        },
        "estados": {
            n: {
                "tinte_bg": tinte(n),
                "marca_fg": marca(n),
                "etiqueta": ESTADO[n].get("etiqueta", n),
                "icono": ESTADO[n].get("icono", "check"),
            }
            for n in NIVEL_ORDEN
        },
        "css_variables": css_vars,
    }

"""Preparación del proceso. Importar **antes** que faiss, docling o torch.

Aquí vive lo que debe ocurrir una vez por proceso y antes de cualquier librería nativa,
independientemente de quién arranque: Streamlit, un notebook, la CLI de evaluación o —en
la Fase 2— un backend FastAPI.

Estaba en `streamlit_app.py` y en `tests/conftest.py`, duplicado. Mientras el único punto
de entrada fue la app de Streamlit no molestaba; en cuanto el frontend deje de ser Python
ese `os.environ.setdefault` desaparece del arranque y reaparece un segfault difícil de
rastrear. Es la restricción 6 de §3.3: nada específico de una plataforma fuera de su
implementación concreta.

Uso — basta con importarlo, antes que faiss/docling/torch:

    import src.bootstrap  # noqa: F401

El módulo se prepara **al importarse**, a propósito. La alternativa (exportar una función
y llamarla) mete una sentencia entre los imports, y entonces todo import posterior es un
E402: ruff reconoce `os.environ` antes de los imports como idioma legítimo para
precisamente este caso, pero no una llamada cualquiera. Un efecto de import es
cuestionable en general; en un módulo cuyo único propósito *es* el efecto, es lo correcto.

`preparar_proceso()` sigue exportada para quien prefiera hacerlo explícito, y es
idempotente.
"""
from __future__ import annotations

import os
import sys

_preparado = False


def preparar_proceso() -> None:
    """Idempotente. Llamar lo antes posible en el arranque."""
    global _preparado
    if _preparado:
        return

    if sys.platform == "darwin":
        # Apple Silicon: faiss y el runtime OpenMP que traen Docling/torch cargan cada
        # uno su copia de libomp, y la segunda aborta el proceso. Es un crash nativo,
        # no una excepción de Python: no hay forma de capturarlo después.
        #
        # `setdefault`, no asignación: si alguien lo fijó a propósito en su entorno,
        # manda su decisión.
        os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

    _preparado = True


# Efecto al importar: ver el docstring.
preparar_proceso()

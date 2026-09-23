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

import logging
import os
import stat
import sys
import tempfile

logger = logging.getLogger(__name__)

_preparado = False


def _materializar_credenciales_gcp() -> None:
    """Resuelve GOOGLE_APPLICATION_CREDENTIALS cuando la credencial llega como JSON.

    Vertex AI (ADC) espera que la variable apunte a un *archivo*. Eso es natural en
    desarrollo local, donde uno descarga la clave de la cuenta de servicio — pero
    Databricks Apps inyecta secretos como el *contenido* de una variable de entorno
    (`valueFrom` en `app.yaml`), no como un archivo montado: no hay forma de apuntar
    GOOGLE_APPLICATION_CREDENTIALS a un secreto de Databricks directamente.

    Puente: si GOOGLE_APPLICATION_CREDENTIALS_JSON trae el JSON de la cuenta de
    servicio, se escribe a un archivo temporal (0600, solo el usuario del proceso)
    y se apunta GOOGLE_APPLICATION_CREDENTIALS ahí. Si ya hay un archivo real en
    GOOGLE_APPLICATION_CREDENTIALS (el caso local), no se toca — gana lo explícito.
    """
    ruta_actual = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
    if ruta_actual and os.path.isfile(ruta_actual):
        return

    credenciales_json = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON")
    if not credenciales_json:
        return

    fd, ruta = tempfile.mkstemp(prefix="gcp-adc-", suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(credenciales_json)
        os.chmod(ruta, stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        os.unlink(ruta)
        raise

    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = ruta
    logger.info("Credenciales de GCP materializadas desde GOOGLE_APPLICATION_CREDENTIALS_JSON en %s", ruta)


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

    _materializar_credenciales_gcp()

    _preparado = True


# Efecto al importar: ver el docstring.
preparar_proceso()

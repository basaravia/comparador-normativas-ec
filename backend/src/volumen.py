"""Documentos desde un volumen de Unity Catalog.

Databricks Apps limita el tamaño de la app, así que los PDF grandes o reales no viajan en el
paquete: viven en un volumen de Unity Catalog asociado a la app como recurso. La app no ve el
volumen como una carpeta; lo lee con la API de archivos de `databricks-sdk` (identidad del
service principal de la app) y deja una copia local en `output/volumen/`, que es lo que el resto
del pipeline consume sin enterarse de dónde vino.

Estructura esperada en el volumen:

    /Volumes/<catálogo>/<esquema>/<volumen>/normativas/*.pdf
    /Volumes/<catálogo>/<esquema>/<volumen>/manuales/*.pdf

Configuración: `DOCUMENTOS_VOLUMEN` con la ruta del volumen (`/Volumes/c/s/v`) o su nombre
(`c.s.v`). En una app se define en app.yaml con `valueFrom` apuntando al recurso UC volume. Sin
ella, este módulo no hace nada y la app usa solo los PDF del paquete.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from .settings import get

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CACHE_DIR = REPO_ROOT / "output" / "volumen"
SUBCARPETAS = {"normativa": "normativas", "manual": "manuales"}

# Cada cuánto se vuelve a listar el volumen como mucho (segundos): listar es una llamada remota
# y la UI pide la lista de documentos a menudo.
REFRESCO_S = 60

_ultimo_sync = 0.0
_ultimo_error: str | None = None


def ruta_volumen() -> str | None:
    """Ruta `/Volumes/c/s/v` configurada, o None si no hay volumen."""
    valor = str(get("DOCUMENTOS_VOLUMEN", default="") or "").strip().rstrip("/")
    if not valor or valor.upper().startswith("REEMPLAZAR"):
        return None
    if valor.startswith("/Volumes/"):
        return valor
    partes = valor.split(".")
    if len(partes) == 3 and all(partes):
        return "/Volumes/" + "/".join(partes)
    raise ValueError(
        f"DOCUMENTOS_VOLUMEN={valor!r} no es una ruta /Volumes/<catálogo>/<esquema>/<volumen> "
        "ni un nombre <catálogo>.<esquema>.<volumen>"
    )


def directorio_local(tipo: str) -> Path:
    """Carpeta local donde quedan las copias de un tipo (`normativa` | `manual`)."""
    return CACHE_DIR / SUBCARPETAS[tipo]


def ultimo_error() -> str | None:
    """Motivo del último fallo de sincronización, para mostrarlo sin tumbar la app."""
    return _ultimo_error


def _cliente() -> Any:
    from databricks.sdk import WorkspaceClient

    return WorkspaceClient()


def sincronizar(cliente: Any = None, *, forzar: bool = False) -> int:
    """Descarga a `output/volumen/` los PDF nuevos o cambiados. Devuelve cuántos bajó.

    Nunca lanza: un volumen caído o sin permisos no debe impedir trabajar con los PDF del
    paquete. El motivo queda en `ultimo_error()` y en el log.
    """
    global _ultimo_sync, _ultimo_error
    try:
        base = ruta_volumen()
    except ValueError as e:
        _ultimo_error = str(e)
        logger.warning("%s", e)
        return 0
    if base is None:
        _ultimo_error = None
        return 0
    if not forzar and time.monotonic() - _ultimo_sync < REFRESCO_S:
        return 0

    descargados = 0
    try:
        w = cliente or _cliente()
        for tipo, sub in SUBCARPETAS.items():
            destino_dir = directorio_local(tipo)
            destino_dir.mkdir(parents=True, exist_ok=True)
            for entrada in w.files.list_directory_contents(f"{base}/{sub}"):
                if getattr(entrada, "is_directory", False):
                    continue
                nombre = Path(entrada.name or entrada.path or "").name
                if not nombre.lower().endswith(".pdf"):
                    continue
                destino = destino_dir / nombre
                tam = getattr(entrada, "file_size", None)
                if destino.exists() and tam is not None and destino.stat().st_size == tam:
                    continue
                datos = w.files.download(entrada.path).contents.read()
                temporal = destino.with_suffix(".pdf.part")
                temporal.write_bytes(datos)
                temporal.replace(destino)   # sin copias a medias si la descarga se corta
                descargados += 1
        _ultimo_sync = time.monotonic()
        _ultimo_error = None
        if descargados:
            logger.info("Volumen %s: %d PDF descargados", base, descargados)
    except Exception as e:  # noqa: BLE001 - cualquier fallo del volumen o del SDK
        _ultimo_error = f"No se pudo leer el volumen {base}: {type(e).__name__}: {e}"
        logger.warning("%s", _ultimo_error)
    return descargados

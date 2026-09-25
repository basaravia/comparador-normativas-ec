"""Configuración por entorno y redacción de secretos.

Hoy no hay una sola lectura de variables de entorno en el proyecto: `python-dotenv` está
declarado en `dependencies/requirements.txt` pero nunca se usa, y `config.py` lleva los
endpoints escritos a mano. Mientras todo corra contra un backend local eso no duele; en
cuanto haya credenciales de por medio, sí.

**Precedencia**, de mayor a menor:
`UI > variable de entorno > .env > secret scope de Databricks > defaults de config.py`.

**Secret scope.** Cualquier variable `X` puede leerse de un secreto de Databricks si el entorno
(o `.env`) dice DÓNDE está, nunca su valor: `X_SECRET_KEY=<key>` y el scope en `X_SECRET_SCOPE`
o, para todas, en `DATABRICKS_SECRET_SCOPE`. Se lee con `dbutils.secrets.get` donde exista
(notebooks, jobs) y con `databricks-sdk` donde no (Databricks Apps, con la identidad de la app).
La UI gana porque un cambio en el sidebar debe verse en la corrida siguiente sin reiniciar;
`config.py` pierde porque deja de ser fuente de credenciales y conserva solo defaults no
sensibles.

La otra mitad del módulo es `redact()`. El repositorio es público y los logs de corrida se
guardan en disco: ninguna clave puede llegar a `output/logs/`, ni al JSON, ni a la hoja de
trazabilidad del papel de trabajo.
"""
from __future__ import annotations

import base64
import logging
import os
import re
from pathlib import Path
from typing import Any

# backend/src/settings.py → la raíz del repo (donde vive .env) está tres niveles arriba.
_RAIZ = Path(__file__).resolve().parent.parent.parent
_ENV = _RAIZ / ".env"

_cargado = False

logger = logging.getLogger(__name__)

# Valores ya leídos de un secret scope, por variable. Un fallo se guarda como None para no
# repetir la llamada en cada `get()`.
_SECRETOS: dict[str, str | None] = {}


def cargar_env(ruta: Path | None = None, *, forzar: bool = False) -> bool:
    """Carga `.env` una vez por proceso. Devuelve True si se leyó un archivo.

    No pisa variables ya presentes en el entorno: quien exporta algo en su shell lo hace
    a propósito y debe ganarle al archivo (es la precedencia declarada arriba).
    """
    global _cargado
    if _cargado and not forzar:
        return False

    destino = ruta or _ENV
    if not destino.exists():
        _cargado = True
        return False

    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - dependencia declarada, pero no obligatoria
        _cargado = True
        return False

    load_dotenv(destino, override=False)
    _cargado = True
    return True


def get(
    clave: str,
    *,
    ui: Any = None,
    default: Any = None,
    cast: type | None = None,
) -> Any:
    """Resuelve un valor siguiendo la precedencia declarada.

    `ui` es el valor que viene del sidebar (o de quien orqueste); si no es None, gana.
    El resto sale del entorno —que a estas alturas ya incluye lo cargado de `.env`— y,
    en último término, del default que se pase.
    """
    if ui is not None and ui != "":
        valor = ui
    else:
        cargar_env()
        valor = os.environ.get(clave)
        if valor is None or valor == "":
            valor = _desde_secret_scope(clave)
        if valor is None or valor == "":
            valor = default

    if valor is None or cast is None:
        return valor
    if cast is bool:
        return str(valor).strip().lower() in ("1", "true", "yes", "si", "sí", "on")
    try:
        return cast(valor)
    except (TypeError, ValueError):
        return default


def faltantes(claves: tuple[str, ...]) -> list[str]:
    """Cuáles de esas variables no están definidas (ni en el entorno ni en un secret scope)."""
    cargar_env()
    return [c for c in claves if not get(c)]


# ── Secret scope de Databricks ────────────────────────────────────────────────

def referencia_secreto(clave: str) -> tuple[str, str] | None:
    """`(scope, key)` de donde leer `clave`, según `X_SECRET_KEY` / `X_SECRET_SCOPE`.

    Se leen de `os.environ` directamente (no con `get`) para no recursar.
    """
    key = (os.environ.get(f"{clave}_SECRET_KEY") or "").strip()
    if not key:
        return None
    scope = (os.environ.get(f"{clave}_SECRET_SCOPE")
             or os.environ.get("DATABRICKS_SECRET_SCOPE") or "").strip()
    if not scope:
        logger.warning("%s_SECRET_KEY está definida pero falta el scope: define %s_SECRET_SCOPE "
                       "o DATABRICKS_SECRET_SCOPE", clave, clave)
        return None
    return scope, key


def _leer_secreto(scope: str, key: str) -> str:
    """Lee un secreto: `dbutils` si existe (notebooks/jobs), si no `databricks-sdk` (Apps)."""
    try:
        from pyspark.dbutils import DBUtils
        from pyspark.sql import SparkSession
        return DBUtils(SparkSession.builder.getOrCreate()).secrets.get(scope=scope, key=key)
    except ImportError:
        pass
    from databricks.sdk import WorkspaceClient

    respuesta = WorkspaceClient().secrets.get_secret(scope=scope, key=key)
    return base64.b64decode(respuesta.value or "").decode("utf-8")


def _desde_secret_scope(clave: str) -> str | None:
    if clave in _SECRETOS:
        return _SECRETOS[clave]
    ref = referencia_secreto(clave)
    if ref is None:
        return None
    scope, key = ref
    try:
        valor = _leer_secreto(scope, key) or None
    except Exception as e:  # noqa: BLE001 - cualquier fallo del backend de secretos
        # Se nombra dónde se buscó y el tipo de error; nunca el valor.
        logger.warning("No se pudo leer %s del secret scope %r (key %r): %s",
                       clave, scope, key, type(e).__name__)
        valor = None
    _SECRETOS[clave] = valor
    return valor


# ── Redacción ─────────────────────────────────────────────────────────────────

_MASCARA = "***"

# Claves de API con formato reconocible.
_PATRONES_VALOR = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),
    # JWT: tres bloques base64 separados por puntos.
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
)

# Asignaciones tipo `api_key=...`, `SECRET: ...`, `"password": "..."`.
#
# `[ \t]*` y no `\s*` tras el separador: `\s*` cruza saltos de línea, y entonces una
# variable declarada sin valor (`API_KEY=` en una plantilla) se traga el contenido de la
# línea siguiente y lo enmascara como si fuera el secreto.
_PATRON_ASIGNACION = re.compile(
    r"(?i)\b([a-z0-9_-]*(?:api[_-]?key|apikey|secret|token|password|passwd|credential)[a-z0-9_-]*)"
    r"([ \t]*[:=][ \t]*)"
    r"(\"[^\"]+\"|'[^']+'|[^\s,;&)]+)"
)

# Credenciales embebidas en URL y tokens en query string.
_PATRON_URL_USERINFO = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)([^/\s:@]+):([^/\s@]+)@")
_PATRON_URL_QUERY = re.compile(
    r"(?i)([?&](?:api[_-]?key|access_token|token|sig|signature|code)=)([^&\s]+)"
)


def redact(valor: Any) -> Any:
    """Enmascara credenciales en cualquier texto antes de que se registre o se exporte.

    Se aplica sobre strings, y recursivamente sobre dicts, listas y tuplas, porque los
    sitios donde esto importa —el buffer de logs, el panel de ejecución, la hoja de
    trazabilidad— manejan estructuras, no solo cadenas sueltas.

    No pretende ser un detector universal de secretos: cubre las formas que este proyecto
    puede producir. La red que sí es exhaustiva son los hooks locales de git.
    """
    if isinstance(valor, dict):
        return {k: redact(v) for k, v in valor.items()}
    if isinstance(valor, (list, tuple)):
        tipo = type(valor)
        return tipo(redact(v) for v in valor)
    if not isinstance(valor, str):
        return valor

    texto = valor
    # Los valores leídos de un secret scope se ocultan literalmente, tengan el formato que tengan.
    for secreto in _SECRETOS.values():
        if secreto and len(secreto) >= 4:
            texto = texto.replace(secreto, _MASCARA)
    for patron in _PATRONES_VALOR:
        texto = patron.sub(_MASCARA, texto)
    texto = _PATRON_ASIGNACION.sub(lambda m: f"{m.group(1)}{m.group(2)}{_MASCARA}", texto)
    texto = _PATRON_URL_USERINFO.sub(lambda m: f"{m.group(1)}{m.group(2)}:{_MASCARA}@", texto)
    texto = _PATRON_URL_QUERY.sub(lambda m: f"{m.group(1)}{_MASCARA}", texto)
    return texto

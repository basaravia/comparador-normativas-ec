"""Sesiones firmadas y dependencias de autorización para la API FastAPI.

La API queda expuesta a internet junto con la SPA, así que toda superficie que
revele documentos, índices o resultados de comparación exige una sesión válida.

El transporte es una **cookie firmada HttpOnly** (`auth_session`) y no un header
`Authorization`, porque dos consumidores del navegador no pueden poner headers:
el `EventSource` del progreso SSE (`/api/compare/stream/{run_id}`) y el visor de
PDF. Una cookie same-origin viaja en ambos sin código extra.

El token no se cifra, se **firma** (HMAC-SHA256 sobre el payload en base64url):
no contiene nada reservado —usuario y expiración— y lo único que importa es que
el cliente no pueda fabricarlo ni extenderle la vigencia.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException, Request, status

from app.auth_core import (
    credentials_are_configured,
    get_configured_credentials,
    is_auth_enabled,
    verify_credentials,
)
from src import settings as _settings

SESSION_COOKIE_NAME = "auth_session"

# 8 horas: cubre una jornada de auditoría sin dejar sesiones vivas indefinidamente.
#
# `_settings.cargar_env()` explícito antes de leer, no solo `os.getenv()`: esta
# constante se calcula una sola vez, al importar el módulo — si algo la lee antes de
# que cualquier otro código del proceso haya cargado `.env`, un AUTH_SESSION_TTL
# puesto solo ahí (la convención documentada del proyecto) queda congelado con el
# default para siempre, sin ninguna llamada posterior que pueda corregirlo.
_settings.cargar_env()
SESSION_TTL_SECONDS = _settings.get("AUTH_SESSION_TTL", default=28800, cast=int)

# Clave de proceso si no hay AUTH_SECRET_KEY: las sesiones no sobreviven a un
# reinicio, que es el comportamiento seguro por defecto para un único worker.
_EPHEMERAL_KEY = secrets.token_hex(32)


def _signing_key() -> bytes:
    """Clave de firma. `AUTH_SECRET_KEY` la hace estable entre reinicios y workers."""
    from src import settings

    settings.cargar_env()
    configurada = os.getenv("AUTH_SECRET_KEY", "").strip()
    return hashlib.sha256((configurada or _EPHEMERAL_KEY).encode("utf-8")).digest()


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(data: str) -> bytes:
    relleno = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + relleno)


def crear_token_sesion(username: str, ttl: int = SESSION_TTL_SECONDS) -> str:
    """Emite un token `<payload>.<firma>` con usuario, emisión y expiración."""
    ahora = int(time.time())
    payload = {"sub": username, "iat": ahora, "exp": ahora + ttl}
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    firma = hmac.new(_signing_key(), payload_b64.encode("ascii"), hashlib.sha256).digest()
    return f"{payload_b64}.{_b64url_encode(firma)}"


def verificar_token_sesion(token: str) -> Optional[Dict[str, Any]]:
    """Valida firma y expiración. Retorna el payload o None si el token no sirve."""
    if not token or token.count(".") != 1:
        return None

    payload_b64, firma_b64 = token.split(".")
    esperada = hmac.new(_signing_key(), payload_b64.encode("ascii"), hashlib.sha256).digest()
    try:
        recibida = _b64url_decode(firma_b64)
    except (ValueError, TypeError):
        return None

    # compare_digest y no `==`: la comparación de firmas no debe filtrar por tiempo.
    if not hmac.compare_digest(esperada, recibida):
        return None

    try:
        payload = json.loads(_b64url_decode(payload_b64))
    except (ValueError, TypeError):
        return None

    if not isinstance(payload, dict) or "sub" not in payload:
        return None
    try:
        if int(payload.get("exp", 0)) <= int(time.time()):
            return None
    except (TypeError, ValueError):
        return None

    # Un token emitido para el usuario anterior deja de valer al rotar credenciales.
    usuario_actual, _ = get_configured_credentials()
    if payload["sub"] != usuario_actual:
        return None

    return payload


def obtener_sesion(request: Request) -> Optional[Dict[str, Any]]:
    """Sesión activa a partir de cookie o cabecera Authorization (Basic o Bearer)."""
    if not is_auth_enabled():
        usuario, _ = get_configured_credentials()
        return {"sub": usuario, "auth_disabled": True}

    # 1. Cookie de sesión del navegador (SPA)
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        valida = verificar_token_sesion(token)
        if valida:
            return valida

    # 2. Cabecera Authorization (Swagger UI, Postman, cURL)
    auth_header = request.headers.get("Authorization", "").strip()
    if auth_header:
        # 2a. HTTP Basic Auth
        if auth_header.lower().startswith("basic "):
            try:
                b64_creds = auth_header[6:].strip()
                decoded = base64.b64decode(b64_creds).decode("utf-8")
                if ":" in decoded:
                    u, p = decoded.split(":", 1)
                    if verify_credentials(u, p):
                        return {"sub": u, "auth_type": "basic"}
            except Exception:
                pass
        # 2b. Bearer Token
        elif auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()
            valida = verificar_token_sesion(token)
            if valida:
                return valida

    return None


def require_session(request: Request) -> Dict[str, Any]:
    """Dependencia que exige sesión o credenciales válidas; responde 401 solicitando Basic Auth."""
    sesion = obtener_sesion(request)
    if sesion is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autenticación requerida para acceder a la API y documentación.",
            headers={"WWW-Authenticate": 'Basic realm="Acceso al Comparador de Normativas"'},
        )
    return sesion


# Alias declarativo para `include_router(..., dependencies=[...])`.
SesionRequerida = Depends(require_session)


def cookie_debe_ser_segura(request: Request) -> bool:
    """Marca `Secure` salvo en HTTP plano de desarrollo.

    `AUTH_COOKIE_SECURE` fuerza el valor cuando hay un proxy TLS delante que
    termina la conexión y habla HTTP con la app (el caso de despliegue típico).

    Vía `_settings.get()` (carga `.env` internamente), no `os.getenv()` directo —
    mismo motivo que `SESSION_TTL_SECONDS` arriba. El valor sin forzar (`None`) usa
    su propia lista de verdadero/falso en vez de la de `settings.get(cast=bool)`
    porque aquí hace falta distinguir tres estados (forzado True / forzado False /
    sin forzar), y `cast=bool` con un default no distingue "no configurado" de
    "configurado en falso".
    """
    forzado = _settings.get("AUTH_COOKIE_SECURE", default="").strip().lower()
    if forzado in ("1", "true", "yes", "on"):
        return True
    if forzado in ("0", "false", "no", "off"):
        return False
    reenviado = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
    return (reenviado or request.url.scheme) == "https"


__all__ = [
    "SESSION_COOKIE_NAME",
    "SESSION_TTL_SECONDS",
    "SesionRequerida",
    "cookie_debe_ser_segura",
    "credentials_are_configured",
    "crear_token_sesion",
    "is_auth_enabled",
    "obtener_sesion",
    "require_session",
    "verificar_token_sesion",
    "verify_credentials",
]

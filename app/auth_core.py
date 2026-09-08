"""Credenciales y verificación en tiempo constante, sin dependencias de UI.

`app/auth.py` (Streamlit) y `api/security.py` (FastAPI) comparten exactamente las
mismas credenciales: una sola definición de qué usuario y contraseña son válidos
evita que la app y la API se desincronicen y que un despliegue quede protegido en
una superficie y abierto en la otra.

Este módulo no importa Streamlit a propósito: la API se ejecuta como servicio HTTP
y no debe arrastrar el runtime de la UI para poder validar un login.
"""
from __future__ import annotations

import hmac
import os

DEFAULT_USERNAME = "asaravia002"


def is_auth_enabled() -> bool:
    """Indica si la autenticación está activa. Por defecto True.

    Carga `.env` antes de mirar el entorno, igual que `get_configured_credentials()`
    de abajo. Sin esto, la primera llamada del proceso —que en Streamlit es
    `check_auth()` al arrancar, antes de que nada más haya cargado `.env`— podía leer
    `AUTH_ENABLED` como si no estuviera definida aunque sí lo estuviera en `.env`: no
    abre el acceso (el default "true" es el lado seguro), pero sí podía mostrar un
    login que un despliegue de prueba con `AUTH_ENABLED=false` en `.env` no esperaba.
    """
    from src import settings

    settings.cargar_env()
    val = os.getenv("AUTH_ENABLED", "true").strip().lower()
    return val not in ("false", "0", "no", "off", "disable", "disabled")


def get_configured_credentials() -> tuple[str, str]:
    """Retorna el usuario y contraseña configurados vía variables de entorno o defaults."""
    from src import settings

    settings.cargar_env()
    user = os.getenv("AUTH_USERNAME", DEFAULT_USERNAME)
    pwd = os.getenv("AUTH_PASSWORD", "")
    return user, pwd


def credentials_are_configured() -> bool:
    """True solo si hay una contraseña no vacía configurada.

    Sin este chequeo, `AUTH_PASSWORD` ausente haría que `hmac.compare_digest("", "")`
    aceptara un login con contraseña vacía: un despliegue mal configurado quedaría
    abierto a internet en lugar de fallar de forma visible.
    """
    user, pwd = get_configured_credentials()
    return bool(user) and bool(pwd)


def verify_credentials(username: str, password: str) -> bool:
    """Verificación segura en tiempo constante de credenciales."""
    expected_user, expected_pwd = get_configured_credentials()
    if not expected_user or not expected_pwd:
        return False
    user_match = hmac.compare_digest(username.encode("utf-8"), expected_user.encode("utf-8"))
    pwd_match = hmac.compare_digest(password.encode("utf-8"), expected_pwd.encode("utf-8"))
    return user_match and pwd_match

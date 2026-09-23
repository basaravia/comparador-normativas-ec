"""Sin usuario por defecto: el repositorio es público y el login debe fallar cerrado."""
from __future__ import annotations

import pytest

from app.auth_core import (
    DEFAULT_USERNAME,
    credentials_are_configured,
    verify_credentials,
)


@pytest.fixture(autouse=True)
def _sin_credenciales(monkeypatch):
    for k in ("AUTH_USERNAME", "AUTH_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr("src.settings.cargar_env", lambda *a, **k: False)


def test_no_hay_usuario_por_defecto():
    assert DEFAULT_USERNAME == ""


def test_sin_configurar_no_hay_credenciales_validas():
    assert credentials_are_configured() is False


def test_sin_configurar_ni_el_login_vacio_entra():
    assert verify_credentials("", "") is False


def test_con_usuario_y_clave_del_entorno_el_login_funciona(monkeypatch):
    monkeypatch.setenv("AUTH_USERNAME", "alguien")
    monkeypatch.setenv("AUTH_PASSWORD", "una-clave-de-prueba")
    assert verify_credentials("alguien", "una-clave-de-prueba") is True
    assert verify_credentials("alguien", "otra") is False

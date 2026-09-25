"""Credenciales desde un secret scope de Databricks, referenciado en el `.env`.

El `.env` dice DÓNDE está el secreto (`DATABRICKS_SECRET_KEY_<NOMBRE>`,
`DATABRICKS_SECRET_SCOPE_<NOMBRE>` o `DATABRICKS_SECRET_SCOPE`), nunca su valor. Estas pruebas fijan la precedencia, que un fallo nombre scope y key sin filtrar
nada, que el valor leído se oculte en los logs y que el backend Foundry lo use de punta a punta.
"""
from __future__ import annotations

import pytest

from src import settings

VALOR = "valor-leido-del-scope-1234"


@pytest.fixture(autouse=True)
def _limpio(monkeypatch):
    for k in ("DATABRICKS_SECRET_SCOPE", "FOUNDRY_AI_TOKEN", "FOUNDRY_AI_ENDPOINT",
              "FOUNDRY_AI_API_VERSION", "FOUNDRY_AI_DEPLOYMENT", "FOUNDRY_AI_EMBED_DEPLOYMENT",
              "DATABRICKS_SECRET_KEY_FOUNDRY_TOKEN", "DATABRICKS_SECRET_SCOPE_FOUNDRY_TOKEN",
              "DATABRICKS_SECRET_KEY_FOUNDRY_AI_TOKEN", "DATABRICKS_SECRET_SCOPE_FOUNDRY_AI_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr("src.settings.cargar_env", lambda *a, **k: False)
    settings._SECRETOS.clear()
    yield
    settings._SECRETOS.clear()


@pytest.fixture
def scope_falso(monkeypatch):
    """Backend de secretos en memoria; registra cada lectura."""
    lecturas: list[tuple[str, str]] = []
    guardados = {("mi-scope", "foundry-token"): VALOR, ("otro-scope", "foundry-token"): "de-otro"}

    def _leer(scope, key):
        lecturas.append((scope, key))
        if (scope, key) not in guardados:
            raise KeyError("no existe")
        return guardados[(scope, key)]

    monkeypatch.setattr("src.settings._leer_secreto", _leer)
    return lecturas


class TestReferencia:
    def test_sin_referencia_no_se_consulta_el_scope(self, scope_falso):
        assert settings.get("FOUNDRY_AI_TOKEN", default="") == ""
        assert scope_falso == []

    def test_key_y_scope_global(self, monkeypatch, scope_falso):
        monkeypatch.setenv("DATABRICKS_SECRET_SCOPE", "mi-scope")
        monkeypatch.setenv("DATABRICKS_SECRET_KEY_FOUNDRY_TOKEN", "foundry-token")
        assert settings.get("FOUNDRY_AI_TOKEN") == VALOR
        assert scope_falso == [("mi-scope", "foundry-token")]

    def test_scope_propio_gana_al_global(self, monkeypatch, scope_falso):
        monkeypatch.setenv("DATABRICKS_SECRET_SCOPE", "mi-scope")
        monkeypatch.setenv("DATABRICKS_SECRET_SCOPE_FOUNDRY_TOKEN", "otro-scope")
        monkeypatch.setenv("DATABRICKS_SECRET_KEY_FOUNDRY_TOKEN", "foundry-token")
        assert settings.get("FOUNDRY_AI_TOKEN") == "de-otro"

    def test_key_sin_scope_no_lee_y_avisa(self, monkeypatch, scope_falso, caplog):
        monkeypatch.setenv("DATABRICKS_SECRET_KEY_FOUNDRY_TOKEN", "foundry-token")
        assert settings.get("FOUNDRY_AI_TOKEN") is None
        assert scope_falso == []
        assert "DATABRICKS_SECRET_SCOPE_FOUNDRY_TOKEN" in caplog.text

    def test_los_nombres_pedidos_scope_y_key_por_credencial(self, monkeypatch, scope_falso):
        """Exactamente DATABRICKS_SECRET_SCOPE_FOUNDRY_TOKEN + DATABRICKS_SECRET_KEY_FOUNDRY_TOKEN."""
        monkeypatch.setenv("DATABRICKS_SECRET_SCOPE_FOUNDRY_TOKEN", "mi-scope")
        monkeypatch.setenv("DATABRICKS_SECRET_KEY_FOUNDRY_TOKEN", "foundry-token")
        assert settings.get("FOUNDRY_AI_TOKEN") == VALOR

    def test_tambien_con_el_nombre_completo_de_la_variable(self, monkeypatch, scope_falso):
        monkeypatch.setenv("DATABRICKS_SECRET_SCOPE_FOUNDRY_AI_TOKEN", "otro-scope")
        monkeypatch.setenv("DATABRICKS_SECRET_KEY_FOUNDRY_AI_TOKEN", "foundry-token")
        assert settings.get("FOUNDRY_AI_TOKEN") == "de-otro"

    def test_auth_secret_key_no_se_confunde_con_una_referencia(self, monkeypatch, scope_falso):
        """AUTH_SECRET_KEY es la firma de sesión, no un puntero a un secreto."""
        monkeypatch.setenv("AUTH_SECRET_KEY", "x" * 40)
        monkeypatch.setenv("DATABRICKS_SECRET_SCOPE", "mi-scope")
        assert settings.get("AUTH") is None and scope_falso == []


class TestPrecedencia:
    def test_el_entorno_gana_al_scope(self, monkeypatch, scope_falso):
        monkeypatch.setenv("FOUNDRY_AI_TOKEN", "del-entorno")
        monkeypatch.setenv("DATABRICKS_SECRET_SCOPE", "mi-scope")
        monkeypatch.setenv("DATABRICKS_SECRET_KEY_FOUNDRY_TOKEN", "foundry-token")
        assert settings.get("FOUNDRY_AI_TOKEN") == "del-entorno"
        assert scope_falso == [], "no debe llamar al scope si la variable ya existe"

    def test_la_ui_gana_a_todo(self, monkeypatch, scope_falso):
        monkeypatch.setenv("DATABRICKS_SECRET_SCOPE", "mi-scope")
        monkeypatch.setenv("DATABRICKS_SECRET_KEY_FOUNDRY_TOKEN", "foundry-token")
        assert settings.get("FOUNDRY_AI_TOKEN", ui="de-la-ui") == "de-la-ui"

    def test_se_lee_una_sola_vez(self, monkeypatch, scope_falso):
        monkeypatch.setenv("DATABRICKS_SECRET_SCOPE", "mi-scope")
        monkeypatch.setenv("DATABRICKS_SECRET_KEY_FOUNDRY_TOKEN", "foundry-token")
        settings.get("FOUNDRY_AI_TOKEN")
        settings.get("FOUNDRY_AI_TOKEN")
        assert len(scope_falso) == 1


class TestFallosYFugas:
    def test_un_fallo_nombra_scope_y_key_y_cae_al_default(self, monkeypatch, scope_falso, caplog):
        monkeypatch.setenv("DATABRICKS_SECRET_SCOPE", "mi-scope")
        monkeypatch.setenv("DATABRICKS_SECRET_KEY_FOUNDRY_TOKEN", "no-existe")
        assert settings.get("FOUNDRY_AI_TOKEN", default="") == ""
        assert "mi-scope" in caplog.text and "no-existe" in caplog.text

    def test_el_valor_leido_se_oculta_en_los_logs(self, monkeypatch, scope_falso):
        monkeypatch.setenv("DATABRICKS_SECRET_SCOPE", "mi-scope")
        monkeypatch.setenv("DATABRICKS_SECRET_KEY_FOUNDRY_TOKEN", "foundry-token")
        settings.get("FOUNDRY_AI_TOKEN")
        linea = f"llamando con cabecera {VALOR} al endpoint"
        assert VALOR not in settings.redact(linea)

    def test_faltantes_cuenta_lo_que_viene_del_scope(self, monkeypatch, scope_falso):
        monkeypatch.setenv("DATABRICKS_SECRET_SCOPE", "mi-scope")
        monkeypatch.setenv("DATABRICKS_SECRET_KEY_FOUNDRY_TOKEN", "foundry-token")
        assert settings.faltantes(("FOUNDRY_AI_TOKEN", "FOUNDRY_AI_ENDPOINT")) == ["FOUNDRY_AI_ENDPOINT"]


class TestLecturaReal:
    def test_sin_pyspark_usa_el_sdk_y_decodifica_base64(self, monkeypatch):
        """En Databricks Apps no hay dbutils: `get_secret` devuelve el valor en base64."""
        import base64
        import sys
        import types

        class _Resp:
            value = base64.b64encode(VALOR.encode()).decode()

        class _Secrets:
            def get_secret(self, scope, key):
                assert (scope, key) == ("mi-scope", "foundry-token")
                return _Resp()

        class _Cliente:
            secrets = _Secrets()

        sdk = types.ModuleType("databricks.sdk")
        sdk.WorkspaceClient = _Cliente
        monkeypatch.setitem(sys.modules, "databricks", types.ModuleType("databricks"))
        monkeypatch.setitem(sys.modules, "databricks.sdk", sdk)
        monkeypatch.setitem(sys.modules, "pyspark", None)   # fuerza ImportError de dbutils
        assert settings._leer_secreto("mi-scope", "foundry-token") == VALOR


def test_foundry_usa_el_token_del_scope_de_punta_a_punta(monkeypatch, scope_falso):
    """El token nunca está en el entorno: sale del scope y llega a la cabecera `api-key`."""
    from src.providers import Provider, ProviderSpec, build_chat_model

    for k, v in {"FOUNDRY_AI_ENDPOINT": "https://mi-recurso.openai.azure.com",
                 "FOUNDRY_AI_API_VERSION": "2024-10-21", "FOUNDRY_AI_DEPLOYMENT": "chat-dep",
                 "DATABRICKS_SECRET_SCOPE_FOUNDRY_TOKEN": "mi-scope",
                 "DATABRICKS_SECRET_KEY_FOUNDRY_TOKEN": "foundry-token"}.items():
        monkeypatch.setenv(k, v)
    llm = build_chat_model(ProviderSpec(proveedor=Provider.AZURE))
    assert llm.default_headers["api-key"] == VALOR

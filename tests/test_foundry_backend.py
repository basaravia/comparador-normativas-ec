"""Backend `foundry` del LLM y los embeddings por variables de entorno.

Foundry expone la API de OpenAI, así que reutiliza `Provider.DMR`; lo que estas pruebas
fijan son las trampas de ese atajo: un endpoint remoto no puede recibir el modelo por
defecto de Vertex, los embeddings tienen que leer `EMBED_*` y no el spec del LLM, y una
temperatura que el modelo rechaza tiene que poder omitirse.
"""
from __future__ import annotations

import pytest

from src import service
from src.errors import ProviderConfigError
from src.providers import Provider, ProviderSpec, build_chat_model, build_embedding_backend
from src.service import ServiceConfig

URL_FOUNDRY = "https://mi-recurso.services.ai.azure.com/openai/v1/"


@pytest.fixture(autouse=True)
def _sin_variables_del_entorno(monkeypatch):
    """Ni el `.env` del desarrollador ni su shell pueden decidir el resultado."""
    for k in ("LLM_BASE_URL", "LLM_API_KEY", "FOUNDRY_LLM_MODEL", "FOUNDRY_OMIT_TEMPERATURE",
              "DMR_LLM_MODEL", "DMR_BASE_URL", "EMBED_MODEL", "EMBED_BASE_URL", "EMBED_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr("src.settings.cargar_env", lambda *a, **k: False)


class _ChatFalso:
    def with_fallbacks(self, _otros):
        return self

    def __call__(self, _entrada):  # pragma: no cover - nunca se invoca
        raise AssertionError("esta prueba no debe llamar al modelo")


class TestModeloEnEndpointRemoto:
    """Antes se mandaba `DMR_LLM_MODEL` —el modelo de Vertex— a Groq o a Foundry."""

    def test_endpoint_remoto_sin_modelo_falla_diciendo_que_falta(self):
        spec = ProviderSpec(proveedor=Provider.DMR, base_url=URL_FOUNDRY, api_key="k")
        with pytest.raises(ProviderConfigError, match="No hay modelo configurado"):
            build_chat_model(spec)

    def test_endpoint_remoto_con_modelo_explicito_construye(self):
        spec = ProviderSpec(proveedor=Provider.DMR, modelo="mi-deployment",
                            base_url=URL_FOUNDRY, api_key="k")
        assert build_chat_model(spec).model_name == "mi-deployment"

    def test_el_modelo_de_dmr_llm_model_en_el_entorno_cuenta_como_explicito(self, monkeypatch):
        monkeypatch.setenv("DMR_LLM_MODEL", "desde-el-entorno")
        spec = ProviderSpec(proveedor=Provider.DMR, base_url=URL_FOUNDRY, api_key="k")
        assert build_chat_model(spec).model_name == "desde-el-entorno"

    def test_un_backend_local_sin_modelo_sigue_usando_el_default(self):
        """No se rompe el uso con Ollama/Docker Model Runner."""
        spec = ProviderSpec(proveedor=Provider.DMR, base_url="http://localhost:11434/v1")
        assert build_chat_model(spec).model_name

    def test_la_marca_sobrevive_a_resolver_dos_veces(self):
        """`construir_comparador` resuelve y luego `build_chat_model` vuelve a resolver."""
        spec = ProviderSpec(proveedor=Provider.DMR, base_url=URL_FOUNDRY, api_key="k")
        with pytest.raises(ProviderConfigError):
            build_chat_model(spec.resuelto())


class TestTemperatura:
    def test_por_defecto_se_envia(self):
        spec = ProviderSpec(proveedor=Provider.DMR, modelo="m", base_url=URL_FOUNDRY,
                            api_key="k", temperature=0.2)
        assert build_chat_model(spec).temperature == 0.2

    def test_sin_temperatura_la_omite(self):
        spec = ProviderSpec(proveedor=Provider.DMR, modelo="m", base_url=URL_FOUNDRY,
                            api_key="k", temperature=0.2, extra={"sin_temperatura": True})
        assert build_chat_model(spec).temperature is None


class TestEmbeddingsLeenSuPropiaConfiguracion:
    """`resuelto()` rellena el modelo con el de chat y la URL/clave con las del LLM, y como
    la UI gana a todo, `EMBED_*` del entorno quedaban ignoradas."""

    def _capturar(self, monkeypatch):
        capt: dict = {}

        class _Falso:
            def __init__(self, **kw):
                capt.update(kw)
        monkeypatch.setattr("src.embeddings.LangChainDMREmbeddings", _Falso)
        return capt

    def test_toma_modelo_url_y_clave_de_embed(self, monkeypatch):
        monkeypatch.setenv("EMBED_MODEL", "mi-embedding")
        monkeypatch.setenv("EMBED_BASE_URL", URL_FOUNDRY)
        monkeypatch.setenv("EMBED_API_KEY", "clave-embed")
        monkeypatch.setenv("LLM_API_KEY", "clave-del-llm")
        capt = self._capturar(monkeypatch)
        build_embedding_backend(ProviderSpec(proveedor=Provider.DMR))
        assert capt["model"] == "mi-embedding", "se usó el modelo de chat como embedding"
        assert capt["base_url"] == URL_FOUNDRY
        assert capt["api_key"] == "clave-embed", "la clave del LLM tapó la de embeddings"

    def test_lo_explicito_gana_al_entorno(self, monkeypatch):
        monkeypatch.setenv("EMBED_MODEL", "del-entorno")
        capt = self._capturar(monkeypatch)
        build_embedding_backend(ProviderSpec(proveedor=Provider.DMR, modelo="de-la-ui",
                                             base_url="http://x/v1"))
        assert capt["model"] == "de-la-ui"
        assert capt["base_url"] == "http://x/v1"

    def test_sin_nada_configurado_cae_al_default_de_embeddings_no_al_de_chat(self, monkeypatch):
        from src.config import DMR_EMBED_MODEL, VERTEX_LLM_MODEL
        capt = self._capturar(monkeypatch)
        build_embedding_backend(ProviderSpec(proveedor=Provider.DMR))
        assert capt["model"] == DMR_EMBED_MODEL
        assert capt["model"] != VERTEX_LLM_MODEL


class TestServicioFoundry:
    def _construir(self, monkeypatch, config: ServiceConfig, entorno: dict | None = None):
        entorno = entorno or {}
        original = service._get_setting
        monkeypatch.setattr(service, "_get_setting",
                            lambda k, default="": entorno.get(k, original(k, default=default)))
        vistos: list[ProviderSpec] = []

        def _fabrica(spec):
            vistos.append(spec)
            return _ChatFalso()
        monkeypatch.setattr("src.providers.build_chat_model", _fabrica)
        comparador = service.construir_comparador(indice=object(), config=config)
        return comparador, vistos

    def test_toma_url_modelo_y_clave_del_entorno(self, monkeypatch):
        cmp, vistos = self._construir(
            monkeypatch,
            ServiceConfig(llm_backend_kind="foundry", llm_api_key="clave"),
            {"LLM_BASE_URL": URL_FOUNDRY, "FOUNDRY_LLM_MODEL": "mi-deployment"},
        )
        assert cmp.grader._model_id == "mi-deployment"
        assert cmp.grader._base_url == URL_FOUNDRY
        assert vistos and vistos[0].reintentos_efectivos == 3, "un 429 debe esperar, no abortar"

    def test_la_ui_o_la_api_ganan_al_entorno(self, monkeypatch):
        cmp, _ = self._construir(
            monkeypatch,
            ServiceConfig(llm_backend_kind="foundry", llm_model="del-request",
                          llm_base_url="https://otro/v1", llm_api_key="clave"),
            {"LLM_BASE_URL": URL_FOUNDRY, "FOUNDRY_LLM_MODEL": "del-entorno"},
        )
        assert cmp.grader._model_id == "del-request"
        assert cmp.grader._base_url == "https://otro/v1"

    def test_sin_url_falla_diciendo_cual_variable_falta(self, monkeypatch):
        with pytest.raises(ProviderConfigError, match="LLM_BASE_URL"):
            self._construir(monkeypatch, ServiceConfig(llm_backend_kind="foundry",
                                                       llm_model="m", llm_api_key="k"))

    def test_sin_modelo_falla_antes_de_llamar_a_la_red(self, monkeypatch):
        """Sin este control, Foundry recibiría el nombre del modelo de Vertex."""
        monkeypatch.setattr("src.providers.build_chat_model", build_chat_model)
        with pytest.raises(ProviderConfigError, match="No hay modelo configurado"):
            service.construir_comparador(
                indice=object(),
                config=ServiceConfig(llm_backend_kind="foundry", llm_base_url=URL_FOUNDRY,
                                     llm_api_key="k"),
            )

    def test_omitir_temperatura_es_opt_in(self, monkeypatch):
        _, sin = self._construir(
            monkeypatch, ServiceConfig(llm_backend_kind="foundry", llm_model="m",
                                       llm_api_key="k", llm_base_url=URL_FOUNDRY))
        _, con = self._construir(
            monkeypatch, ServiceConfig(llm_backend_kind="foundry", llm_model="m",
                                       llm_api_key="k", llm_base_url=URL_FOUNDRY),
            {"FOUNDRY_OMIT_TEMPERATURE": "true"})
        assert not sin[0].extra.get("sin_temperatura")
        assert con[0].extra.get("sin_temperatura") is True

    def test_no_se_valida_contra_el_catalogo(self, monkeypatch):
        """Foundry nombra deployments, que `/models` no lista."""
        _, vistos = self._construir(
            monkeypatch, ServiceConfig(llm_backend_kind="foundry", llm_model="m",
                                       llm_api_key="k", llm_base_url=URL_FOUNDRY))
        assert vistos[0].extra.get("sin_listado") is True

    def test_groq_sin_modelo_lo_toma_de_su_variable_no_del_de_vertex(self, monkeypatch):
        cmp, _ = self._construir(
            monkeypatch, ServiceConfig(llm_backend_kind="groq", llm_api_key="k"),
            {"GROQ_LLM_MODEL": "openai/gpt-oss-120b"})
        assert cmp.grader._model_id == "openai/gpt-oss-120b"


class TestConexionConLaUIYLaAPI:
    def test_la_etiqueta_de_la_ui_se_traduce_a_foundry(self):
        cfg = ServiceConfig.desde_dict({"llm_backend_kind": "Foundry (cuenta propia)"})
        assert cfg.llm_backend_kind == "foundry"

    def test_la_api_acepta_foundry(self):
        from api.schemas import StartCompareRequest
        req = StartCompareRequest(llm_backend_kind="foundry", **_minimos_api())
        assert req.llm_backend_kind == "foundry"

    def test_la_api_sigue_rechazando_valores_desconocidos(self):
        from pydantic import ValidationError

        from api.schemas import StartCompareRequest
        with pytest.raises(ValidationError):
            StartCompareRequest(llm_backend_kind="inventado", **_minimos_api())


def _minimos_api() -> dict:
    """Campos obligatorios del request, sea cual sea su definición actual."""
    from api.schemas import StartCompareRequest
    return {n: "x" for n, f in StartCompareRequest.model_fields.items()
            if f.is_required()}

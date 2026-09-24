"""Backend `foundry` del LLM y los embeddings por variables de entorno.

Foundry va por `Provider.AZURE` (`ChatOpenAI` / `OpenAIEmbeddings` con la ruta de Azure) con
`FOUNDRY_AI_ENDPOINT`, `FOUNDRY_AI_TOKEN`, `FOUNDRY_AI_API_VERSION` y el deployment. Lo que
estas pruebas fijan: que esos valores llegan a la petición (URL, api-version, clave), que
el deployment de embeddings no se confunde con el de chat, que lo que falte se nombra, y
que un endpoint remoto genérico (Groq…) no puede recibir el modelo por defecto de Vertex.
"""
from __future__ import annotations

import pytest

from src import service
from src.errors import ProviderConfigError
from src.providers import Provider, ProviderSpec, build_chat_model, build_embedding_backend
from src.service import ServiceConfig

URL_FOUNDRY = "https://mi-recurso.services.ai.azure.com/openai/v1/"   # endpoint remoto genérico
ENDPOINT_AZURE = "https://mi-recurso.openai.azure.com"
API_VERSION = "2024-10-21"


@pytest.fixture
def foundry_env(monkeypatch):
    """Las cuatro variables que el usuario sustituye en el `.env`."""
    for k, v in {"FOUNDRY_AI_ENDPOINT": ENDPOINT_AZURE, "FOUNDRY_AI_TOKEN": "clave-secreta",
                 "FOUNDRY_AI_API_VERSION": API_VERSION,
                 "FOUNDRY_AI_DEPLOYMENT": "chat-dep",
                 "FOUNDRY_AI_EMBED_DEPLOYMENT": "emb-dep"}.items():
        monkeypatch.setenv(k, v)


@pytest.fixture(autouse=True)
def _sin_variables_del_entorno(monkeypatch):
    """Ni el `.env` del desarrollador ni su shell pueden decidir el resultado."""
    for k in ("FOUNDRY_AI_ENDPOINT", "FOUNDRY_AI_TOKEN", "FOUNDRY_AI_API_VERSION",
              "FOUNDRY_AI_DEPLOYMENT", "FOUNDRY_AI_EMBED_DEPLOYMENT", "LLM_BACKEND", "EMBED_BACKEND",
              "LLM_BASE_URL", "LLM_API_KEY", "FOUNDRY_LLM_MODEL", "FOUNDRY_OMIT_TEMPERATURE",
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

    def test_toma_endpoint_deployment_y_clave_del_entorno(self, monkeypatch, foundry_env):
        cmp, vistos = self._construir(monkeypatch, ServiceConfig(llm_backend_kind="foundry"))
        assert vistos[0].proveedor is Provider.AZURE
        assert cmp.grader._model_id == "chat-dep", "el modelo de Azure ES el deployment"
        assert cmp.grader._base_url == ENDPOINT_AZURE
        assert vistos[0].extra["api_version"] == API_VERSION
        assert vistos[0].reintentos_efectivos == 3, "un 429 debe esperar, no abortar"

    def test_la_ui_o_la_api_ganan_al_entorno(self, monkeypatch, foundry_env):
        cmp, _ = self._construir(
            monkeypatch,
            ServiceConfig(llm_backend_kind="foundry", llm_model="del-request",
                          llm_base_url="https://otro.openai.azure.com", llm_api_key="clave"),
        )
        assert cmp.grader._model_id == "del-request"
        assert cmp.grader._base_url == "https://otro.openai.azure.com"

    def test_sin_nada_configurado_nombra_todas_las_variables(self, monkeypatch):
        monkeypatch.setattr("src.providers.build_chat_model", build_chat_model)
        with pytest.raises(ProviderConfigError) as e:
            service.construir_comparador(
                indice=object(), config=ServiceConfig(llm_backend_kind="foundry"))
        assert e.value.faltantes == ["FOUNDRY_AI_ENDPOINT", "FOUNDRY_AI_TOKEN",
                                     "FOUNDRY_AI_API_VERSION", "FOUNDRY_AI_DEPLOYMENT"]

    def test_sin_api_version_falla_antes_de_llamar_a_la_red(self, monkeypatch, foundry_env):
        monkeypatch.delenv("FOUNDRY_AI_API_VERSION")
        monkeypatch.setattr("src.providers.build_chat_model", build_chat_model)
        with pytest.raises(ProviderConfigError, match="FOUNDRY_AI_API_VERSION") as e:
            service.construir_comparador(
                indice=object(), config=ServiceConfig(llm_backend_kind="foundry"))
        assert e.value.faltantes == ["FOUNDRY_AI_API_VERSION"], "no debe nombrar lo que sí está"

    def test_omitir_temperatura_es_opt_in(self, monkeypatch, foundry_env):
        _, sin = self._construir(monkeypatch, ServiceConfig(llm_backend_kind="foundry"))
        _, con = self._construir(monkeypatch, ServiceConfig(llm_backend_kind="foundry"),
                                 {"FOUNDRY_OMIT_TEMPERATURE": "true"})
        assert not sin[0].extra.get("sin_temperatura")
        assert con[0].extra.get("sin_temperatura") is True

    def test_no_se_valida_contra_el_catalogo(self, monkeypatch, foundry_env):
        """Foundry nombra deployments, que `/models` no lista."""
        _, vistos = self._construir(monkeypatch, ServiceConfig(llm_backend_kind="foundry"))
        assert vistos[0].extra.get("sin_listado") is True

    def test_groq_sin_modelo_lo_toma_de_su_variable_no_del_de_vertex(self, monkeypatch):
        cmp, _ = self._construir(
            monkeypatch, ServiceConfig(llm_backend_kind="groq", llm_api_key="k"),
            {"GROQ_LLM_MODEL": "openai/gpt-oss-120b"})
        assert cmp.grader._model_id == "openai/gpt-oss-120b"


class TestAzureChat:
    """`ChatOpenAI` recibe lo que el usuario sustituye en el `.env`, con la forma de Azure."""

    def test_es_chatopenai_y_apunta_al_deployment(self, foundry_env):
        from langchain_openai import AzureChatOpenAI, ChatOpenAI
        llm = build_chat_model(ProviderSpec(proveedor=Provider.AZURE, temperature=0.2))
        assert isinstance(llm, ChatOpenAI) and not isinstance(llm, AzureChatOpenAI)
        assert llm.model_name == "chat-dep"
        assert str(llm.openai_api_base) == f"{ENDPOINT_AZURE}/openai/deployments/chat-dep"
        assert llm.default_query == {"api-version": API_VERSION}
        assert llm.temperature == 0.2

    def test_sin_temperatura_la_omite(self, foundry_env):
        llm = build_chat_model(ProviderSpec(proveedor=Provider.AZURE, temperature=0.2,
                                            extra={"sin_temperatura": True}))
        assert llm.temperature is None

    def test_la_peticion_lleva_deployment_api_version_y_clave(self, foundry_env):
        """Sin red: se intercepta el HTTP y se mira lo que de verdad saldría."""
        import httpx
        capturado: dict = {}

        def _responder(request: httpx.Request) -> httpx.Response:
            capturado["url"] = str(request.url)
            capturado["api_key"] = request.headers.get("api-key")
            return httpx.Response(200, json={
                "id": "x", "object": "chat.completion", "created": 0, "model": "chat-dep",
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": "ok"}}],
            })

        llm = build_chat_model(ProviderSpec(proveedor=Provider.AZURE))
        llm.root_client._client = httpx.Client(transport=httpx.MockTransport(_responder))
        assert llm.invoke("hola").content == "ok"
        assert capturado["url"].startswith(
            f"{ENDPOINT_AZURE}/openai/deployments/chat-dep/chat/completions")
        assert f"api-version={API_VERSION}" in capturado["url"]
        assert capturado["api_key"] == "clave-secreta"

    @pytest.mark.parametrize("pegado", [
        ENDPOINT_AZURE + "/",
        ENDPOINT_AZURE + "/openai/v1/",
        ENDPOINT_AZURE + "/openai/deployments/otro/chat/completions",
    ])
    def test_una_ruta_pegada_en_el_endpoint_se_descarta(self, monkeypatch, foundry_env, pegado):
        monkeypatch.setenv("FOUNDRY_AI_ENDPOINT", pegado)
        llm = build_chat_model(ProviderSpec(proveedor=Provider.AZURE))
        assert str(llm.openai_api_base) == f"{ENDPOINT_AZURE}/openai/deployments/chat-dep"


class TestAzureEmbeddings:
    def test_usa_el_deployment_de_embeddings_no_el_de_chat(self, foundry_env):
        from langchain_openai import OpenAIEmbeddings
        backend = build_embedding_backend(ProviderSpec(proveedor=Provider.AZURE))
        assert isinstance(backend._embedder, OpenAIEmbeddings)
        assert backend._embedder.model == "emb-dep", "se usó el deployment de chat"
        assert str(backend._embedder.openai_api_base) == f"{ENDPOINT_AZURE}/openai/deployments/emb-dep"
        assert backend._embedder.default_query == {"api-version": API_VERSION}
        assert backend.nombre_modelo == "emb-dep"

    def test_el_modelo_explicito_gana_al_entorno(self, foundry_env):
        backend = build_embedding_backend(ProviderSpec(proveedor=Provider.AZURE, modelo="de-la-ui"))
        assert backend._embedder.model == "de-la-ui"
        assert str(backend._embedder.openai_api_base).endswith("/deployments/de-la-ui")

    def test_sin_deployment_de_embeddings_nombra_la_variable(self, monkeypatch, foundry_env):
        monkeypatch.delenv("FOUNDRY_AI_EMBED_DEPLOYMENT")
        with pytest.raises(ProviderConfigError, match="FOUNDRY_AI_EMBED_DEPLOYMENT"):
            build_embedding_backend(ProviderSpec(proveedor=Provider.AZURE))

    def test_la_peticion_lleva_deployment_api_version_y_clave(self, foundry_env):
        import httpx
        capturado: dict = {}

        def _responder(request: httpx.Request) -> httpx.Response:
            capturado["url"] = str(request.url)
            capturado["api_key"] = request.headers.get("api-key")
            return httpx.Response(200, json={
                "object": "list", "model": "emb-dep",
                "usage": {"prompt_tokens": 1, "total_tokens": 1},
                "data": [{"object": "embedding", "index": 0, "embedding": [0.1, 0.2]}],
            })

        backend = build_embedding_backend(ProviderSpec(proveedor=Provider.AZURE))
        backend._embedder.client._client._client = httpx.Client(transport=httpx.MockTransport(_responder))
        backend._embedder.embed_query("hola")
        assert capturado["url"].startswith(f"{ENDPOINT_AZURE}/openai/deployments/emb-dep/embeddings")
        assert f"api-version={API_VERSION}" in capturado["url"]
        assert capturado["api_key"] == "clave-secreta"

    def test_el_servicio_lo_elige_con_embed_backend_foundry(self, monkeypatch):
        vistos: list[ProviderSpec] = []
        monkeypatch.setattr(service, "build_embedding_backend", lambda s: vistos.append(s) or object())
        service.construir_backend_embeddings(ServiceConfig(embed_backend_kind="foundry"))
        assert vistos[0].proveedor is Provider.AZURE


class TestBackendDesdeElEntorno:
    """La UI mínima no manda `llm_backend_kind`: el `.env` tiene que poder elegirlo."""

    def test_sin_variables_los_defaults_de_siempre(self):
        cfg = ServiceConfig()
        assert (cfg.llm_backend_kind, cfg.embed_backend_kind) == ("vertex", "remoto")

    def test_llm_backend_y_embed_backend_del_entorno(self, monkeypatch):
        monkeypatch.setenv("LLM_BACKEND", "Foundry")
        monkeypatch.setenv("EMBED_BACKEND", "foundry")
        cfg = ServiceConfig()
        assert (cfg.llm_backend_kind, cfg.embed_backend_kind) == ("foundry", "foundry")

    def test_lo_explicito_gana_al_entorno(self, monkeypatch):
        monkeypatch.setenv("LLM_BACKEND", "foundry")
        assert ServiceConfig(llm_backend_kind="groq").llm_backend_kind == "groq"

    def test_un_valor_desconocido_falla_nombrando_la_variable(self, monkeypatch):
        monkeypatch.setenv("LLM_BACKEND", "azur")
        with pytest.raises(ProviderConfigError, match="LLM_BACKEND"):
            ServiceConfig()

    def test_la_etiqueta_de_la_ui_para_embeddings(self):
        cfg = ServiceConfig.desde_dict({"embed_backend_kind": "Foundry (cuenta propia)"})
        assert cfg.embed_backend_kind == "foundry"


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


class TestLaApiRespetaLLMBackend:
    def test_sin_backend_en_la_peticion_manda_el_entorno(self, monkeypatch):
        from api.routers.compare import _service_config_from_request
        from api.schemas import StartCompareRequest
        monkeypatch.setenv("LLM_BACKEND", "foundry")
        assert _service_config_from_request(StartCompareRequest()).llm_backend_kind == "foundry"

    def test_la_peticion_gana_al_entorno(self, monkeypatch):
        from api.routers.compare import _service_config_from_request
        from api.schemas import StartCompareRequest
        monkeypatch.setenv("LLM_BACKEND", "foundry")
        req = StartCompareRequest(llm_backend_kind="groq")
        assert _service_config_from_request(req).llm_backend_kind == "groq"

    def test_sin_nada_sigue_siendo_vertex(self):
        from api.routers.compare import _service_config_from_request
        from api.schemas import StartCompareRequest
        assert _service_config_from_request(StartCompareRequest()).llm_backend_kind == "vertex"


class TestPlaceholdersDeAppYaml:
    """Un `REEMPLAZAR-…` sin sustituir no es un valor: se nombra como falta, no como fallo de red."""

    def test_placeholder_cuenta_como_falta(self, monkeypatch, foundry_env):
        monkeypatch.setenv("FOUNDRY_AI_ENDPOINT", "REEMPLAZAR-https://<recurso>.openai.azure.com")
        monkeypatch.setenv("FOUNDRY_AI_API_VERSION", "REEMPLAZAR-2024-10-21")
        with pytest.raises(ProviderConfigError) as e:
            build_chat_model(ProviderSpec(proveedor=Provider.AZURE))
        assert e.value.faltantes == ["FOUNDRY_AI_ENDPOINT", "FOUNDRY_AI_API_VERSION"]
        assert "REEMPLAZAR" in str(e.value)

    def test_la_api_lo_informa(self, monkeypatch, foundry_env):
        from fastapi.testclient import TestClient

        from api.main import app
        monkeypatch.setenv("FOUNDRY_AI_DEPLOYMENT", "REEMPLAZAR-deployment-del-llm")
        f = [p for p in TestClient(app).get("/api/config/providers").json()["providers"]
             if p["id"] == "foundry"][0]
        assert f["disponible"] is False and "FOUNDRY_AI_DEPLOYMENT" in f["detalles"]

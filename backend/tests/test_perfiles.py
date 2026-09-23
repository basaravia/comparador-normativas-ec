"""Perfiles de modelos (config/perfiles.yaml): un parámetro elige el backend de cada eje.

Fijan la precedencia (petición > LLM_BACKEND/EMBED_BACKEND > MODEL_PROFILE > `activo`), que un
perfil mal escrito falle nombrando qué corregir, y que el LLM local no reciba el modelo de Vertex.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

# La API valida el perfil al importarse: se importa aquí, con el entorno limpio, para que ningún
# test que la use dependa de haber sido importada antes por otro.
from api.main import app
from src import perfiles, service
from src.errors import ProviderConfigError
from src.perfiles import PERFILES_PATH, cargar_perfiles, perfil_activo
from src.providers import build_chat_model
from src.service import ServiceConfig


@pytest.fixture(autouse=True)
def _entorno_limpio(monkeypatch):
    for k in ("MODEL_PROFILE", "LLM_BACKEND", "EMBED_BACKEND", "DMR_LLM_MODEL", "DMR_BASE_URL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr("src.settings.cargar_env", lambda *a, **k: False)


def _yaml(tmp_path, texto):
    ruta = tmp_path / "perfiles.yaml"
    ruta.write_text(texto, encoding="utf-8")
    return ruta


# ── El YAML que se distribuye ────────────────────────────────────────────────

class TestYamlDistribuido:
    def test_es_valido_y_trae_los_perfiles_pedidos(self):
        activo, perfs = cargar_perfiles()
        assert activo == "default"
        assert {n: (p.llm, p.embeddings) for n, p in perfs.items()} == {
            "default": ("vertex", "remoto"),
            "foundry": ("foundry", "foundry"),
            "local": ("local", "remoto"),
            "local_groq": ("groq", "remoto"),
            "personalizado": ("foundry", "remoto"),
        }

    def test_no_lleva_secretos(self):
        texto = PERFILES_PATH.read_text(encoding="utf-8").lower()
        for palabra in ("api_key", "token", "password", "secret"):
            assert f"{palabra}:" not in texto, f"el YAML no debe declarar {palabra}"


# ── Selección y precedencia ──────────────────────────────────────────────────

class TestSeleccion:
    def test_sin_nada_es_el_comportamiento_historico(self):
        cfg = ServiceConfig()
        assert (cfg.llm_backend_kind, cfg.embed_backend_kind) == ("vertex", "remoto")

    @pytest.mark.parametrize("perfil,llm,embed", [
        ("foundry", "foundry", "foundry"),
        ("local", "local", "remoto"),
        ("local_groq", "groq", "remoto"),
        ("personalizado", "foundry", "remoto"),
    ])
    def test_model_profile_elige_ambos_ejes(self, monkeypatch, perfil, llm, embed):
        monkeypatch.setenv("MODEL_PROFILE", perfil)
        cfg = ServiceConfig()
        assert (cfg.llm_backend_kind, cfg.embed_backend_kind) == (llm, embed)

    def test_activo_del_yaml_se_usa_sin_variable(self, tmp_path):
        ruta = _yaml(tmp_path, "activo: b\nperfiles:\n  a: {llm: vertex, embeddings: ollama}\n"
                               "  b: {llm: groq, embeddings: foundry}\n")
        assert perfil_activo(ruta).nombre == "b"

    def test_la_variable_gana_al_activo_del_yaml(self, monkeypatch, tmp_path):
        ruta = _yaml(tmp_path, "activo: b\nperfiles:\n  a: {llm: vertex, embeddings: ollama}\n"
                               "  b: {llm: groq, embeddings: foundry}\n")
        monkeypatch.setenv("MODEL_PROFILE", "a")
        assert perfil_activo(ruta).nombre == "a"

    def test_llm_backend_explicito_gana_al_perfil_solo_en_su_eje(self, monkeypatch):
        monkeypatch.setenv("MODEL_PROFILE", "foundry")
        monkeypatch.setenv("LLM_BACKEND", "groq")
        cfg = ServiceConfig()
        assert (cfg.llm_backend_kind, cfg.embed_backend_kind) == ("groq", "foundry")

    def test_embed_backend_acepta_el_alias_ollama(self, monkeypatch):
        monkeypatch.setenv("EMBED_BACKEND", "Ollama")
        assert ServiceConfig().embed_backend_kind == "remoto"

    def test_la_peticion_gana_a_todo(self, monkeypatch):
        monkeypatch.setenv("MODEL_PROFILE", "foundry")
        assert ServiceConfig(llm_backend_kind="vertex").llm_backend_kind == "vertex"


# ── Fallos que tienen que decir qué corregir ─────────────────────────────────

class TestErrores:
    def test_perfil_inexistente_lista_los_disponibles(self, monkeypatch):
        monkeypatch.setenv("MODEL_PROFILE", "foundy")
        with pytest.raises(ProviderConfigError, match="foundy") as e:
            ServiceConfig()
        for nombre in ("default", "foundry", "local", "local_groq", "personalizado"):
            assert nombre in str(e.value)

    def test_valor_invalido_nombra_perfil_campo_y_opciones(self, tmp_path):
        ruta = _yaml(tmp_path, "perfiles:\n  x: {llm: azur, embeddings: ollama}\n")
        with pytest.raises(ProviderConfigError, match=r"Perfil 'x': llm='azur'.*foundry"):
            cargar_perfiles(ruta)

    def test_el_reranker_ya_no_es_un_campo(self, tmp_path):
        ruta = _yaml(tmp_path, "perfiles:\n  x: {llm: vertex, embeddings: ollama, reranker: local}\n")
        with pytest.raises(ProviderConfigError, match="reranker"):
            cargar_perfiles(ruta)

    def test_falta_un_eje(self, tmp_path):
        ruta = _yaml(tmp_path, "perfiles:\n  x: {llm: vertex}\n")
        with pytest.raises(ProviderConfigError, match="falta embeddings"):
            cargar_perfiles(ruta)

    def test_yaml_roto(self, tmp_path):
        ruta = _yaml(tmp_path, "perfiles: [sin cerrar\n")
        with pytest.raises(ProviderConfigError, match="YAML"):
            cargar_perfiles(ruta)

    def test_sin_archivo_y_sin_pedir_perfil_usa_el_historico(self, tmp_path):
        p = perfil_activo(tmp_path / "no-existe.yaml")
        assert (p.llm, p.embeddings) == ("vertex", "remoto")

    def test_sin_archivo_pero_pidiendo_perfil_falla(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MODEL_PROFILE", "foundry")
        with pytest.raises(ProviderConfigError, match="no existe"):
            perfil_activo(tmp_path / "no-existe.yaml")

    def test_backend_explicito_invalido_nombra_la_variable(self, monkeypatch):
        monkeypatch.setenv("EMBED_BACKEND", "azur")
        with pytest.raises(ProviderConfigError, match="EMBED_BACKEND"):
            ServiceConfig()


# ── LLM local (Ollama) ───────────────────────────────────────────────────────

class TestLlmLocal:
    def _grader(self, monkeypatch):
        monkeypatch.setattr("src.providers.build_chat_model", build_chat_model)
        return service.construir_comparador(
            indice=object(), config=ServiceConfig(llm_backend_kind="local")).grader

    def test_sin_modelo_no_manda_el_de_vertex(self, monkeypatch):
        with pytest.raises(ProviderConfigError, match="DMR_LLM_MODEL"):
            self._grader(monkeypatch)

    def test_con_modelo_apunta_a_ollama(self, monkeypatch):
        monkeypatch.setenv("DMR_LLM_MODEL", "qwen2.5:3b")
        g = self._grader(monkeypatch)
        assert g._llm_grader.model_name == "qwen2.5:3b"
        assert "11434" in str(g._llm_grader.openai_api_base)


# ── Lo que ve la API ─────────────────────────────────────────────────────────

class TestApi:
    def _providers(self):
        return TestClient(app).get("/api/config/providers").json()

    def test_informa_el_perfil_y_los_backends_efectivos(self, monkeypatch):
        monkeypatch.setenv("MODEL_PROFILE", "local_groq")
        p = self._providers()["perfil"]
        assert (p["nombre"], p["llm"], p["embeddings"], p["con_override"]) == \
            ("local_groq", "groq", "remoto", False)

    def test_marca_el_override(self, monkeypatch):
        monkeypatch.setenv("MODEL_PROFILE", "foundry")
        monkeypatch.setenv("LLM_BACKEND", "groq")
        p = self._providers()["perfil"]
        assert (p["llm"], p["con_override"]) == ("groq", True)

    def test_un_perfil_roto_se_reporta_sin_tumbar_la_ruta(self, monkeypatch):
        monkeypatch.setenv("MODEL_PROFILE", "inventado")
        r = self._providers()
        assert r["perfil"] is None and "inventado" in r["perfil_error"]


def test_los_valores_validos_coinciden_con_los_de_service():
    """Un solo lugar define los backends: service no puede aceptar uno que el YAML rechace."""
    assert service.LLM_BACKENDS is perfiles.LLM_BACKENDS
    assert service.EMBED_BACKENDS is perfiles.EMBED_BACKENDS

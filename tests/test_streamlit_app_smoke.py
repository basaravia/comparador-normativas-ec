"""Pruebas funcionales de streamlit_app.py con streamlit.testing.v1.AppTest —
sin LLM, sin red (excepto el chequeo GET /models de DMR usado para el
indicador "conectado", que tolera fallo silenciosamente vía _check_dmr()).

Cubren: render inicial sin excepciones, que la barra lateral produzca una
configuración con los defaults de src/config.py, y que el botón de
tabulación quede deshabilitado cuando no hay documentos seleccionados.
"""
from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest

from src import config as cfg


def _find_button(at: AppTest, text: str):
    for b in at.button:
        if text in (b.label or ""):
            return b
    raise AssertionError(f"botón no encontrado: {text!r} (labels: {[b.label for b in at.button]})")


@pytest.fixture
def at(app_path: str) -> AppTest:
    at = AppTest.from_file(app_path, default_timeout=60)
    at.run()
    return at


def test_app_renders_without_exceptions(at: AppTest):
    assert not at.exception, f"la app lanzó excepciones en el render inicial: {list(at.exception)}"


def test_app_renders_sidebar_and_four_tabs(at: AppTest):
    assert len(at.sidebar) > 0, "la barra lateral debe tener widgets"
    assert len(at.tabs) == 4, "la app debe exponer las 4 pestañas del flujo (Documentos/Índice/Comparación/Resultados)"


class TestSidebarDefaultsMatchConfig:
    """La barra lateral inicializa cada widget `cfg_*` con el default de src/config.py
    (contrato explícito del feature: 'widgets con keys cfg_* que defaultean desde
    src/config.py')."""

    def test_dmr_base_url_default(self, at: AppTest):
        assert at.text_input(key="cfg_dmr_url").value == cfg.DMR_BASE_URL

    def test_reranker_model_default(self, at: AppTest):
        assert at.text_input(key="cfg_reranker_model").value == cfg.RERANKER_MODEL

    def test_temperature_default(self, at: AppTest):
        assert at.slider(key="cfg_temperature").value == cfg.LLM_TEMPERATURE

    def test_faiss_top_k_default(self, at: AppTest):
        assert at.slider(key="cfg_faiss_top_k").value == cfg.FAISS_TOP_K

    def test_reranker_top_n_default(self, at: AppTest):
        assert at.slider(key="cfg_reranker_top_n").value == cfg.RERANKER_TOP_N

    def test_min_semantic_score_default(self, at: AppTest):
        assert at.slider(key="cfg_min_score").value == cfg.MIN_SEMANTIC_SCORE

    def test_llm_max_tokens_default(self, at: AppTest):
        assert at.number_input(key="cfg_llm_max_tokens").value == cfg.LLM_MAX_TOKENS

    def test_grader_max_tokens_default(self, at: AppTest):
        assert at.number_input(key="cfg_grader_max_tokens").value == cfg.LLM_GRADER_MAX_TOKENS

    def test_docling_max_tokens_default(self, at: AppTest):
        assert at.number_input(key="cfg_docling_max_tokens").value == cfg.DOCLING_MAX_TOKENS

    def test_max_workers_default(self, at: AppTest):
        assert at.number_input(key="cfg_max_workers").value == cfg.MAX_WORKERS

    def test_embed_batch_size_default(self, at: AppTest):
        assert at.number_input(key="cfg_embed_batch").value == cfg.EMBED_BATCH_SIZE

    def test_device_defaults_to_cpu(self, at: AppTest):
        # index=0 en el selectbox ["cpu", "auto", "mps", "cuda"] — 'cpu' por
        # seguridad ante el segfault de MPS documentado en el sidebar.
        assert at.selectbox(key="cfg_device").value == "cpu"

    def test_do_ocr_default_enabled(self, at: AppTest):
        assert at.checkbox(key="cfg_do_ocr").value is True

    def test_use_reranker_default_enabled(self, at: AppTest):
        assert at.checkbox(key="cfg_use_reranker").value is True


def test_tab_documentos_tabular_button_disabled_when_no_documents_selected(at: AppTest):
    at.multiselect(key="normativa_existing").set_value([])
    at.multiselect(key="manual_existing").set_value([])
    at.run(timeout=30)

    assert not at.exception
    boton = _find_button(at, "Tabular documentos")
    assert boton.disabled is True


def test_tab_documentos_tabular_button_enabled_when_both_selected(at: AppTest):
    """Contraparte del caso anterior: con al menos un PDF de cada lado
    seleccionado, el botón debe habilitarse (disabled=not(normativa and manual))."""
    norm_ms = at.multiselect(key="normativa_existing")
    man_ms = at.multiselect(key="manual_existing")
    if not norm_ms.options or not man_ms.options:
        pytest.skip("no hay PDFs de muestra disponibles en Normativa2026/ o document_test/")

    norm_ms.set_value(norm_ms.options[:1])
    man_ms.set_value(man_ms.options[:1])
    at.run(timeout=30)

    assert not at.exception
    boton = _find_button(at, "Tabular documentos")
    assert boton.disabled is False


def test_tab_index_shows_hint_when_documents_not_yet_tabulated(at: AppTest):
    """Sin normativa_df en session_state, la pestaña Índice debe guiar al
    usuario a tabular primero en vez de exponer un botón que fallaría."""
    tab_index = at.tabs[1]
    info_texts = " ".join(el.value for el in tab_index.info)
    assert "Tabula primero los documentos" in info_texts


def test_tab_results_shows_hint_when_no_results_yet(at: AppTest):
    tab_results = at.tabs[3]
    info_texts = " ".join(el.value for el in tab_results.info)
    assert "Ejecuta una comparación" in info_texts

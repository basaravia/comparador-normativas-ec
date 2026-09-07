"""Configuración compartida de pytest para la suite del comparador de normativas.

Fija el cwd al root del repo (las rutas de la app — ``Normativa2026/``,
``document_test/``, ``output/`` — son relativas al directorio de trabajo,
igual que cuando se ejecuta ``streamlit run streamlit_app.py`` desde la raíz).
También aplica el mismo workaround de OpenMP que ``streamlit_app.py`` y
``master.ipynb`` antes de que cualquier test importe faiss/docling/torch.
"""
from __future__ import annotations

from pathlib import Path

# Mismo arranque que la app, antes de que cualquier módulo importe faiss/docling/torch.
# Una copia del workaround aquí volvería a duplicar lo que bootstrap centraliza.
import src.bootstrap  # noqa: F401

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_PATH = str(REPO_ROOT / "streamlit_app.py")

# `import src` / `import app` los resuelve `pythonpath` en pyproject.toml, y los
# marcadores se declaran ahí mismo con --strict-markers. Antes ambas cosas vivían
# aquí: un sys.path.insert y un pytest_configure que ya no hacen falta.


@pytest.fixture(autouse=True)
def _repo_root_cwd(monkeypatch: pytest.MonkeyPatch) -> None:
    """Todas las pruebas corren con cwd=raíz del repo (rutas relativas de la app)."""
    monkeypatch.chdir(REPO_ROOT)


@pytest.fixture(autouse=True)
def _clean_streamlit_session_state(monkeypatch: pytest.MonkeyPatch):
    """Limpia st.session_state y desactiva auth solo durante AppTest.

    La autenticación queda activa por defecto en producción; las pruebas de UI
    existentes validan el flujo interno y deben entrar directamente a las tabs.
    """
    monkeypatch.setenv("AUTH_ENABLED", "false")
    import streamlit as st

    st.session_state.clear()
    yield
    st.session_state.clear()


@pytest.fixture
def app_path() -> str:
    return APP_PATH


# ── Corpus sintético y dobles ─────────────────────────────────────────────
# Ver tests/fixtures/corpus.py para los casos límite que el corpus construye.


@pytest.fixture
def normativa_df():
    from tests.fixtures import normativa_df as _n
    return _n()


@pytest.fixture
def manual_df():
    from tests.fixtures import manual_df as _m
    return _m()


@pytest.fixture
def fake_embeddings():
    from tests.fixtures import FakeEmbeddingBackend
    return FakeEmbeddingBackend()


@pytest.fixture
def fake_grader():
    """Grader determinista. Para veredictos o fallos concretos, constrúyelo en la
    prueba: `FakeGrader(veredictos={...}, fallar_en=...)`."""
    from tests.fixtures import FakeGrader
    return FakeGrader()


@pytest.fixture
def fake_index(normativa_df):
    """Índice falso sin FAISS. El `plan` (embed_text -> element_ids) lo fija la prueba."""
    from tests.fixtures import FakeIndex
    return FakeIndex(normativa_df=normativa_df)

"""Configuración compartida de pytest para la suite del comparador de normativas.

Fija el cwd al root del repo (las rutas de la app — ``Normativa2026/``,
``document_test/``, ``output/`` — son relativas al directorio de trabajo,
igual que cuando se ejecuta ``streamlit run streamlit_app.py`` desde la raíz).
También aplica el mismo workaround de OpenMP que ``streamlit_app.py`` y
``master.ipynb`` antes de que cualquier test importe faiss/docling/torch.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Mismo workaround que streamlit_app.py: evita crash nativo en Apple Silicon
# cuando faiss y el runtime OpenMP de Docling/torch coexisten en el proceso.
# Debe fijarse antes de que cualquier módulo importe esas librerías.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_PATH = str(REPO_ROOT / "streamlit_app.py")

# Garantiza que `import src` / `import app` funcionen sin importar desde
# dónde se invoque pytest.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "e2e: pruebas end-to-end lentas que requieren DMR real (Docker Model Runner)"
    )


@pytest.fixture(autouse=True)
def _repo_root_cwd(monkeypatch: pytest.MonkeyPatch) -> None:
    """Todas las pruebas corren con cwd=raíz del repo (rutas relativas de la app)."""
    monkeypatch.chdir(REPO_ROOT)


@pytest.fixture(autouse=True)
def _clean_streamlit_session_state():
    """Limpia st.session_state antes y después de cada prueba.

    st.session_state es un singleton de proceso fuera de un ScriptRunContext
    real (funciona en "bare mode" con solo un warning) y AppTest crea su
    propio contexto por script-run, pero los tests que llaman directamente a
    funciones de app/logging_utils.py comparten el mismo estado si no se
    limpia entre pruebas.
    """
    import streamlit as st

    st.session_state.clear()
    yield
    st.session_state.clear()


@pytest.fixture
def app_path() -> str:
    return APP_PATH

"""Pruebas funcionales de app/logging_utils.py.

Cubre: acumulación de logs en el panel en vivo (st.session_state),
idempotencia de setup_logging() ante reruns de Streamlit, y persistencia de
save_run_log() con nombre de archivo con estampa de tiempo.

Sin red, sin LLM. st.session_state funciona en "bare mode" (fuera de un
ScriptRunContext real) como un dict de proceso — solo emite un warning
inocuo de Streamlit, que no afecta las aserciones.
"""
from __future__ import annotations

import logging
import re

import pytest
import streamlit as st

from app import logging_utils


@pytest.fixture(autouse=True)
def _isolate_logging_state():
    """Aísla el estado global de logging entre pruebas.

    setup_logging() adjunta handlers al logger raíz una sola vez *por
    proceso* (guard ``_handlers_attached``, ver docstring del módulo). Sin
    esta fixture, la primera prueba que llame setup_logging() dejaría los
    handlers adjuntos para siempre y ninguna prueba posterior podría
    verificar la idempotencia partiendo de un estado limpio.
    """
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    original_level = root.level
    original_attached = logging_utils._handlers_attached

    yield

    root.handlers = original_handlers
    root.level = original_level
    logging_utils._handlers_attached = original_attached


def test_setup_logging_attaches_console_and_buffer_handlers():
    logging_utils._handlers_attached = False
    root = logging.getLogger()
    before = len(root.handlers)

    logging_utils.setup_logging()

    assert len(root.handlers) == before + 2
    assert any(isinstance(h, logging.StreamHandler) for h in root.handlers)
    assert any(isinstance(h, logging_utils._StreamlitBufferHandler) for h in root.handlers)


def test_setup_logging_is_idempotent_does_not_duplicate_handlers():
    """Streamlit re-ejecuta el script completo en cada interacción del usuario,
    así que setup_logging() se llama de nuevo en cada rerun — no debe
    duplicar handlers ni las líneas de log saldrían repetidas por sesión."""
    logging_utils._handlers_attached = False
    root = logging.getLogger()

    logging_utils.setup_logging()
    count_after_first_call = len(root.handlers)

    logging_utils.setup_logging()
    logging_utils.setup_logging()

    assert len(root.handlers) == count_after_first_call


def test_get_log_lines_empty_by_default():
    assert logging_utils.get_log_lines() == []


def test_buffer_handler_accumulates_formatted_lines_in_session_state():
    logging_utils._handlers_attached = False
    logging_utils.setup_logging()

    logger = logging.getLogger("test.buffer")
    logger.info("mensaje de prueba %s", 123)

    lines = logging_utils.get_log_lines()
    assert len(lines) == 1
    assert "mensaje de prueba 123" in lines[0]
    assert "[INFO]" in lines[0]
    assert "test.buffer" in lines[0]


def test_buffer_handler_does_not_duplicate_lines_across_reruns():
    logging_utils._handlers_attached = False
    logging_utils.setup_logging()
    logging_utils.setup_logging()  # simula un segundo rerun de Streamlit

    logging.getLogger("test.buffer").info("una sola línea")

    assert len(logging_utils.get_log_lines()) == 1


def test_clear_log_lines_resets_buffer():
    st.session_state["_log_buffer"] = ["línea vieja 1", "línea vieja 2"]

    logging_utils.clear_log_lines()

    assert logging_utils.get_log_lines() == []


def test_save_run_log_creates_file_with_timestamp_pattern_and_buffer_content(tmp_path, monkeypatch):
    monkeypatch.setattr(logging_utils, "_LOG_DIR", tmp_path / "logs")
    st.session_state["_log_buffer"] = [
        "10:00:00 [INFO] app: inicio",
        "10:00:05 [INFO] app: fin",
    ]

    path = logging_utils.save_run_log()

    assert path.exists()
    assert path.parent == tmp_path / "logs"
    assert re.match(r"run_\d{8}_\d{6}\.log$", path.name), f"nombre inesperado: {path.name}"
    content = path.read_text(encoding="utf-8")
    assert "10:00:00 [INFO] app: inicio" in content
    assert "10:00:05 [INFO] app: fin" in content


def test_save_run_log_creates_output_dir_if_missing(tmp_path, monkeypatch):
    target_dir = tmp_path / "nested" / "logs"
    assert not target_dir.exists()
    monkeypatch.setattr(logging_utils, "_LOG_DIR", target_dir)
    st.session_state["_log_buffer"] = ["línea única"]

    path = logging_utils.save_run_log()

    assert target_dir.exists()
    assert path.parent == target_dir


def test_save_run_log_handles_empty_buffer_without_error(tmp_path, monkeypatch):
    monkeypatch.setattr(logging_utils, "_LOG_DIR", tmp_path / "logs")
    st.session_state["_log_buffer"] = []

    path = logging_utils.save_run_log()

    assert path.exists()
    assert path.read_text(encoding="utf-8") == "\n"

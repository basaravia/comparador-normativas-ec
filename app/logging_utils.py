"""Logging de la app: consola (CLI) + panel en vivo + persistencia con estampa de tiempo.

Mismo formato que ``master.ipynb`` (``logging.basicConfig`` en la celda de
configuración) para que la salida de terminal sea consistente entre el
notebook y la app. Los handlers se adjuntan al logger raíz una sola vez por
proceso (no por sesión de Streamlit) — el script se re-ejecuta en cada
interacción, así que sin esta guarda cada línea saldría duplicada por
sesión abierta.
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

import streamlit as st

_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATEFMT = "%H:%M:%S"
_LOG_DIR = Path("output/logs")
_SESSION_KEY = "_log_buffer"

_handlers_attached = False  # global de proceso, no de sesión


class _StreamlitBufferHandler(logging.Handler):
    """Acumula líneas formateadas en st.session_state para el panel en vivo."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
        except Exception:
            return
        try:
            st.session_state.setdefault(_SESSION_KEY, []).append(line)
        except Exception:
            pass  # fuera de un script-run de Streamlit (p.ej. hilo sin contexto)


def setup_logging(level: int = logging.INFO) -> None:
    """Configura logging de consola + panel en vivo. Llamar al inicio del script."""
    global _handlers_attached
    st.session_state.setdefault(_SESSION_KEY, [])

    if _handlers_attached:
        return

    root = logging.getLogger()
    root.setLevel(level)
    formatter = logging.Formatter(_FORMAT, datefmt=_DATEFMT)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)

    buffer_handler = _StreamlitBufferHandler()
    buffer_handler.setFormatter(formatter)
    root.addHandler(buffer_handler)

    _handlers_attached = True


def get_log_lines() -> list[str]:
    return st.session_state.get(_SESSION_KEY, [])


def clear_log_lines() -> None:
    st.session_state[_SESSION_KEY] = []


def save_run_log() -> Path:
    """Persiste el buffer de logs de la sesión a un archivo con estampa de tiempo.

    Pensado para llamarse al finalizar una ejecución (éxito o error).
    """
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = _LOG_DIR / f"run_{timestamp}.log"
    lines = get_log_lines()
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path

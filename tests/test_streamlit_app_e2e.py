"""Prueba E2E de humo para streamlit_app.py — flujo completo con DMR real.

Requiere Docker Model Runner corriendo en localhost:12434 con
``ai/granite-embedding-multilingual:latest`` (embeddings) y
``docker.io/ai/gemma4:latest`` (LLM) cargados — son los defaults de
src/config.py que usa la barra lateral, así que la prueba no cambia ningún
parámetro del sidebar.

Ejercita el flujo real de un usuario: tabular normativa + manual (Docling,
con caché) -> construir índice FAISS (embeddings DMR + reranker CrossEncoder
local) -> ejecutar comparación en modo "Muestra rápida" con n=1 -> verificar
resultados y exportaciones en session_state, y que se haya persistido un log
de la ejecución en output/logs/.

Documentos elegidos (ver notas del proyecto):
  - PDL-DERECHOS-DIGITALES.pdf: normativa con caché Docling (tabulación
    ~instantánea, 44 elementos).
  - [REDACTADO] …V2.pdf: manual más pequeño de document_test/, conversión
    Docling en vivo pero acotada (~1 min en este hardware).

Tiempos observados en este entorno (Apple M1 16GB, gemma4 vía DMR): tabulación
~1 min, índice FAISS ~15s, comparación de 1 sección ~3-5 min (grading +
análisis con razonamiento CoT interno de gemma4) — se usan timeouts generosos
para no producir falsos negativos por lentitud del hardware/modelo.

Se excluye del run por defecto vía el marcador ``e2e``:
    pytest -m "not e2e"       # suite rápida (default recomendado en CI)
    pytest -m e2e             # solo esta prueba, con DMR real corriendo
"""
from __future__ import annotations

import time
from pathlib import Path

import httpx
import pytest
from streamlit.testing.v1 import AppTest

from src import config as cfg

pytestmark = pytest.mark.e2e

LOG_DIR = Path("output/logs")
NIVELES_VALIDOS = {"cumple", "parcial", "omision", "no_aplica"}


def _dmr_available() -> bool:
    try:
        r = httpx.get(f"{cfg.DMR_BASE_URL}/models", timeout=3.0)
        return r.status_code == 200
    except Exception:
        return False


def _find_button(at: AppTest, text: str):
    for b in at.button:
        if text in (b.label or ""):
            return b
    raise AssertionError(f"botón no encontrado: {text!r} (labels: {[b.label for b in at.button]})")


def _assert_no_exception(at: AppTest, step: str) -> None:
    if at.exception:
        details = "\n".join(str(e) for e in at.exception)
        pytest.fail(f"excepción no esperada tras '{step}':\n{details}")


def _session_value(at: AppTest, key: str, step: str):
    """at.session_state.get(...) no existe en el proxy de AppTest — hay que
    indexar y capturar KeyError/AttributeError (ver notas del proyecto)."""
    try:
        return at.session_state[key]
    except (KeyError, AttributeError):
        pytest.fail(f"'{key}' no quedó en session_state tras '{step}'")


@pytest.mark.skipif(not _dmr_available(), reason="Docker Model Runner no responde en DMR_BASE_URL")
def test_full_comparison_flow_end_to_end(app_path: str):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logs_before = set(LOG_DIR.glob("run_*.log"))

    at = AppTest.from_file(app_path, default_timeout=60)
    at.run()
    _assert_no_exception(at, "render inicial")

    # ── Tab 1: seleccionar documentos y tabular ───────────────────────────
    # Selección por substring ASCII de las opciones reales del widget, no
    # por literal Python con tildes: en macOS los nombres de document_test/
    # están normalizados en NFD y un literal fuente (NFC) no matchea.
    norm_ms = at.multiselect(key="normativa_existing")
    norm_choice = [o for o in norm_ms.options if "PDL-DERECHOS" in str(o)]
    assert norm_choice, f"PDL-DERECHOS-DIGITALES.pdf no está en las opciones: {norm_ms.options}"
    norm_ms.set_value(norm_choice)

    man_ms = at.multiselect(key="manual_existing")
    man_choice = [o for o in man_ms.options if "[REDACTADO]" in str(o)]
    assert man_choice, f"[REDACTADO] no está en las opciones: {man_ms.options}"
    man_ms.set_value(man_choice)

    at.run(timeout=60)
    _assert_no_exception(at, "selección de documentos")

    t0 = time.time()
    _find_button(at, "Tabular documentos").click().run(timeout=300)
    _assert_no_exception(at, "tabulación de documentos")
    tabulacion_s = time.time() - t0

    normativa_df = _session_value(at, "normativa_df", "tabulación")
    manual_df = _session_value(at, "manual_df", "tabulación")
    assert len(normativa_df) > 0, f"la normativa tabulada está vacía ({tabulacion_s:.1f}s)"
    assert len(manual_df) > 0, f"el manual tabulado está vacío ({tabulacion_s:.1f}s)"

    # ── Tab 2: construir índice FAISS (embeddings DMR + reranker CrossEncoder) ──
    _find_button(at, "Construir índice FAISS").click().run(timeout=180)
    _assert_no_exception(at, "construcción del índice FAISS")
    normativa_index = _session_value(at, "normativa_index", "construcción del índice")
    assert normativa_index is not None

    # ── Tab 3: comparación en modo 'Muestra rápida' con n=1 sección ──────
    at.radio(key="cfg_run_mode").set_value("Muestra rápida")
    at.run(timeout=30)
    _assert_no_exception(at, "seleccionar modo de ejecución")

    at.number_input(key="cfg_sample_n").set_value(1)
    at.run(timeout=30)
    _assert_no_exception(at, "fijar tamaño de muestra")

    t0 = time.time()
    _find_button(at, "Ejecutar comparación").click().run(timeout=600)
    comparacion_s = time.time() - t0
    _assert_no_exception(at, "ejecutar comparación")

    # ── Resultados en session_state ───────────────────────────────────────
    results_df = _session_value(at, "results_df", f"comparación ({comparacion_s:.1f}s)")
    assert len(results_df) == 1, f"se pidió una muestra de 1 sección, resultó en {len(results_df)} filas"

    nivel = results_df.iloc[0]["nivel_cumplimiento"]
    assert nivel in NIVELES_VALIDOS, f"nivel_cumplimiento inesperado: {nivel!r} (esperado uno de {NIVELES_VALIDOS})"
    assert str(results_df.iloc[0]["analisis_general"]).strip(), "analisis_general no debe estar vacío"
    assert results_df.iloc[0]["tipo_coincidencia"] in {"lexica", "semantica", "ninguna"}

    excel_bytes = _session_value(at, "excel_bytes", "exportación Excel")
    json_bytes = _session_value(at, "json_bytes", "exportación JSON")
    assert excel_bytes, "el reporte Excel exportado no debe estar vacío"
    assert json_bytes, "el reporte JSON exportado no debe estar vacío"
    assert json_bytes.decode("utf-8").strip().startswith("["), "el JSON exportado debe ser una lista de registros"

    # ── Log de la ejecución persistido en output/logs/ (save_run_log()) ───
    logs_after = set(LOG_DIR.glob("run_*.log"))
    new_logs = logs_after - logs_before
    assert new_logs, "save_run_log() debía crear un nuevo output/logs/run_*.log durante esta ejecución"
    new_log = max(new_logs, key=lambda p: p.stat().st_mtime)
    log_content = new_log.read_text(encoding="utf-8")
    assert "Iniciando comparación" in log_content
    assert "Comparación completa" in log_content or "Comparación interrumpida" in log_content

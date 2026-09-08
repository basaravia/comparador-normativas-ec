"""Router para ejecución de comparación, streaming de eventos SSE y exportación.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncGenerator, Callable, Dict

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from api.routers.documents import get_document_cache
from api.schemas import RunStatusResponse, StartCompareRequest, StartCompareResponse
from app.run_manager import RunHandle, gestor
from src import scope, service
from src.errors import RunAbortedError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/compare", tags=["Comparación"])

# Almacén de bundles de corridas en memoria, keyed por run_id igual que
# `RunManager._corridas`. Se purga en el mismo momento que ese registro (ver
# `_purgar_cachés_compare`) para no crecer sin límite por su cuenta.
_RUN_BUNDLES: Dict[str, Any] = {}
_RUN_PATHS: Dict[str, service.RunPaths] = {}


def _purgar_cachés_compare() -> None:
    """Alinea `_RUN_BUNDLES`/`_RUN_PATHS` con lo que `RunManager` todavía conoce.

    `RunManager._purgar_terminales()` libera corridas viejas de su propio registro;
    sin esto, estas dos cachés de este módulo seguían creciendo indefinidamente aun
    después de que la corrida correspondiente ya no existiera en ningún otro lado —
    cada una guarda un `ComparisonBundle` completo (varios DataFrames con texto de
    análisis), así que es memoria real, no solo un diccionario vacío.
    """
    conocidos = gestor().run_ids_conocidos()
    for cache in (_RUN_BUNDLES, _RUN_PATHS):
        for run_id in list(cache):
            if run_id not in conocidos:
                del cache[run_id]


def _construir_trabajo(
    run_id: str,
    req: StartCompareRequest,
    normativa_df: Any,
    manual_df: Any,
    normativa_index: Any,
    cfg: service.ServiceConfig,
    rutas: service.RunPaths,
) -> Callable[[RunHandle], Any]:
    """Arma el callable que `RunManager.lanzar()` ejecuta en su propio hilo.

    Antes esta ruta reimplementaba a mano el ciclo de vida completo (estado
    CORRIENDO/COMPLETADO/FALLIDO, registro de errores) en vez de pasar por
    `gestor().lanzar()` — que ya hace exactamente esto y es lo que usa
    `streamlit_app.py`. Dos implementaciones del mismo ciclo de vida es como se
    llega a que un backend pierda `RunAbortedError.parciales` mientras el otro los
    conserva, o que uno nunca marque un estado terminal y el otro sí.
    """

    def trabajo(handle: RunHandle) -> Any:
        if req.scope:
            sel_norm = scope.filtrar_articulos(
                normativa_df,
                doc_ids=req.scope.doc_ids_normativa or None,
                incluir_referencias=(req.scope.preset_articulos == "Todo el articulado"),
            )
            if req.scope.muestra_n:
                sel_man = scope.muestra_rapida(
                    manual_df, req.scope.muestra_n, aleatoria=req.scope.muestra_aleatoria
                )
            else:
                sel_man = manual_df
        else:
            sel_norm = normativa_df
            sel_man = manual_df

        def _on_progress(via: str, hechas: int, total: int):
            handle.progreso = hechas
            handle.total = total
            handle.etiqueta_actual = f"Procesando {via} ({hechas}/{total})"
            gestor()._espejar(handle)

        try:
            if req.dual_mode:
                manual_idx = service.construir_indice_manual(sel_man, cfg)
                bundle = service.comparar_dual(
                    indice_normativa=normativa_index,
                    indice_manual=manual_idx,
                    manual_df=sel_man,
                    normativa_df=sel_norm,
                    config=cfg,
                    min_score=req.min_score,
                    top_k=req.top_k,
                    progress_callback=_on_progress,
                )
                _RUN_BUNDLES[run_id] = bundle
                results_df = bundle.vista_manual
            else:
                results_df = service.comparar(
                    normativa_index,
                    sel_man,
                    sel_norm,
                    cfg,
                    progress_callback=lambda d, t, r: _on_progress("Vía 1", d, t),
                    cancelar=handle.cancelar,
                )
        except RunAbortedError as e:
            # A diferencia del resto de excepciones (que `lanzar()` ya clasifica
            # como FALLIDO con `handle.error` = str(e)), esta trae resultados
            # parciales que ya se pagaron en llamadas al LLM — perderlos porque el
            # router los descartaba con un `except Exception` genérico era tirar
            # trabajo hecho. Se exportan antes de relanzar, igual que
            # `streamlit_app.py` los conserva etiquetados como incompletos.
            if e.parciales is not None and len(e.parciales):
                service.exportar(
                    e.parciales, rutas,
                    metadatos={"run_id": run_id, "workspace_id": "local", "parcial": True},
                )
            logger.error("Corrida %s abortada (parcial): %s", run_id, e)
            raise RunAbortedError(
                f"{e.completadas} de {e.total} secciones analizadas, "
                f"{e.omitidas} sin procesar. Causa: {e.causa}",
                completadas=e.completadas, total=e.total, causa=e.causa,
            ) from e

        service.exportar(
            results_df,
            rutas,
            bundle=_RUN_BUNDLES.get(run_id),
            metadatos={"run_id": run_id, "workspace_id": "local"},
        )
        return results_df

    return trabajo


@router.post("/start", response_model=StartCompareResponse)
def start_compare(req: StartCompareRequest) -> StartCompareResponse:
    """Inicia una corrida de comparación asíncrona.

    `gestor().lanzar()` ya arranca su propio hilo y devuelve de inmediato — no hace
    falta envolverlo en `BackgroundTasks` de FastAPI encima; sería un segundo nivel
    de asincronía sobre uno que ya no bloquea.
    """
    cache = get_document_cache()
    normativa_df = cache.get("normativa_df")
    manual_df = cache.get("manual_df")
    normativa_index = cache.get("normativa_index")

    if normativa_df is None or manual_df is None or normativa_index is None:
        raise HTTPException(
            status_code=400,
            detail="Documentos no tabulados o índice no construido. Ejecute pasos 1 y 2.",
        )

    # Purga ANTES de registrar la corrida nueva: `_purgar_cachés_compare()` borra lo
    # que `gestor()` ya no conoce, y en el orden inverso se borraría a sí misma —
    # `gestor()` todavía no sabe de este run_id hasta que `lanzar()` lo registra.
    _purgar_cachés_compare()

    run_id = service.nuevo_run_id()
    rutas = service.RunPaths(run_id=run_id)
    _RUN_PATHS[run_id] = rutas

    total_est = len(manual_df)
    handle = RunHandle(run_id=run_id, total=total_est)
    cfg = service.ServiceConfig()
    trabajo = _construir_trabajo(run_id, req, normativa_df, manual_df, normativa_index, cfg, rutas)
    gestor().lanzar(handle, trabajo)

    return StartCompareResponse(
        run_id=run_id,
        status="iniciado",
        stream_url=f"/api/compare/stream/{run_id}",
    )


@router.get("/stream/{run_id}")
async def stream_progress(run_id: str):
    """Canal Server-Sent Events (SSE) para recibir el progreso en vivo."""
    handle = gestor().obtener(run_id)
    if not handle:
        raise HTTPException(status_code=404, detail="Corrida no encontrada")

    async def event_generator() -> AsyncGenerator[str, None]:
        while True:
            h = gestor().obtener(run_id)
            if not h:
                break

            data = {
                "run_id": run_id,
                "estado": h.estado.value,
                "progreso": h.progreso,
                "total": h.total,
                "porcentaje": round(h.porcentaje, 3),
                "etiqueta": h.etiqueta_actual,
                "lineas": h.lineas(5),
                "error": h.error,
            }
            yield f"data: {json.dumps(data)}\n\n"

            if h.estado.terminal:
                break

            await asyncio.sleep(0.8)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/runs/{run_id}", response_model=RunStatusResponse)
def get_run_status(run_id: str) -> RunStatusResponse:
    """Retorna el estado detallado y resultados de una corrida."""
    handle = gestor().obtener(run_id)
    if not handle:
        raise HTTPException(status_code=404, detail=f"Corrida {run_id} no encontrada")

    bundle = _RUN_BUNDLES.get(run_id)
    cobertura_pct = None
    alerta = None
    sin_cobertura = []
    v1_data = []
    v2_data = []
    motivos_rev = []
    total_rev = 0

    if bundle is not None:
        cobertura_pct = bundle.cobertura.porcentaje
        alerta = bundle.alerta_cobertura
        sin_cobertura = bundle.cobertura.sin_cobertura
        v1_data = bundle.vista_manual.to_dict(orient="records")
        v2_data = bundle.vista_normativa.to_dict(orient="records")

        # Motivos y conteos de revisión manual (Ítem 10)
        filas_rev_v1 = [r for r in v1_data if r.get("requiere_revision_manual")]
        filas_rev_v2 = [r for r in v2_data if r.get("requiere_revision_manual")]
        total_rev = len(filas_rev_v1) + len(filas_rev_v2)
        motivos_rev = sorted({
            m for r in (v1_data + v2_data) for m in (r.get("motivos_revision") or [])
        })

    return RunStatusResponse(
        run_id=run_id,
        estado=handle.estado.value,
        progreso=handle.progreso,
        total=handle.total,
        porcentaje=handle.porcentaje,
        etiqueta=handle.etiqueta_actual,
        error=handle.error,
        cobertura_global=cobertura_pct,
        alerta_cobertura=alerta,
        articulos_sin_cobertura=sin_cobertura,
        vista_manual=v1_data,
        vista_normativa=v2_data,
        motivos_revision=motivos_rev,
        total_revision_manual=total_rev,
    )


@router.get("/runs/{run_id}/export/{formato}")
def export_run(run_id: str, formato: str):
    """Descarga el Papel de Trabajo en Excel (6 hojas) o archivo JSON."""
    rutas = _RUN_PATHS.get(run_id) or service.RunPaths(run_id=run_id)
    if formato.lower() in ("excel", "xlsx"):
        if not rutas.excel.exists():
            raise HTTPException(status_code=404, detail="Archivo Excel aún no disponible")
        return FileResponse(
            path=rutas.excel,
            filename=f"papel_trabajo_{run_id}.xlsx",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    elif formato.lower() == "json":
        if not rutas.json.exists():
            raise HTTPException(status_code=404, detail="Archivo JSON aún no disponible")
        return FileResponse(
            path=rutas.json,
            filename=f"reporte_{run_id}.json",
            media_type="application/json",
        )
    else:
        raise HTTPException(status_code=400, detail="Formato no soportado (use excel o json)")

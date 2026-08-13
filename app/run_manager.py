"""Ciclo de vida de las corridas, a nivel de proceso (ítem 2).

El defecto: la corrida es bloqueante dentro del script-run de Streamlit. Al refrescar el
navegador, Streamlit crea una sesión nueva con `session_state` vacío mientras los hilos
siguen vivos en el proceso — la terminal avanza y la web dice "En espera…". Peor: pulsar
"Ejecutar" otra vez lanza una segunda corrida sobre la misma configuración, duplicando el
gasto de LLM sin que nadie lo note.

La causa es dónde vive el estado. `session_state` es **por pestaña del navegador**; la
corrida es **del proceso**. Este módulo mueve el registro al nivel que le corresponde:

  · registro de proceso, protegido por lock — sobrevive a refrescos y lo ven todas las
    pestañas;
  · espejo en disco (`state.json`) — permite detectar corridas huérfanas incluso tras
    reiniciar Streamlit, y es la base sobre la que la Fase 3 pondrá almacenamiento
    externo sin cambiar esta interfaz;
  · cancelación cooperativa mediante un evento que el pipeline consulta.

`session_state` pasa a guardar **solo el `run_id`**. Todo lo demás se re-adjunta.
"""
from __future__ import annotations

import json
import logging
import threading
import traceback
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Cuántas líneas de log se conservan por corrida para el panel en vivo.
_MAX_LINEAS_LOG = 500


class EstadoCorrida(str, Enum):
    PENDIENTE = "pendiente"
    CORRIENDO = "corriendo"
    ABORTANDO = "abortando"
    COMPLETADO = "completado"
    FALLIDO = "fallido"
    CANCELADO = "cancelado"

    @property
    def terminal(self) -> bool:
        return self in (EstadoCorrida.COMPLETADO, EstadoCorrida.FALLIDO,
                        EstadoCorrida.CANCELADO)


@dataclass
class RunHandle:
    """Una corrida y su estado. Vive en el proceso, no en la sesión."""

    run_id: str
    total: int = 0
    progreso: int = 0
    estado: EstadoCorrida = EstadoCorrida.PENDIENTE
    iniciado_en: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    terminado_en: str | None = None
    config_hash: str = ""
    etiqueta_actual: str = ""
    error: str | None = None

    # No se serializan: son del proceso vivo.
    cancelar: threading.Event = field(default_factory=threading.Event, repr=False)
    resultado: Any = field(default=None, repr=False)
    _log: deque = field(default_factory=lambda: deque(maxlen=_MAX_LINEAS_LOG), repr=False)

    @property
    def porcentaje(self) -> float:
        return self.progreso / self.total if self.total else 0.0

    @property
    def viva(self) -> bool:
        return not self.estado.terminal

    def registrar(self, linea: str) -> None:
        """Añade una línea al buffer de esta corrida.

        Por `run_id` y no en `st.session_state`: el handler de logs escribía en la sesión
        desde hilos worker que no tienen `ScriptRunContext`, fallaba en silencio y el
        panel "Registro de ejecución" quedaba vacío justo cuando hacía falta.
        """
        self._log.append(linea)

    def lineas(self, ultimas: int | None = None) -> list[str]:
        xs = list(self._log)
        return xs[-ultimas:] if ultimas else xs

    def como_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "estado": self.estado.value,
            "progreso": self.progreso,
            "total": self.total,
            "iniciado_en": self.iniciado_en,
            "terminado_en": self.terminado_en,
            "config_hash": self.config_hash,
            "error": self.error,
        }


class RunManager:
    """Registro de corridas del proceso.

    Una instancia por proceso (ver `gestor()`). El lock protege el diccionario, no la
    ejecución: dos corridas distintas pueden avanzar en paralelo, lo que no puede pasar es
    que dos hilos registren la misma a la vez.
    """

    def __init__(self, raiz: Path | str = "output/runs") -> None:
        self.raiz = Path(raiz)
        self._corridas: dict[str, RunHandle] = {}
        self._lock = threading.RLock()

    # ── consulta ──────────────────────────────────────────────────────────

    def obtener(self, run_id: str) -> RunHandle | None:
        with self._lock:
            return self._corridas.get(run_id)

    def activas(self) -> list[RunHandle]:
        with self._lock:
            return [h for h in self._corridas.values() if h.viva]

    def todas(self) -> list[RunHandle]:
        with self._lock:
            return sorted(self._corridas.values(), key=lambda h: h.iniciado_en, reverse=True)

    def activa_con_config(self, config_hash: str) -> RunHandle | None:
        """Corrida viva con la misma configuración.

        Es lo que impide lanzar dos veces lo mismo: sin esto, pulsar "Ejecutar" tras un
        refresco duplicaba el gasto de LLM en silencio.
        """
        with self._lock:
            return next(
                (h for h in self._corridas.values() if h.viva and h.config_hash == config_hash),
                None,
            )

    # ── ciclo de vida ─────────────────────────────────────────────────────

    def registrar(self, handle: RunHandle) -> RunHandle:
        with self._lock:
            self._corridas[handle.run_id] = handle
        self._espejar(handle)
        return handle

    def lanzar(
        self,
        handle: RunHandle,
        trabajo: Callable[[RunHandle], Any],
    ) -> RunHandle:
        """Ejecuta `trabajo` en un hilo propio y devuelve el handle de inmediato.

        `trabajo` recibe el handle para reportar progreso y consultar `cancelar`. No se
        le pasa nada de Streamlit a propósito: este módulo no debe saber qué interfaz lo
        usa.
        """
        self.registrar(handle)

        def _correr() -> None:
            handle.estado = EstadoCorrida.CORRIENDO
            self._espejar(handle)
            try:
                handle.resultado = trabajo(handle)
                handle.estado = (
                    EstadoCorrida.CANCELADO if handle.cancelar.is_set()
                    else EstadoCorrida.COMPLETADO
                )
            except Exception as e:
                # Se guarda el error, no se propaga: nadie está esperando este hilo, y
                # una excepción no capturada aquí moriría en silencio con el hilo.
                handle.estado = EstadoCorrida.FALLIDO
                handle.error = f"{type(e).__name__}: {e}"
                handle.registrar(f"ERROR: {handle.error}")
                logger.error("Corrida %s falló: %s", handle.run_id, e)
                logger.debug("%s", traceback.format_exc())
            finally:
                handle.terminado_en = datetime.now(timezone.utc).isoformat(timespec="seconds")
                self._espejar(handle)

        threading.Thread(target=_correr, name=f"corrida-{handle.run_id}", daemon=True).start()
        return handle

    def cancelar(self, run_id: str) -> bool:
        """Cancelación cooperativa: marca el evento y el pipeline lo consulta.

        No se mata el hilo. Interrumpir a la fuerza dejaría el checkpoint a medias y
        artefactos sin cerrar; el pipeline comprueba el evento entre unidades y sale
        limpiamente conservando lo hecho.
        """
        handle = self.obtener(run_id)
        if handle is None or not handle.viva:
            return False
        handle.cancelar.set()
        handle.estado = EstadoCorrida.ABORTANDO
        handle.registrar("Cancelación solicitada; se detendrá tras la unidad en curso.")
        self._espejar(handle)
        return True

    # ── espejo en disco ───────────────────────────────────────────────────

    def _espejar(self, handle: RunHandle) -> None:
        """Escribe `state.json`. Tolera fallos: es diagnóstico, no la fuente de verdad."""
        try:
            d = self.raiz / handle.run_id
            d.mkdir(parents=True, exist_ok=True)
            (d / "state.json").write_text(
                json.dumps(handle.como_dict(), ensure_ascii=False, indent=2), encoding="utf-8",
            )
        except OSError as e:
            logger.warning("No se pudo espejar el estado de %s: %s", handle.run_id, e)

    def huerfanas(self) -> list[dict]:
        """Corridas que el disco dice vivas pero el proceso no conoce.

        Tras reiniciar Streamlit, el registro en memoria nace vacío mientras en disco
        quedan corridas marcadas como corriendo. No se pueden reanudar desde aquí —sus
        hilos murieron con el proceso anterior— pero sí hay que mostrarlas: son las
        candidatas a reanudar con el checkpoint del ítem 3.
        """
        if not self.raiz.exists():
            return []
        fuera = []
        for d in sorted(self.raiz.iterdir(), reverse=True):
            estado_path = d / "state.json"
            if not estado_path.exists() or self.obtener(d.name) is not None:
                continue
            try:
                estado = json.loads(estado_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if estado.get("estado") in ("corriendo", "pendiente", "abortando"):
                fuera.append(estado)
        return fuera


# ── instancia de proceso ──────────────────────────────────────────────────────

_gestor: RunManager | None = None
_gestor_lock = threading.Lock()


def gestor(raiz: Path | str = "output/runs") -> RunManager:
    """Gestor único del proceso.

    Un singleton perezoso y no una variable de módulo directa: Streamlit reejecuta el
    script en cada interacción, y solo la primera debe crear el registro. Si se recreara,
    cada refresco perdería las corridas en curso — que es el defecto que este módulo
    corrige.
    """
    global _gestor
    if _gestor is None:
        with _gestor_lock:
            if _gestor is None:
                _gestor = RunManager(raiz)
    return _gestor


def reiniciar_gestor() -> None:
    """Descarta el gestor. Solo para pruebas."""
    global _gestor
    with _gestor_lock:
        _gestor = None

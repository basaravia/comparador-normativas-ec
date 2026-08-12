"""Validación de modelos antes de gastar un token.

El ítem 4 nace de dos fallos que se refuerzan. Uno: la app comprueba que el endpoint
responde (`status_code == 200`) pero nunca lee la lista ni verifica que el modelo
configurado exista, así que un modelo mal escrito se descubre a mitad de una corrida de
horas. Dos: los desplegables del sidebar son constantes escritas a mano, de modo que
ofrecen modelos que quizá no están y ocultan los que sí.

El resultado es el riesgo espejo del ítem 1: allí se perdían secciones por un fallo
ruidoso; aquí se cuelan **falsos positivos de cumplimiento** en silencio, que en un papel
de trabajo de auditoría es mucho peor.

Se construye sobre las costuras de `providers.py`: el listado es distinto en cada
proveedor y consultarlo directamente contra un endpoint concreto obligaría a reescribirlo
al añadir el primero de nube.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from .errors import LLMUnavailableError, ModelNotFoundError, classify_llm_exception
from .providers import ProviderSpec, list_models

logger = logging.getLogger(__name__)

# Caché corta: Streamlit reejecuta el script en cada interacción y sin esto cada
# movimiento de un slider golpearía el endpoint. 15 s es suficiente para una sesión de
# ajustes y lo bastante corto para notar que un modelo se cayó.
_TTL_S = 15.0
_cache: dict[str, tuple[float, list[str]]] = {}


@dataclass(frozen=True)
class ModelInfo:
    id: str
    proveedor: str


def limpiar_cache() -> None:
    """Fuerza la relectura. La usan las pruebas y el botón de recarga de la UI."""
    _cache.clear()


def modelos_disponibles(spec: ProviderSpec, *, usar_cache: bool = True) -> list[str]:
    """IDs de modelo del proveedor. Lista vacía si no responde — no lanza.

    Devolver vacío en vez de propagar es deliberado: esta función alimenta los
    desplegables del sidebar, y una excepción ahí dejaría la app sin arrancar por algo
    que solo debería degradar la experiencia. Quien necesite el fallo duro usa
    `validar_modelo()` o `preflight()`.
    """
    spec = spec.resuelto()
    clave = f"{spec.proveedor.value}|{spec.base_url}"

    if usar_cache:
        entrada = _cache.get(clave)
        if entrada and (time.monotonic() - entrada[0]) < _TTL_S:
            return entrada[1]

    try:
        modelos = sorted(list_models(spec))
    except Exception as e:
        logger.warning("No se pudo listar modelos de %s: %s", spec.proveedor.value, e)
        modelos = []

    _cache[clave] = (time.monotonic(), modelos)
    return modelos


def validar_modelo(spec: ProviderSpec, model_id: str) -> None:
    """Lanza `ModelNotFoundError` si el modelo no está en el proveedor.

    El mensaje incluye la lista real disponible: decir "no existe" sin decir qué sí existe
    obliga a adivinar, y adivinar contra un endpoint es lo que produce corridas tiradas.
    """
    spec = spec.resuelto()
    if not spec.capacidades.listado_modelos:
        # Sin endpoint de listado no se puede afirmar que falte. Callar es correcto:
        # inventar un error donde no hay evidencia es peor que no comprobar.
        logger.debug("El proveedor %s no expone listado; se omite la validación",
                     spec.proveedor.value)
        return

    disponibles = modelos_disponibles(spec)
    if not disponibles:
        raise LLMUnavailableError(
            "No se pudo obtener la lista de modelos para validar la configuración",
            modelo=model_id, url=spec.base_url,
        )

    if model_id not in disponibles:
        raise ModelNotFoundError(
            f"El modelo '{model_id}' no está disponible",
            modelo=model_id, url=spec.base_url, disponibles=disponibles,
        )


@dataclass(frozen=True)
class ResultadoPreflight:
    ok: bool
    mensajes: list[str]
    modelos: list[str]

    def __bool__(self) -> bool:
        return self.ok


def preflight(
    spec_llm: ProviderSpec,
    modelo_llm: str,
    spec_embed: ProviderSpec | None = None,
    modelo_embed: str | None = None,
) -> ResultadoPreflight:
    """Comprueba LLM **y** embeddings antes de arrancar.

    Los dos, no solo el LLM: una corrida con el modelo de embeddings mal configurado
    construye un índice inservible y el fallo aparece mucho después, cuando ya se pagó el
    tiempo de indexación.

    No lanza: devuelve el diagnóstico completo para que la UI pueda mostrar todos los
    problemas a la vez en vez de uno por intento.
    """
    mensajes: list[str] = []
    modelos = modelos_disponibles(spec_llm)

    for etiqueta, spec, modelo in (
        ("LLM", spec_llm, modelo_llm),
        ("embeddings", spec_embed, modelo_embed),
    ):
        if spec is None or not modelo:
            continue
        try:
            validar_modelo(spec, modelo)
        except ModelNotFoundError as e:
            mensajes.append(f"{etiqueta}: {e}")
        except LLMUnavailableError as e:
            mensajes.append(f"{etiqueta}: {e}")
        except Exception as e:                      # pragma: no cover - defensivo
            mensajes.append(f"{etiqueta}: {classify_llm_exception(e)}")

    return ResultadoPreflight(ok=not mensajes, mensajes=mensajes, modelos=modelos)

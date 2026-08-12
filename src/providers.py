"""Costuras de proveedor: dónde se construyen los clientes de modelo, y solo ahí.

**Alcance deliberadamente reducido.** Este módulo no trae ningún backend de nube. Su única
misión es que añadirlos más adelante sea escribir una fábrica, no refactorizar el pipeline.
Hoy `LLMGrader` instancia `ChatOpenAI` dentro de su `__init__` y `LangChainDMREmbeddings`
hace lo propio con `OpenAIEmbeddings`: mientras eso siga así, cada proveedor nuevo obliga a
tocar el motor.

La Fase 3 añadirá aquí `AzureChatOpenAI` / `AzureOpenAIEmbeddings` con Managed Identity.
Nada fuera de este módulo debería enterarse.

Un `ProviderSpec` describe *qué* se quiere; las fábricas deciden *cómo* construirlo. Los
timeouts y reintentos viajan en el spec porque están calibrados para un backend local
secuencial: en nube conviene lo contrario (timeout más corto, reintentos con backoff), y
eso no puede quedar escrito a mano en el grader.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .config import (
    DMR_BASE_URL,
    DMR_EMBED_MODEL,
    DMR_LLM_MODEL,
    EMBED_BATCH_SIZE,
    LLM_MAX_TOKENS,
    LLM_TEMPERATURE,
)
from .errors import ProviderConfigError
from .settings import faltantes, get


class Provider(str, Enum):
    """Proveedores soportados.

    Solo hay dos porque solo hay dos implementados. Las entradas de nube se añaden en la
    Fase 3, cuando exista una suscripción contra la que verificarlas: declararlas ahora
    sería prometer un camino que nadie ha recorrido.
    """

    DMR = "dmr"              # backend local compatible con la API de OpenAI
    LOCAL_ST = "local_st"    # sentence-transformers en proceso (solo embeddings)


@dataclass(frozen=True)
class ProviderCapabilities:
    """Qué sabe hacer un proveedor y con qué parámetros conviene usarlo."""

    chat: bool
    embeddings: bool
    listado_modelos: bool
    requiere_env: tuple[str, ...] = ()
    # Concurrencia sugerida. En local es 1: el backend procesa secuencialmente y subirlo
    # solo añade presión de memoria. En nube sube, y es lo que dejará resuelto el ítem 15.
    concurrencia_recomendada: int = 1
    timeout_s: int = 180
    max_retries: int = 0
    # Prefijos que exige el modelo de embeddings. e5 los necesita; el backend local los
    # usa y el de DMR no. Vive aquí para que nadie vuelva a fijarlos a ciegas.
    prefijo_documento: str = ""
    prefijo_consulta: str = ""


CAPACIDADES: dict[Provider, ProviderCapabilities] = {
    Provider.DMR: ProviderCapabilities(
        chat=True,
        embeddings=True,
        listado_modelos=True,
        concurrencia_recomendada=1,
        timeout_s=180,
        max_retries=0,
    ),
    Provider.LOCAL_ST: ProviderCapabilities(
        chat=False,
        embeddings=True,
        listado_modelos=False,
        concurrencia_recomendada=1,
        # intfloat/multilingual-e5-large exige estos prefijos; sin ellos rinde por debajo
        # de su capacidad (defecto 3 de §2.2 del plan).
        prefijo_documento="passage: ",
        prefijo_consulta="query: ",
    ),
}


@dataclass(frozen=True)
class ProviderSpec:
    """Qué proveedor, qué modelo y con qué parámetros."""

    proveedor: Provider
    modelo: str | None = None
    base_url: str | None = None
    temperature: float = LLM_TEMPERATURE
    max_tokens: int = LLM_MAX_TOKENS
    batch_size: int = EMBED_BATCH_SIZE
    device: str = "auto"
    # Sobrescriben lo que declaran las capacidades del proveedor. §7 pedía que los
    # timeouts dejaran de estar escritos a mano en el grader, y las capacidades solos no
    # bastan: son constantes por proveedor, y el grading y el análisis tienen
    # presupuestos distintos (2 min frente a 3) porque generan volúmenes distintos.
    timeout_s: int | None = None
    max_retries: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def timeout_efectivo(self) -> int:
        return self.timeout_s if self.timeout_s is not None else self.capacidades.timeout_s

    @property
    def reintentos_efectivos(self) -> int:
        return (self.max_retries if self.max_retries is not None
                else self.capacidades.max_retries)

    @property
    def capacidades(self) -> ProviderCapabilities:
        return CAPACIDADES[self.proveedor]

    def resuelto(self) -> ProviderSpec:
        """Rellena lo que falte desde el entorno y los defaults (precedencia de settings)."""
        if self.proveedor is Provider.DMR:
            return ProviderSpec(
                proveedor=self.proveedor,
                modelo=get("DMR_LLM_MODEL", ui=self.modelo, default=DMR_LLM_MODEL),
                base_url=get("DMR_BASE_URL", ui=self.base_url, default=DMR_BASE_URL),
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                batch_size=self.batch_size,
                device=self.device,
                timeout_s=self.timeout_s,
                max_retries=self.max_retries,
                extra=self.extra,
            )
        return self


def validate(spec: ProviderSpec) -> None:
    """Aborta antes de gastar un token si falta configuración.

    El mensaje enumera **exactamente** qué variables faltan: "credenciales inválidas" sin
    decir cuáles obliga a adivinar, y adivinar con credenciales acaba en claves pegadas
    en sitios donde no deben estar.
    """
    ausentes = faltantes(spec.capacidades.requiere_env)
    if ausentes:
        raise ProviderConfigError(
            f"Faltan variables para el proveedor '{spec.proveedor.value}': "
            f"{', '.join(ausentes)}",
            faltantes=ausentes,
        )


def build_chat_model(spec: ProviderSpec) -> Any:
    """Construye el modelo de chat. Es el único sitio del proyecto que lo hace."""
    spec = spec.resuelto()
    if not spec.capacidades.chat:
        raise ProviderConfigError(
            f"El proveedor '{spec.proveedor.value}' no ofrece chat; elige otro para el LLM"
        )
    validate(spec)

    if spec.proveedor is Provider.DMR:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=spec.modelo,
            base_url=spec.base_url,
            api_key="ignored",          # el backend local no autentica
            temperature=spec.temperature,
            max_tokens=spec.max_tokens,
            timeout=spec.timeout_efectivo,
            max_retries=spec.reintentos_efectivos,
        )

    raise ProviderConfigError(f"Proveedor de chat no soportado: {spec.proveedor.value}")


def construir_embeddings_openai(*, model: str, base_url: str, api_key: str = "ignored") -> Any:
    """Cliente de embeddings compatible con la API de OpenAI.

    Existe para que `embeddings.py` no lo instancie por su cuenta: la construcción de
    clientes vive aquí y solo aquí, que es lo que hará barato añadir Azure en la Fase 3.
    """
    from langchain_openai import OpenAIEmbeddings

    return OpenAIEmbeddings(
        model=model,
        base_url=base_url,
        api_key=api_key,
        check_embedding_ctx_length=False,
    )


def construir_sentence_transformer(*, model_name: str, device: str) -> Any:
    """Modelo local de sentence-transformers. Import perezoso: arrastra torch."""
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name, device=device)


def build_embedding_backend(spec: ProviderSpec) -> Any:
    """Construye el backend de embeddings, con la interfaz `EmbeddingBackend`."""
    spec = spec.resuelto()
    if not spec.capacidades.embeddings:
        raise ProviderConfigError(
            f"El proveedor '{spec.proveedor.value}' no ofrece embeddings"
        )
    validate(spec)

    if spec.proveedor is Provider.DMR:
        from .embeddings import LangChainDMREmbeddings

        return LangChainDMREmbeddings(
            model=spec.modelo or get("DMR_EMBED_MODEL", default=DMR_EMBED_MODEL),
            base_url=spec.base_url or DMR_BASE_URL,
            batch_size=spec.batch_size,
        )

    if spec.proveedor is Provider.LOCAL_ST:
        from .embeddings import SentenceTransformersEmbeddings

        return SentenceTransformersEmbeddings(
            device=spec.device,
            batch_size=spec.batch_size,
        )

    raise ProviderConfigError(f"Proveedor de embeddings no soportado: {spec.proveedor.value}")


def list_models(spec: ProviderSpec) -> list[str]:
    """IDs de modelo disponibles. El ítem 4 construye su registro sobre esto."""
    spec = spec.resuelto()
    if not spec.capacidades.listado_modelos:
        return []

    if spec.proveedor is Provider.DMR:
        import httpx

        r = httpx.get(f"{spec.base_url}/models", timeout=5.0)
        r.raise_for_status()
        return [m["id"] for m in r.json().get("data", [])]

    return []


def prefijos_de(backend: Any) -> tuple[str, str]:
    """(prefijo_documento, prefijo_consulta) del backend dado.

    Lo consulta el índice para no volver a fijar `prefix=""` a ciegas. Un backend puede
    declararlos por su cuenta; si no, se deducen de las capacidades del proveedor.
    """
    doc = getattr(backend, "prefijo_documento", None)
    qry = getattr(backend, "prefijo_consulta", None)
    if doc is not None and qry is not None:
        return doc, qry

    from .embeddings import SentenceTransformersEmbeddings

    if isinstance(backend, SentenceTransformersEmbeddings):
        caps = CAPACIDADES[Provider.LOCAL_ST]
        return caps.prefijo_documento, caps.prefijo_consulta
    return "", ""

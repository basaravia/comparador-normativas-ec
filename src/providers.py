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

import logging
import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .config import (
    DMR_BASE_URL,
    RERANKER_MODEL,
    DMR_EMBED_MODEL,
    DMR_LLM_MODEL,
    EMBED_BATCH_SIZE,
    LLM_MAX_TOKENS,
    LLM_TEMPERATURE,
    VERTEX_EMBED_LOCATION,
    VERTEX_EMBED_MODEL,
    VERTEX_LLM_MODEL,
    VERTEX_LOCATION,
    VERTEX_PROJECT_ID,
)
from .errors import ProviderConfigError
from .settings import faltantes, get

logger = logging.getLogger(__name__)


class Provider(str, Enum):
    """Proveedores soportados.

    Solo hay dos porque solo hay dos implementados. Las entradas de nube se añaden en la
    Fase 3, cuando exista una suscripción contra la que verificarlas: declararlas ahora
    sería prometer un camino que nadie ha recorrido.
    """

    # Endpoint que habla la API de OpenAI. Cubre el backend local (sin autenticación)
    # y cualquier servicio compatible con credencial — entre ellos los endpoints
    # serverless de Azure AI Foundry, que exponen esa misma interfaz. Lo único que
    # cambia entre uno y otro es `base_url` y `api_key`, así que no necesitan cliente
    # distinto: separarlos en dos proveedores duplicaría la fábrica sin motivo.
    OPENAI_COMPAT = "openai_compat"

    # Alias histórico del anterior. Se conserva porque `config.py`, la UI y el
    # `.env.example` lo nombran; apunta a la misma fábrica.
    DMR = "openai_compat"

    # Vertex AI (Gemini) para chat. Añadido en la rama Linux: la Fase 3 de la que habla
    # el docstring del módulo llegó antes por necesidad de hardware que por calendario
    # — sin backend local viable para el LLM de análisis (ver config.py), se adelantó
    # el primer proveedor de nube, ya con auth propia (ADC vía
    # GOOGLE_APPLICATION_CREDENTIALS) en vez de la del openai-compat de arriba.
    VERTEX = "vertex"

    LOCAL_ST = "local_st"    # sentence-transformers en proceso
    RERANK_LOCAL = "rerank_local"      # CrossEncoder en proceso
    RERANK_HTTP = "rerank_http"        # endpoint de reranking remoto

    # Docling en proceso (layout + OCR nativo del SO). La Fase 3 evalúa Azure AI
    # Document Intelligence para el mismo rol de parser/OCR.
    DOCLING_LOCAL = "docling_local"

    # FAISS en memoria. La Fase 3 evalúa Azure AI Search para el mismo rol de
    # vector store.
    FAISS_LOCAL = "faiss_local"


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
    Provider.VERTEX: ProviderCapabilities(
        chat=True,
        # Opción validada (ver VERTEX_EMBED_* en config.py), no el default — Ollama
        # sigue siéndolo. Misma auth (ADC) que el chat, por eso comparten Provider.
        embeddings=True,
        listado_modelos=False,  # sin endpoint de listado homogéneo; preflight no valida
        requiere_env=("GOOGLE_APPLICATION_CREDENTIALS",),
        # Nube, no backend local secuencial: el docstring del módulo ya anticipaba que
        # esto se invertiría (timeout más corto, reintentos con backoff) al llegar el
        # primer proveedor de nube.
        concurrencia_recomendada=4,
        timeout_s=60,
        max_retries=2,
    ),
    Provider.RERANK_LOCAL: ProviderCapabilities(
        chat=False,
        embeddings=False,
        listado_modelos=False,
        concurrencia_recomendada=1,
    ),
    Provider.RERANK_HTTP: ProviderCapabilities(
        chat=False,
        embeddings=False,
        listado_modelos=False,
        concurrencia_recomendada=4,
        timeout_s=30,
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
    Provider.DOCLING_LOCAL: ProviderCapabilities(
        chat=False,
        embeddings=False,
        listado_modelos=False,
        concurrencia_recomendada=1,
    ),
    Provider.FAISS_LOCAL: ProviderCapabilities(
        chat=False,
        embeddings=False,
        listado_modelos=False,
        concurrencia_recomendada=1,
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
    # Credencial del endpoint. None = se resuelve desde el entorno con `clave_env`.
    # Nunca se escribe en config.py ni se hornea en la imagen del contenedor: es lo
    # que permite apuntar el mismo cliente a un backend local sin autenticación o a
    # un endpoint remoto con token, cambiando solo el entorno.
    api_key: str | None = None
    clave_env: str = "LLM_API_KEY"
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
                api_key=get(self.clave_env, ui=self.api_key, default=""),
                clave_env=self.clave_env,
                timeout_s=self.timeout_s,
                max_retries=self.max_retries,
                extra=self.extra,
            )
        if self.proveedor is Provider.VERTEX:
            # Sin api_key: Vertex autentica con ADC (Application Default Credentials),
            # resuelta por la librería a partir de GOOGLE_APPLICATION_CREDENTIALS — no
            # hay credencial estática que pasar por `api_key` como en el openai-compat.
            return ProviderSpec(
                proveedor=self.proveedor,
                modelo=get("VERTEX_LLM_MODEL", ui=self.modelo, default=VERTEX_LLM_MODEL),
                base_url=self.base_url,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                batch_size=self.batch_size,
                device=self.device,
                api_key=self.api_key,
                clave_env=self.clave_env,
                timeout_s=self.timeout_s,
                max_retries=self.max_retries,
                extra={
                    "project": get("VERTEX_PROJECT_ID", default=VERTEX_PROJECT_ID),
                    "location": get("VERTEX_LOCATION", default=VERTEX_LOCATION),
                    **self.extra,
                },
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
            # "ignored" solo como último recurso: un backend local no autentica, pero
            # uno remoto sí, y hornear la credencial aquí era justo lo que impedía
            # apuntar a otro endpoint sin tocar código.
            api_key=spec.api_key or "ignored",
            temperature=spec.temperature,
            max_tokens=spec.max_tokens,
            timeout=spec.timeout_efectivo,
            max_retries=spec.reintentos_efectivos,
        )

    if spec.proveedor is Provider.VERTEX:
        from langchain_google_vertexai import ChatVertexAI

        return ChatVertexAI(
            model=spec.modelo,
            project=spec.extra["project"],
            location=spec.extra["location"],
            temperature=spec.temperature,
            max_output_tokens=spec.max_tokens,
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
            model=spec.modelo or get("EMBED_MODEL", default=DMR_EMBED_MODEL),
            base_url=get("EMBED_BASE_URL", ui=spec.base_url, default=DMR_BASE_URL),
            api_key=get("EMBED_API_KEY", ui=spec.api_key, default="") or "ignored",
            batch_size=spec.batch_size,
        )

    if spec.proveedor is Provider.LOCAL_ST:
        from .embeddings import SentenceTransformersEmbeddings

        return SentenceTransformersEmbeddings(
            device=spec.device,
            batch_size=spec.batch_size,
        )

    if spec.proveedor is Provider.VERTEX:
        # Resuelve modelo/región por su cuenta, sin apoyarse en lo que `resuelto()`
        # ya dejó en `spec.modelo`/`spec.extra`: eso está calibrado para chat
        # (VERTEX_LLM_MODEL, location="global") y aquí el par correcto es otro —
        # VERTEX_EMBED_MODEL, location="us-central1" (ver el gotcha en config.py).
        # Mezclar los dos apuntaría el cliente de embeddings al modelo o la región
        # del LLM.
        from langchain_google_vertexai import VertexAIEmbeddings

        from .embeddings import LangChainEmbeddingsAdapter

        modelo = get("VERTEX_EMBED_MODEL", default=VERTEX_EMBED_MODEL)
        embedder = VertexAIEmbeddings(
            model_name=modelo,
            project=get("VERTEX_PROJECT_ID", default=VERTEX_PROJECT_ID),
            location=get("VERTEX_EMBED_LOCATION", default=VERTEX_EMBED_LOCATION),
        )
        return LangChainEmbeddingsAdapter(
            embedder, batch_size=spec.batch_size, nombre_modelo=modelo,
        )

    raise ProviderConfigError(f"Proveedor de embeddings no soportado: {spec.proveedor.value}")


def build_reranker(spec: ProviderSpec) -> Any:
    """Construye el reranker. Tercera costura, junto a chat y embeddings.

    Antes esto vivía dentro de `NormativaIndex.__init__`, que importaba torch y
    sentence-transformers y descargaba ~1.2 GB de pesos **solo por construir un índice**.
    Dos consecuencias que esta costura corrige:

      · no se podía usar un reranker remoto ni ninguno en absoluto sin pagar la carga
        del local;
      · en la Fase 2 esa dependencia engorda el contenedor en varios GB para reordenar
        tres candidatos. Con el reranker fuera, la imagen de producción puede no llevar
        torch en absoluto.

    Enmienda el supuesto S9 del plan ("el reranker sigue siendo local con cualquier
    proveedor"), escrito cuando ningún candidato de nube exponía reranking de forma
    homogénea. Hoy sí los hay servibles por endpoint.

    Devuelve un callable `(query, documentos) -> list[float]`.
    """
    spec = spec.resuelto()

    if spec.proveedor is Provider.RERANK_HTTP:
        validate(spec)
        return _reranker_http(spec)

    return _reranker_local(spec)


def _reranker_local(spec: ProviderSpec):
    """CrossEncoder en proceso. Import perezoso: arrastra torch."""
    import torch
    from sentence_transformers import CrossEncoder

    # Antes solo distinguía "mps"/"cpu": en Linux con CUDA disponible, "auto" caía
    # siempre a CPU y el reranker (~1.2GB, cabe de sobra en 4GB de VRAM) nunca tocaba
    # la GPU. `resolve_device` ya sabe distinguir mps/cuda/cpu — se reutiliza en vez de
    # duplicar la lógica una segunda vez con el mismo bug.
    device = resolve_device(spec.device)

    model_kwargs = {"dtype": torch.float32}
    if device == "mps":
        # Qwen3-Reranker produce NaN en MPS con el kernel de atención optimizado
        # (SDPA); "eager" evita ese bug de precisión.
        model_kwargs["attn_implementation"] = "eager"

    modelo = spec.modelo or RERANKER_MODEL
    logger.info("Cargando reranker local: %s (device=%s)", modelo, device)
    encoder = CrossEncoder(modelo, device=device, model_kwargs=model_kwargs)

    def puntuar(query: str, documentos: list[str]) -> list[float]:
        return [float(x) for x in encoder.predict([(query, d) for d in documentos])]

    return puntuar


def _reranker_http(spec: ProviderSpec):
    """Endpoint de reranking remoto. Sin dependencias pesadas en el proceso."""
    import httpx

    url = f"{spec.base_url.rstrip('/')}/rerank"
    cabeceras = {"Authorization": f"Bearer {spec.api_key}"} if spec.api_key else {}

    def puntuar(query: str, documentos: list[str]) -> list[float]:
        r = httpx.post(
            url,
            json={"model": spec.modelo, "query": query, "documents": documentos},
            headers=cabeceras,
            timeout=spec.timeout_efectivo,
        )
        r.raise_for_status()
        datos = r.json().get("results", [])
        # La respuesta viene ordenada por relevancia; se devuelve en el orden de
        # entrada para que el llamador no tenga que saber cómo puntúa el proveedor.
        puntos = [0.0] * len(documentos)
        for item in datos:
            puntos[item["index"]] = float(item.get("relevance_score", 0.0))
        return puntos

    return puntuar


def resolve_device(device: str) -> str:
    """Resuelve 'auto' → mps/cuda/cpu según el hardware disponible.

    `torch.cuda.is_available()` solo confirma que hay un driver NVIDIA funcional; no
    dice si el *wheel* de PyTorch instalado trae kernels compilados para la compute
    capability de esa GPU en concreto. Los wheels oficiales recientes (torch>=2.9, p.ej.)
    dejaron de compilar para Maxwell (sm_50 — GTX 960M entre otras): `is_available()`
    sigue devolviendo True y el fallo real solo aparece a mitad de un forward pass, como
    "CUDA error: no kernel image is available for execution on the device" (visto en
    esta máquina al cargar el reranker). `_cuda_utilizable` cierra ese hueco.
    """
    if device != "auto":
        return device
    try:
        import torch
        if torch.backends.mps.is_available():
            return "mps"
        if torch.cuda.is_available() and _cuda_utilizable():
            return "cuda"
    except ImportError:
        pass
    return "cpu"


def _cuda_utilizable() -> bool:
    """True si el wheel de torch instalado trae kernels para la GPU presente.

    Exige coincidencia exacta con `torch.cuda.get_arch_list()` a propósito: un cubin
    compilado para sm_80 no está garantizado a ejecutar en sm_86 sin el PTX de reserva
    (no siempre embebido), y adivinar "compatible" aquí es exactamente el tipo de
    optimismo que produjo el fallo que esta función existe para evitar.
    """
    import torch

    try:
        major, minor = torch.cuda.get_device_capability()
    except Exception:
        return False

    return f"sm_{major}{minor}" in torch.cuda.get_arch_list()


def _build_pdf_pipeline_options(device: str, do_ocr: bool, table_mode: str = "accurate"):
    """Opciones de pipeline PDF de Docling (layout + tablas + OCR nativo).

    En macOS usa OcrMacOptions (Vision del SO) → sin modelos que descargar.
    ``table_mode`` = "accurate" (por defecto) o "fast" (más estable en sesiones largas)."""
    from docling.datamodel.pipeline_options import (
        PdfPipelineOptions,
        TableFormerMode,
        AcceleratorOptions,
        AcceleratorDevice,
    )

    device_map = {
        "mps": AcceleratorDevice.MPS,
        "cuda": AcceleratorDevice.CUDA,
        "cpu": AcceleratorDevice.CPU,
        "auto": AcceleratorDevice.AUTO,
    }
    device_enum = device_map.get(device, AcceleratorDevice.AUTO)
    tf_mode = TableFormerMode.FAST if table_mode == "fast" else TableFormerMode.ACCURATE

    opts = PdfPipelineOptions()
    opts.do_table_structure = True
    opts.table_structure_options.mode = tf_mode
    opts.accelerator_options = AcceleratorOptions(num_threads=4, device=device_enum)

    if do_ocr and sys.platform == "darwin":
        try:
            from docling.datamodel.pipeline_options import OcrMacOptions
            opts.do_ocr = True
            opts.ocr_options = OcrMacOptions(force_full_page_ocr=False)
        except ImportError:
            opts.do_ocr = True
    else:
        opts.do_ocr = do_ocr
    return opts


def build_document_converter(spec: ProviderSpec) -> Any:
    """Construye el conversor de documentos (PDF → texto/markdown). Cuarta costura,
    junto a chat, embeddings y reranker.

    Antes `NormativaParser` y `ManualParser` instanciaban `DocumentConverter` de Docling
    cada uno por su cuenta. La Fase 3 evalúa Azure AI Document Intelligence para el mismo
    rol de parser/OCR; esta costura es donde entra sin tocar los parsers.

    ``spec.extra`` transporta lo que el pipeline de Docling necesita y que no tiene
    hueco propio en `ProviderSpec`: ``do_ocr`` (bool) y ``table_mode``
    ("accurate"/"fast") — cada parser calibra el suyo.
    """
    spec = spec.resuelto()
    if spec.proveedor is not Provider.DOCLING_LOCAL:
        raise ProviderConfigError(f"Proveedor de parser no soportado: {spec.proveedor.value}")

    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.datamodel.base_models import InputFormat

    device = resolve_device(spec.device)
    do_ocr = bool(spec.extra.get("do_ocr", True))
    table_mode = spec.extra.get("table_mode", "accurate")
    opts = _build_pdf_pipeline_options(device, do_ocr, table_mode)
    return DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})


def build_vector_store(spec: ProviderSpec, dim: int) -> Any:
    """Construye el índice vectorial. Quinta costura, junto a chat, embeddings,
    reranker y parser.

    Antes `NormativaIndex` y `ManualIndex` instanciaban `faiss.IndexFlatIP` cada uno por
    su cuenta. La Fase 3 evalúa Azure AI Search para el mismo rol de vector store; esta
    costura es donde entra sin tocar los índices.
    """
    spec = spec.resuelto()
    if spec.proveedor is not Provider.FAISS_LOCAL:
        raise ProviderConfigError(f"Proveedor de vector store no soportado: {spec.proveedor.value}")

    import faiss

    return faiss.IndexFlatIP(dim)


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

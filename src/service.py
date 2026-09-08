"""Orquestación del pipeline, sin depender de ninguna interfaz.

Hasta ahora esto vivía dentro de `streamlit_app.py`: qué backend construir, cómo armar el
grader y el comparador, y el flujo entre las cuatro pestañas. Mientras la única interfaz
fuese Streamlit no molestaba; en cuanto haya una API HTTP delante, ese código no se puede
llamar sin arrastrar `st.*` — y la alternativa sería reimplementarlo, con dos versiones
que se desincronizan.

Este módulo es la costura que hace que la Fase 2 escriba **presentación** y no lógica
(supuesto S10 del plan). Streamlit y, más adelante, FastAPI son dos consumidores del
mismo servicio.

**Sin estado, por decisión de diseño.** Ninguna función guarda nada entre llamadas: los
DataFrames y el índice entran y salen por parámetro, y quien llama decide dónde vivirán
—`st.session_state` hoy, un almacén en disco cuando la Fase 2 lo necesite—. La
consecuencia práctica es que el índice FAISS hay que pasarlo, no reconstruirlo, porque es
lo caro del pipeline. Las firmas están pensadas para que añadir persistencia después no
obligue a tocar a los llamadores.

Lo que **no** vive aquí: el ciclo de vida de las corridas —arrancar en segundo plano,
consultar progreso, cancelar, reanudar—. Eso es `app/run_manager.py`, ítems 2 y 3, y se
apoyará sobre estas operaciones.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field, replace as _replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

import pandas as pd

from .comparator import DocumentComparator
from .config import (
    DOCLING_MAX_TOKENS,
    EMBED_BATCH_SIZE,
    FAISS_TOP_K,
    LLM_GRADER_MAX_TOKENS,
    LLM_MAX_TOKENS,
    LLM_TEMPERATURE,
    MAX_WORKERS,
    MIN_SEMANTIC_SCORE,
    GROQ_BASE_URL,
    OPENROUTER_BASE_URL,
    RERANKER_MODEL,
    RERANKER_TOP_N,
)
from .document_parser import ManualParser, NormativaParser
from .llm_grader import LLMGrader
from .providers import Provider, ProviderSpec, build_chat_model, build_embedding_backend
from .search_engine import NormativaIndex
from .settings import get as _get_setting

logger = logging.getLogger(__name__)

RAIZ_SALIDA = Path("output")


# ── Configuración ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ServiceConfig:
    """Parámetros de una corrida.

    Sustituye al `dict` suelto que la UI venía pasando. Un dict no falla al escribir mal
    una clave: devuelve `None` o lanza `KeyError` en mitad de una corrida de horas. Como
    dataclass, un nombre equivocado es un `TypeError` inmediato — y en la Fase 2 es el
    modelo del que FastAPI deriva su esquema de petición.
    """

    # Modelos
    llm_model: str | None = None
    embed_model: str | None = None
    base_url: str | None = None
    embed_backend_kind: str = "remoto"        # "remoto" | "local" | "vertex"
    llm_backend_kind: str = "vertex"          # "vertex" | "openrouter" | "groq"
    llm_base_url: str | None = None
    llm_api_key: str | None = None

    # Búsqueda
    faiss_top_k: int = FAISS_TOP_K
    reranker_top_n: int = RERANKER_TOP_N
    min_semantic_score: float = MIN_SEMANTIC_SCORE
    use_reranker: bool = True
    reranker_model: str = RERANKER_MODEL

    # LLM
    temperature: float = LLM_TEMPERATURE
    llm_max_tokens: int = LLM_MAX_TOKENS
    grader_max_tokens: int = LLM_GRADER_MAX_TOKENS

    # Procesamiento
    device: str = "cpu"
    do_ocr: bool = True
    docling_max_tokens: int = DOCLING_MAX_TOKENS
    embed_batch_size: int = EMBED_BATCH_SIZE
    max_workers: int = MAX_WORKERS

    extra: dict = field(default_factory=dict)

    @classmethod
    def desde_dict(cls, d: dict) -> ServiceConfig:
        """Construye desde el dict que produce la barra lateral.

        Puente para no reescribir la UI de golpe. Ignora las claves que no reconoce en
        vez de fallar: la barra lateral produce algunas que son solo de presentación.
        """
        campos = {f for f in cls.__dataclass_fields__ if f != "extra"}
        conocidas = {k: v for k, v in d.items() if k in campos}
        # Nombres que la UI usa con otro nombre.
        if "dmr_base_url" in d:
            conocidas.setdefault("base_url", d["dmr_base_url"])
        if d.get("embed_backend_kind", "").startswith("Local"):
            conocidas["embed_backend_kind"] = "local"
        elif d.get("embed_backend_kind", "").startswith("Vertex"):
            conocidas["embed_backend_kind"] = "vertex"
        elif "embed_backend_kind" in d:
            conocidas["embed_backend_kind"] = "remoto"
        if d.get("llm_backend_kind", "").startswith("OpenRouter"):
            conocidas["llm_backend_kind"] = "openrouter"
        elif d.get("llm_backend_kind", "").startswith("Groq"):
            conocidas["llm_backend_kind"] = "groq"
        elif "llm_backend_kind" in d:
            conocidas["llm_backend_kind"] = "vertex"
        return cls(**conocidas, extra={k: v for k, v in d.items() if k not in campos})


# ── Rutas por corrida ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RunPaths:
    """Dónde escribe una corrida concreta.

    Cada corrida tiene su directorio. Antes todo iba a rutas fijas
    (`output/comparador/reporte_comparacion.xlsx`), así que dos corridas se pisaban el
    reporte y no había forma de saber cuál produjo qué — inaceptable en un papel de
    trabajo de auditoría, donde la trazabilidad es el punto (§3.3.2 del plan).

    `workspace` está previsto pero hoy siempre vale el sentinela "local" (single-tenant):
    cuando haya varios usuarios (Fase 3), pasar otro valor y escribir a
    `output/workspaces/<ws>/runs/<run_id>/` es rellenar este parámetro, no un refactor.
    """

    run_id: str
    raiz: Path = RAIZ_SALIDA
    workspace: str = "local"

    @property
    def directorio(self) -> Path:
        base = self.raiz / "workspaces" / self.workspace if self.workspace != "local" else self.raiz
        return base / "runs" / self.run_id

    @property
    def excel(self) -> Path:
        return self.directorio / "reporte_comparacion.xlsx"

    @property
    def json(self) -> Path:
        return self.directorio / "reporte_comparacion.json"

    @property
    def indice(self) -> Path:
        return self.directorio / "faiss_index"

    @property
    def manifest(self) -> Path:
        return self.directorio / "manifest.json"

    def crear(self) -> RunPaths:
        self.directorio.mkdir(parents=True, exist_ok=True)
        return self


def nuevo_run_id() -> str:
    """Identificador ordenable por tiempo y único.

    El prefijo temporal hace que `ls` los liste en orden cronológico, que es como se
    buscan cuando hay que revisar una corrida concreta.
    """
    return f"{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}"


# ── Operaciones ───────────────────────────────────────────────────────────────

def construir_backend_embeddings(config: ServiceConfig):
    """Backend de embeddings según la configuración. Delega en `providers`."""
    if config.embed_backend_kind == "local":
        spec = ProviderSpec(proveedor=Provider.LOCAL_ST, device=config.device,
                            batch_size=config.embed_batch_size)
    elif config.embed_backend_kind == "vertex":
        spec = ProviderSpec(proveedor=Provider.VERTEX, batch_size=config.embed_batch_size)
    else:
        spec = ProviderSpec(proveedor=Provider.OPENAI_COMPAT, modelo=config.embed_model,
                            base_url=config.base_url, batch_size=config.embed_batch_size)
    logger.info("Backend de embeddings: %s", spec.proveedor.value)
    return build_embedding_backend(spec)


def tabular(
    normativa_pdfs: Iterable[Path],
    manual_pdfs: Iterable[Path],
    config: ServiceConfig,
    *,
    on_file: Optional[Callable[[str, str], None]] = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fase 1 — PDFs a DataFrames.

    `on_file(tipo, nombre)` se invoca antes de cada archivo para que la interfaz muestre
    progreso sin que este módulo sepa nada de ella.
    """
    normativa_parser = NormativaParser(
        device=config.device, do_ocr=config.do_ocr, cache_dir="output/docling",
    )
    frames = []
    for pdf in normativa_pdfs:
        if on_file:
            on_file("normativa", pdf.name)
        df = normativa_parser.parse_pdf(pdf)
        logger.info("Normativa %s: %d elementos", pdf.name, len(df))
        frames.append(df)
    normativa_df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    manual_parser = ManualParser(max_tokens=config.docling_max_tokens, device=config.device)
    mframes = []
    for pdf in manual_pdfs:
        if on_file:
            on_file("manual", pdf.name)
        df = manual_parser.parse_pdf(pdf)
        logger.info("Manual %s: %d chunks", pdf.name, len(df))
        mframes.append(df)
    manual_df = pd.concat(mframes, ignore_index=True) if mframes else pd.DataFrame()

    return normativa_df, manual_df


def construir_indice(normativa_df: pd.DataFrame, config: ServiceConfig) -> NormativaIndex:
    """Fase 2 — índice FAISS sobre la normativa.

    Devuelve el índice; **no lo guarda**. Quien llama decide dónde vive: es lo caro del
    pipeline y reconstruirlo en cada operación no sería viable.
    """
    backend = construir_backend_embeddings(config)
    indice = NormativaIndex(
        embedding_backend=backend,
        use_reranker=config.use_reranker,
        reranker_model=config.reranker_model,
    )
    indice.build(normativa_df, text_col="embed_text")
    return indice


def construir_comparador(indice: NormativaIndex, config: ServiceConfig) -> DocumentComparator:
    """Arma el grader y el comparador. Único sitio donde se cablean sus parámetros.

    El LLM de análisis va por `Provider.VERTEX` por defecto, no por la firma clásica
    (`model=`/`base_url=`) de `LLMGrader`: esa firma construye siempre un cliente
    `Provider.DMR` (openai-compat), y por defecto el LLM no vive ahí — vive en Vertex
    AI, con su propia auth (ADC). `config.llm_model=None` deja que `ProviderSpec.resuelto()`
    resuelva `VERTEX_LLM_MODEL` desde entorno/default, igual que ya hacía para DMR.

    `llm_backend_kind` en {"openrouter", "groq"} reutiliza el mismo `Provider.DMR`
    (openai-compat genérico) que ya usan los embeddings locales — ambos exponen la
    API de OpenAI, solo cambian `base_url`/`api_key`. No hace falta un Provider nuevo
    por cada uno.

    Con Groq, si además hay `OPENROUTER_API_KEY`/`OPENROUTER_LLM_MODEL` en el
    entorno, se arma un respaldo automático vía `.with_fallbacks()` de LangChain:
    una llamada que falla contra Groq (rate limit, error transitorio del
    proveedor — verificado en vivo el 2026-09-08) reintenta sola contra
    OpenRouter antes de abortar la corrida. Sin esas credenciales, sigue siendo
    Groq solo, como hasta ahora — nadie tiene que pedirlo explícito.
    """
    respaldo_spec = None
    if config.llm_backend_kind in ("openrouter", "groq"):
        es_groq = config.llm_backend_kind == "groq"
        spec = ProviderSpec(
            proveedor=Provider.DMR,
            modelo=config.llm_model,
            base_url=config.llm_base_url or (GROQ_BASE_URL if es_groq else OPENROUTER_BASE_URL),
            temperature=config.temperature,
            api_key=config.llm_api_key,
            clave_env="GROQ_API_KEY" if es_groq else "OPENROUTER_API_KEY",
        )
        if es_groq:
            respaldo_key = _get_setting("OPENROUTER_API_KEY", default="")
            respaldo_modelo = _get_setting("OPENROUTER_LLM_MODEL", default="")
            if respaldo_key and respaldo_modelo:
                respaldo_spec = ProviderSpec(
                    proveedor=Provider.DMR, modelo=respaldo_modelo, base_url=OPENROUTER_BASE_URL,
                    temperature=config.temperature, api_key=respaldo_key, clave_env="OPENROUTER_API_KEY",
                )
    else:
        spec = ProviderSpec(
            proveedor=Provider.VERTEX,
            modelo=config.llm_model,
            temperature=config.temperature,
        )

    if respaldo_spec is not None:
        primario = spec.resuelto()
        respaldo = respaldo_spec.resuelto()
        grader = LLMGrader(
            chat_grader=build_chat_model(_replace(primario, max_tokens=config.grader_max_tokens))
                .with_fallbacks([build_chat_model(_replace(respaldo, max_tokens=config.grader_max_tokens))]),
            chat_analyst=build_chat_model(_replace(primario, max_tokens=config.llm_max_tokens))
                .with_fallbacks([build_chat_model(_replace(respaldo, max_tokens=config.llm_max_tokens))]),
            max_tokens=config.llm_max_tokens,
            grader_max_tokens=config.grader_max_tokens,
        )
    else:
        grader = LLMGrader(
            spec=spec,
            max_tokens=config.llm_max_tokens,
            grader_max_tokens=config.grader_max_tokens,
        )
    return DocumentComparator(
        normativa_index=indice,
        llm_grader=grader,
        top_k_faiss=config.faiss_top_k,
        top_n_rerank=config.reranker_top_n,
        min_semantic_score=config.min_semantic_score,
    )


def comparar(
    indice: NormativaIndex,
    manual_df: pd.DataFrame,
    normativa_df: pd.DataFrame,
    config: ServiceConfig,
    *,
    progress_callback: Optional[Callable[[int, int, dict], None]] = None,
    desc: str = "Comparando",
    checkpoint: Any | None = None,
    cancelar: Any | None = None,
) -> pd.DataFrame:
    """Fases 3-5 — grading y análisis comparativo.

    Propaga `RunAbortedError` tal cual: quien llama decide qué hacer con los parciales
    que la excepción trae consigo. Tragarla aquí volvería a ocultar una corrida
    incompleta, que es justo el defecto del ítem 1.
    """
    comparador = construir_comparador(indice, config)
    return comparador.run(
        manual_df=manual_df,
        normativa_df=normativa_df,
        max_workers=config.max_workers,
        desc=desc,
        progress_callback=progress_callback,
        checkpoint=checkpoint,
        cancelar=cancelar,
    )


def exportar(
    results_df: pd.DataFrame,
    rutas: RunPaths,
    indice: NormativaIndex | None = None,
    bundle: Any | None = None,
    run_scope: Any | None = None,
    metadatos: dict[str, Any] | None = None,
) -> dict[str, Path]:
    """Fase 5 — entregables de la corrida en su propio directorio.

    Si se proporciona un `bundle` (corrida en doble vía), genera el Papel de Trabajo
    completo de 6 hojas gobernado por `templates/papel_trabajo.yaml` (ítem 9).
    Si no, genera el reporte en Excel tradicional conservando total compatibilidad.
    """
    rutas.crear()
    generados: dict[str, Path] = {}

    if bundle is not None:
        from .papel_trabajo import generar_papel_trabajo
        meta = metadatos or {"run_id": rutas.run_id, "workspace_id": rutas.workspace}
        generados["excel"] = generar_papel_trabajo(
            bundle, rutas.excel, run_scope=run_scope, metadatos=meta
        )
    else:
        generados["excel"] = DocumentComparator.export_excel(results_df, rutas.excel)

    rutas.json.write_text(
        results_df.to_json(orient="records", force_ascii=False, indent=2),
        encoding="utf-8",
    )
    generados["json"] = rutas.json

    if indice is not None:
        indice.save(rutas.indice)
        generados["indice"] = rutas.indice

    logger.info("Corrida %s exportada en %s", rutas.run_id, rutas.directorio)
    return generados


def construir_indice_manual(
    manual_df: pd.DataFrame,
    config: ServiceConfig,
):
    """Construye el índice semántico sobre las secciones del manual (para Vía 2).

    Antes instanciaba `search_engine.NormativaIndex` — la clase de la Vía 1 ("¿qué
    normativa aplica a esta sección?"), no la de la Vía 2 ("¿alguna sección cubre este
    artículo?"). Esa segunda pregunta es la que resuelve `manual_index.ManualIndex`
    (ver su docstring: existe justo para no heredar de `NormativaIndex` lo que no
    aplica). Además pasaba `config.vector_store_spec`, un campo que `ServiceConfig`
    nunca declaró — `AttributeError` inmediato en cualquier corrida en modo dual.
    `construir_indice()` (Vía 1, arriba) tampoco pasa vector_store_spec explícito;
    se mantiene la misma convención aquí, dejando que `ManualIndex` use su default
    (`Provider.FAISS_LOCAL`).
    """
    backend = construir_backend_embeddings(config)
    from .manual_index import ManualIndex
    indice = ManualIndex(backend)
    col = "embed_text" if "embed_text" in manual_df.columns else "texto"
    indice.build(manual_df, text_col=col)
    return indice


def comparar_dual(
    indice_normativa: NormativaIndex,
    indice_manual: Any,
    manual_df: pd.DataFrame,
    normativa_df: pd.DataFrame,
    config: ServiceConfig,
    *,
    workspace_id: str = "local",
    min_score: float = 0.30,
    top_k: int = 5,
    incluir_referencias: bool = False,
    progress_callback: Optional[Callable[[str, int, int], None]] = None,
):
    """Orquesta el análisis en doble vía (Vía 1 + Vía 2) del ítem 6."""
    from .dual import run_dual
    comparador = construir_comparador(indice_normativa, config)
    return run_dual(
        comparador=comparador,
        manual_index=indice_manual,
        manual_df=manual_df,
        normativa_df=normativa_df,
        workspace_id=workspace_id,
        top_k=top_k,
        min_score=min_score,
        incluir_referencias=incluir_referencias,
        progress_callback=progress_callback,
    )

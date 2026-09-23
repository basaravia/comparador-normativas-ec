"""Router de estado de salud y catálogo de proveedores de modelos (DMR/Ollama, Vertex).
"""
from __future__ import annotations

import os
import platform
from fastapi import APIRouter

from api.schemas import HealthResponse, PerfilActivo, ProviderInfo, ProvidersResponse
from src import config as cfg
from src.errors import ProviderConfigError
from src.model_registry import modelos_disponibles
from src.perfiles import perfil_activo
from src.providers import Provider, ProviderSpec, resolve_device
from src.service import ServiceConfig
from src.settings import get as get_setting

router = APIRouter(prefix="/api", tags=["Sistema y Proveedores"])


@router.get("/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    """Verifica la operatividad del servicio y plataforma."""
    # `resolve_device()`, no una detección propia: antes esto miraba solo
    # CUDA_VISIBLE_DEVICES/platform.system(), la misma heurística que
    # providers._cuda_utilizable() existe justo para no usar — is_available()/la
    # presencia de la variable de entorno no dice si el wheel de torch instalado
    # trae kernels para la GPU presente (ver el docstring de resolve_device, y el
    # caso real de esta máquina: GTX 960M, sm_50, wheels recientes sin soporte).
    device = resolve_device("auto")
    return HealthResponse(
        status="ok",
        version="4.0.0",
        device=device,
        platform=platform.system().lower(),
    )


@router.get("/config/providers", response_model=ProvidersResponse)
def get_providers() -> ProvidersResponse:
    """Retorna los proveedores disponibles con aceleración GPU local y remota.

    Azure AI Foundry va por `Provider.AZURE` (`AzureChatOpenAI` / `AzureOpenAIEmbeddings`).
    Aquí solo se informa si sus variables FOUNDRY_AI_* están definidas: no se llama al
    recurso, así que "disponible" no garantiza que el endpoint responda.
    """
    # Mismo chequeo que usa el resto del pipeline (providers.list_models vía
    # model_registry), no un GET a mano con su propio timeout y base_url —
    # duplicarlo aquí es exactamente lo que puede hacer que la API y el pipeline
    # disientan sobre si Ollama está arriba.
    ollama_ok = bool(modelos_disponibles(ProviderSpec(proveedor=Provider.DMR, base_url=cfg.DMR_BASE_URL)))

    # Chequeo de Vertex AI
    vertex_ok = bool(os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or os.getenv("VERTEX_PROJECT_ID"))

    # Groq y OpenRouter (LLM openai-compat, ver src/service.py::construir_comparador):
    # esta ruta no los listaba en absoluto hasta ahora, aunque `src/config.py` ya trae
    # GROQ_BASE_URL/OPENROUTER_BASE_URL y streamlit_app.py ya deja elegirlos desde el
    # sidebar — la SPA no tenía forma de saber que existían. `get_setting()`, no
    # `os.getenv()` a mano: sigue la misma precedencia UI > env > .env > default que
    # usa `construir_comparador()` para armar el backend real, así esta ruta no le
    # miente a quién consulte el catálogo sobre una clave que sí está en `.env`.
    groq_ok = bool(get_setting("GROQ_API_KEY", default=""))
    openrouter_ok = bool(get_setting("OPENROUTER_API_KEY", default=""))

    # Con estas cuatro variables `build_chat_model` puede construir el cliente de Azure.
    foundry_faltan = [v for v in ("FOUNDRY_AI_ENDPOINT", "FOUNDRY_AI_TOKEN",
                                  "FOUNDRY_AI_API_VERSION", "FOUNDRY_AI_DEPLOYMENT")
                      if not get_setting(v, default="")]

    providers = [
        ProviderInfo(
            id="ollama_dmr",
            nombre="Ollama / Docker Model Runner (Local GPU)",
            disponible=ollama_ok,
            tipo="embedding / llm",
            detalles=f"Endpoint: {cfg.DMR_BASE_URL}",
        ),
        ProviderInfo(
            id=Provider.VERTEX.value,
            nombre="GCP Vertex AI (Gemini)",
            disponible=vertex_ok,
            tipo="llm / embedding",
            detalles=f"Proyecto: {cfg.VERTEX_PROJECT_ID or 'No configurado'}",
        ),
        ProviderInfo(
            id="groq",
            nombre="Groq (LLM gratuito, hardware propio)",
            disponible=groq_ok,
            tipo="llm",
            detalles=(
                f"Modelo: {get_setting('GROQ_LLM_MODEL', default=cfg.GROQ_LLM_MODEL) or 'sin configurar'}"
                if groq_ok else "Falta GROQ_API_KEY"
            ),
        ),
        ProviderInfo(
            id="openrouter",
            nombre="OpenRouter (LLM gratuito, agregador)",
            disponible=openrouter_ok,
            tipo="llm",
            detalles=(
                f"Modelo: {get_setting('OPENROUTER_LLM_MODEL', default=cfg.OPENROUTER_LLM_MODEL) or 'sin configurar'}"
                if openrouter_ok else "Falta OPENROUTER_API_KEY"
            ),
        ),
        ProviderInfo(
            id="foundry",
            nombre="Azure AI Foundry (cuenta propia)",
            disponible=not foundry_faltan,
            tipo="llm / embedding",
            detalles=(
                f"Deployment: {get_setting('FOUNDRY_AI_DEPLOYMENT', default='')}"
                if not foundry_faltan else f"Faltan: {', '.join(foundry_faltan)}"
            ),
        ),
        ProviderInfo(
            id="sentence_transformers",
            nombre="Local Transformers (CPU / MPS / CUDA)",
            disponible=True,
            tipo="embedding / reranker",
            detalles="Ejecución local en proceso",
        ),
    ]

    perfil, perfil_error = None, None
    try:
        p = perfil_activo()
        efectivo = ServiceConfig()  # aplica LLM_BACKEND / EMBED_BACKEND sobre el perfil
        perfil = PerfilActivo(
            nombre=p.nombre,
            llm=efectivo.llm_backend_kind,
            embeddings=efectivo.embed_backend_kind,
            con_override=(efectivo.llm_backend_kind != p.llm
                          or efectivo.embed_backend_kind != p.embeddings),
        )
    except ProviderConfigError as e:
        perfil_error = str(e)

    return ProvidersResponse(
        providers=providers,
        perfil=perfil,
        perfil_error=perfil_error,
        default_llm=getattr(cfg, "VERTEX_LLM_MODEL", "gemini-3.5-flash-lite"),
        default_embed=getattr(cfg, "OLLAMA_EMBED_MODEL", "qwen3-embedding:0.6b"),
    )

"""Router de estado de salud y catálogo de proveedores de modelos (DMR/Ollama, Vertex).
"""
from __future__ import annotations

import os
import platform
from fastapi import APIRouter

from api.schemas import HealthResponse, ProviderInfo, ProvidersResponse
from src import config as cfg
from src.model_registry import modelos_disponibles
from src.providers import Provider, ProviderSpec, resolve_device

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

    No hay entrada de Azure AI Foundry: `src/providers.py` (Provider enum) no lo
    declara a propósito todavía ("declararlas ahora sería prometer un camino que
    nadie ha recorrido" — no hay suscripción contra la que verificarlo). Esta ruta
    reportaba antes un `azure_ai_foundry` disponible con solo mirar variables de
    entorno, sin que exista ningún `Provider.AZURE` ni fábrica en
    `build_chat_model`/`build_embedding_backend` — seleccionarlo en cualquier punto
    del pipeline habría lanzado `ProviderConfigError` de inmediato. La API no debe
    prometer una capacidad que el backend no puede construir.
    """
    # Mismo chequeo que usa el resto del pipeline (providers.list_models vía
    # model_registry), no un GET a mano con su propio timeout y base_url —
    # duplicarlo aquí es exactamente lo que puede hacer que la API y el pipeline
    # disientan sobre si Ollama está arriba.
    ollama_ok = bool(modelos_disponibles(ProviderSpec(proveedor=Provider.DMR, base_url=cfg.DMR_BASE_URL)))

    # Chequeo de Vertex AI
    vertex_ok = bool(os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or os.getenv("VERTEX_PROJECT_ID"))

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
            id="sentence_transformers",
            nombre="Local Transformers (CPU / MPS / CUDA)",
            disponible=True,
            tipo="embedding / reranker",
            detalles="Ejecución local en proceso",
        ),
    ]

    return ProvidersResponse(
        providers=providers,
        default_llm=getattr(cfg, "VERTEX_LLM_MODEL", "gemini-3.5-flash-lite"),
        default_embed=getattr(cfg, "OLLAMA_EMBED_MODEL", "qwen3-embedding:0.6b"),
    )

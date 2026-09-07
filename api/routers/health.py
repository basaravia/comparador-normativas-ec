"""Router de estado de salud y catálogo de proveedores de modelos (DMR, Ollama, Vertex, Azure AI Foundry).
"""
from __future__ import annotations

import os
import platform
import httpx
from fastapi import APIRouter

from api.schemas import HealthResponse, ProviderInfo, ProvidersResponse
from src import config as cfg
from src.providers import Provider

router = APIRouter(prefix="/api", tags=["Sistema y Proveedores"])


@router.get("/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    """Verifica la operatividad del servicio y plataforma."""
    device = "cuda" if os.environ.get("CUDA_VISIBLE_DEVICES") else ("mps" if platform.system() == "Darwin" else "cpu")
    return HealthResponse(
        status="ok",
        version="4.0.0",
        device=device,
        platform=platform.system().lower(),
    )


@router.get("/config/providers", response_model=ProvidersResponse)
def get_providers() -> ProvidersResponse:
    """Retorna los proveedores disponibles con aceleración GPU local y remota."""
    # Chequeo rápido de Ollama
    ollama_ok = False
    try:
        r = httpx.get(f"{cfg.DMR_BASE_URL.rstrip('/')}/models", timeout=0.8)
        ollama_ok = (r.status_code == 200)
    except Exception:
        ollama_ok = False

    # Chequeo de Vertex AI
    vertex_ok = bool(os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or os.getenv("VERTEX_PROJECT_ID"))

    # Chequeo de Azure AI Foundry
    azure_ok = bool(os.getenv("AZURE_OPENAI_ENDPOINT") and os.getenv("AZURE_OPENAI_API_KEY"))

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
            nombre="GCP Vertex AI (Gemini 2.5 / 1.5)",
            disponible=vertex_ok,
            tipo="llm",
            detalles=f"Proyecto: {cfg.VERTEX_PROJECT_ID or 'No configurado'}",
        ),
        ProviderInfo(
            id="azure_ai_foundry",
            nombre="Azure AI Foundry (OpenAI Models)",
            disponible=azure_ok,
            tipo="llm / embedding",
            detalles=f"Endpoint: {os.getenv('AZURE_OPENAI_ENDPOINT', 'No configurado')}",
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

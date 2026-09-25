"""Esquemas Pydantic para el contrato OpenAPI de la API REST de Comparador de Normativas.
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "4.0.0"
    device: str = "cpu"
    platform: str = "linux"


class ProviderInfo(BaseModel):
    id: str
    nombre: str
    disponible: bool
    tipo: str  # llm | embedding | reranker
    detalles: str = ""


class PerfilActivo(BaseModel):
    """Perfil de modelos vigente (config/perfiles.yaml) y los backends efectivos."""
    nombre: str
    llm: str
    embeddings: str
    # True si LLM_BACKEND / EMBED_BACKEND fuerzan un eje distinto al del perfil.
    con_override: bool = False


class ProvidersResponse(BaseModel):
    providers: List[ProviderInfo]
    default_llm: str
    default_embed: str
    perfil: Optional[PerfilActivo] = None
    # Si el perfil no se pudo resolver (YAML inválido, perfil inexistente…), el motivo.
    perfil_error: Optional[str] = None


class DocumentItem(BaseModel):
    id: str
    nombre: str
    tipo: str  # normativa | manual
    size_bytes: int
    elementos_parseados: int = 0
    tiene_pdf: bool = True


class DocumentsListResponse(BaseModel):
    normativas: List[DocumentItem]
    manuales: List[DocumentItem]
    # Si hay un volumen de Unity Catalog configurado y no se pudo leer, el motivo.
    aviso_volumen: Optional[str] = None


class TabulateRequest(BaseModel):
    normativas: List[str] = Field(default_factory=list)
    manuales: List[str] = Field(default_factory=list)
    do_ocr: bool = False


class TabulateResponse(BaseModel):
    status: str
    normativa_elementos: int
    manual_secciones: int
    elapsed_seconds: float


class IndexBuildRequest(BaseModel):
    use_chunking: bool = True
    max_tokens: int = 512
    solape: int = 50


class IndexBuildResponse(BaseModel):
    status: str
    total_vectores: int
    usar_chunking: bool
    elapsed_seconds: float


class SearchQueryRequest(BaseModel):
    query: str
    top_k: int = 5
    min_score: float = 0.30
    use_reranker: bool = True


class SearchResultItem(BaseModel):
    element_id: str
    numero: str
    encabezado: str
    contenido: str
    score: float
    doc_id: str


class SearchQueryResponse(BaseModel):
    query: str
    results: List[SearchResultItem]


class RunScopeModel(BaseModel):
    articulos: List[str] = Field(default_factory=list)
    secciones: List[str] = Field(default_factory=list)
    doc_ids_normativa: List[str] = Field(default_factory=list)
    preset_articulos: Optional[str] = None
    muestra_n: Optional[int] = None
    muestra_aleatoria: bool = False


class StartCompareRequest(BaseModel):
    dual_mode: bool = True
    scope: Optional[RunScopeModel] = None
    min_score: float = 0.30
    top_k: int = 5
    llm_model: Optional[str] = None
    embed_model: Optional[str] = None
    # Antes de esto, `start_compare()` los recibía pero los ignoraba por completo: la
    # corrida vía API siempre corría con `ServiceConfig()` por defecto (Vertex), sin
    # importar lo que este campo llevara. Streamlit ya puede elegir Groq/OpenRouter
    # desde el sidebar (ver streamlit_app.py) desde que se agregó ese backend — la API
    # nunca conectó el mismo interruptor. Valores canónicos, no las etiquetas de
    # presentación del sidebar ('Groq (gratis)'): quien llame a la API no tiene por
    # qué conocerlas, y así lo valida además el propio esquema OpenAPI.
    llm_backend_kind: Optional[Literal["vertex", "openrouter", "groq", "foundry"]] = None


class StartCompareResponse(BaseModel):
    run_id: str
    status: str
    stream_url: str


class RunStatusResponse(BaseModel):
    run_id: str
    estado: str  # pendiente | corriendo | completado | cancelado | fallido
    progreso: int
    total: int
    porcentaje: float
    etiqueta: str = ""
    # Motivo cuando estado == "fallido" (`RunHandle.error`). Antes esta respuesta no
    # tenía este campo en absoluto: un consumidor de la API (la SPA, un script) veía
    # "fallido" sin ninguna pista de la causa, mientras la misma corrida vía
    # Streamlit sí mostraba el error completo con st.error() — dos superficies del
    # mismo backend con visibilidad distinta del mismo fallo.
    error: Optional[str] = None
    cobertura_global: Optional[float] = None
    alerta_cobertura: Optional[str] = None
    # Las tres categorías de la Vía 2 van por separado. `cobertura_global` cuenta como
    # cubierto solo lo que el veredicto de adopción declaró cubierto, así que un
    # artículo `parcial` no está ni en el numerador ni en `articulos_sin_cobertura`:
    # sin su propia lista desaparecería de la vista del consumidor, que es la manera
    # más silenciosa de subestimar la brecha.
    articulos_sin_cobertura: List[Dict[str, Any]] = Field(default_factory=list)
    articulos_parciales: List[Dict[str, Any]] = Field(default_factory=list)
    articulos_no_aplican: List[Dict[str, Any]] = Field(default_factory=list)
    vista_manual: List[Dict[str, Any]] = Field(default_factory=list)
    vista_normativa: List[Dict[str, Any]] = Field(default_factory=list)
    motivos_revision: List[str] = Field(default_factory=list)
    total_revision_manual: int = 0


# ── Autenticación ─────────────────────────────────────────────────────────


class LoginRequest(BaseModel):
    username: str = Field(..., description="Usuario autorizado (AUTH_USERNAME).")
    password: str = Field(..., description="Contraseña asociada (AUTH_PASSWORD).")


class LoginResponse(BaseModel):
    ok: bool = True
    usuario: str
    expira_en: int = Field(..., description="Vigencia de la sesión en segundos.")


class LogoutResponse(BaseModel):
    ok: bool = True
    mensaje: str = "Sesión cerrada."


class SessionResponse(BaseModel):
    autenticado: bool
    usuario: str = ""
    expira_en: Optional[int] = Field(None, description="Marca de tiempo Unix de expiración.")
    auth_habilitada: bool = True

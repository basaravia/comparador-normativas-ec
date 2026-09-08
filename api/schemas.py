"""Esquemas Pydantic para el contrato OpenAPI de la API REST de Comparador de Normativas.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
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


class ProvidersResponse(BaseModel):
    providers: List[ProviderInfo]
    default_llm: str
    default_embed: str


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
    articulos_sin_cobertura: List[Dict[str, Any]] = Field(default_factory=list)
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

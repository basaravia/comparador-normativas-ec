"""Aplicación principal FastAPI para el Comparador Automatizado de Normativas vs Manuales Internos.

Expone endpoints REST y SSE, contratos OpenAPI / Swagger UI interactivos en `/docs`,
ReDoc en `/redoc`, especificación JSON en `/openapi.json` y colección Postman en `/api/postman.json`.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from api.routers import auth, compare, documents, health, index, theme
from api.security import SesionRequerida, obtener_sesion, require_session

logger = logging.getLogger("api")

API_DESCRIPTION = """
# 📑 Comparador Automatizado de Normativas vs Manuales Internos — API REST

Bienvenido a la API del **Pipeline de Análisis de Cumplimiento Normativo Bancario** (SBS, BCE, SEPS, UAF)
frente a manuales internos de entidades financieras.

## 🔐 Autenticación

Toda la API (salvo `/api/health`, `/api/theme/tokens` y `/api/auth/*`) exige una **sesión activa**.

1. `POST /api/auth/login` con `{"username": "...", "password": "..."}` emite la cookie firmada
   `auth_session` (HttpOnly, `SameSite=Lax`), que el navegador reenvía sola en las llamadas
   posteriores —incluidos el streaming SSE y el visor de PDF—.
2. `GET /api/auth/me` valida la sesión vigente; `POST /api/auth/logout` la revoca.
3. Las credenciales se configuran en `.env` con `AUTH_USERNAME` y `AUTH_PASSWORD`.

`/docs`, `/redoc` y `/openapi.json` también quedan detrás de la sesión: sin ella, `/docs` y
`/redoc` redirigen a la pantalla de acceso y `/openapi.json` responde 401.

## 🚀 Flujo de Trabajo Diario (Workflow en 4 Pasos)

1. **Documentos (`/api/documents`)**:
   - Subir o consultar normativas y manuales en PDF.
   - Tabular con Docling mediante `POST /api/documents/tabular`.
   - Visualizar PDFs en alta fidelidad y streaming con `GET /api/documents/{tipo}/{doc_id}/pdf`.
2. **Índice Semántico (`/api/index`)**:
   - Construir el índice FAISS vectorial con chunking semántico parent-child (`POST /api/index/build`).
   - Probar similitud y reranking con `POST /api/index/search`.
3. **Comparación y Alcance (`/api/compare`)**:
   - Configurar el alcance con `RunScope` y lanzar análisis en doble vía (`POST /api/compare/start`).
   - Monitorear el progreso en tiempo real mediante Server-Sent Events (SSE) en `GET /api/compare/stream/{run_id}`.
4. **Resultados y Entregables (`/api/compare/runs`)**:
   - Consultar la Cobertura Global, hallazgos, alertas y motivos de revisión manual (`GET /api/compare/runs/{run_id}`).
   - Descargar el **Papel de Trabajo de Auditoría en Excel** de 6 hojas (`GET /api/compare/runs/{run_id}/export/excel`).

## 🛠️ Herramientas de Integración

- **Swagger UI Interactivo**: Pruebe cada endpoint directamente desde el navegador en [`/docs`](/docs).
- **ReDoc Documentación**: Visualización de especificación completa en [`/redoc`](/redoc).
- **Contrato OpenAPI 3.1**: Descargue el esquema estándar en [`/openapi.json`](/openapi.json) para importar en Swagger Editor.
- **Colección Postman**: Descargue la colección lista para usar en [`/api/postman.json`](/api/postman.json).
"""

app = FastAPI(
    title="Comparador de Normativas — API REST & SSE",
    version="4.0.0",
    description=API_DESCRIPTION,
    # Sin rutas automáticas: `/docs`, `/redoc` y `/openapi.json` se registran más abajo
    # envueltos en la verificación de sesión (ver `docs_*` / `openapi_protegido`).
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

# CORS habilitado para clientes web, iPad y móviles
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Inclusión de routers modulares.
# Públicos: salud, tokens de diseño y el propio login (la SPA los necesita para
# poder pintar la pantalla de acceso). El resto exige sesión válida.
app.include_router(health.router)
app.include_router(theme.router)
app.include_router(auth.router)
app.include_router(documents.router, dependencies=[SesionRequerida])
app.include_router(index.router, dependencies=[SesionRequerida])
app.include_router(compare.router, dependencies=[SesionRequerida])


# ── Documentación interactiva protegida ───────────────────────────────────
# `/docs` y `/redoc` los abre una persona en el navegador: redirigir a la SPA
# (que muestra el login) es más útil que un 401 en crudo. `/openapi.json` lo
# consume Swagger UI y herramientas, así que ahí sí corresponde el 401.

OPENAPI_URL = "/openapi.json"


def _redirigir_a_login(request: Request, destino: str) -> RedirectResponse | None:
    """None si hay sesión; si no, redirección a la SPA con el destino a retomar."""
    if obtener_sesion(request) is not None:
        return None
    return RedirectResponse(url=f"/?next={destino}", status_code=302)


@app.get("/docs", include_in_schema=False)
def docs_swagger(request: Request):
    """Swagger UI interactivo; requiere sesión activa."""
    redireccion = _redirigir_a_login(request, "/docs")
    if redireccion is not None:
        return redireccion
    return get_swagger_ui_html(openapi_url=OPENAPI_URL, title=f"{app.title} — Swagger UI")


@app.get("/redoc", include_in_schema=False)
def docs_redoc(request: Request):
    """Documentación ReDoc; requiere sesión activa."""
    redireccion = _redirigir_a_login(request, "/redoc")
    if redireccion is not None:
        return redireccion
    return get_redoc_html(openapi_url=OPENAPI_URL, title=f"{app.title} — ReDoc")


@app.get(OPENAPI_URL, include_in_schema=False)
def openapi_protegido(_: dict = Depends(require_session)) -> Dict[str, Any]:
    """Contrato OpenAPI 3.1; responde 401 sin sesión."""
    return app.openapi()


@app.get("/api/postman.json", tags=["Sistema y Proveedores"], dependencies=[SesionRequerida])
def get_postman_collection(request: Request) -> Dict[str, Any]:
    """Genera y descarga la colección Postman v2.1 para importar directamente en Postman."""
    base_url = str(request.base_url).rstrip("/")
    openapi = app.openapi()

    items = []
    for path, methods in openapi.get("paths", {}).items():
        for method, op in methods.items():
            if method.upper() not in ("GET", "POST", "PUT", "DELETE", "PATCH"):
                continue
            name = op.get("summary") or f"{method.upper()} {path}"
            tag = (op.get("tags") or ["General"])[0]

            item = {
                "name": f"[{tag}] {name}",
                "request": {
                    "method": method.upper(),
                    "header": [
                        {"key": "Accept", "value": "application/json"},
                        {"key": "Content-Type", "value": "application/json"},
                    ],
                    "url": {
                        "raw": f"{base_url}{path}",
                        "protocol": request.url.scheme,
                        "host": [request.url.hostname],
                        "port": str(request.url.port or ("443" if request.url.scheme == "https" else "80")),
                        "path": [p for p in path.strip("/").split("/") if p],
                    },
                    "description": op.get("description", ""),
                },
            }
            items.append(item)

    return {
        "info": {
            "name": "Comparador de Normativas vs Manuales API",
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
            "description": "Colección completa para pruebas y automatización de la API de cumplimiento normativo.",
            "version": "4.0.0",
        },
        "item": items,
    }


# Montar estáticos del frontend Vue si el directorio existe (dist compilado)
FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")

"""Aplicación principal FastAPI para el Comparador Automatizado de Normativas vs Manuales Internos.

Expone endpoints REST y SSE, contratos OpenAPI / Swagger UI interactivos en `/docs`,
ReDoc en `/redoc`, especificación JSON en `/openapi.json` y colección Postman en `/api/postman.json`.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from api.routers import compare, documents, health, index, theme

logger = logging.getLogger("api")

API_DESCRIPTION = """
# 📑 Comparador Automatizado de Normativas vs Manuales Internos — API REST

Bienvenido a la API del **Pipeline de Análisis de Cumplimiento Normativo Bancario** (SBS, BCE, SEPS, UAF)
frente a manuales internos de entidades financieras.

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
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# CORS habilitado para clientes web, iPad y móviles
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Inclusión de routers modulares
app.include_router(health.router)
app.include_router(documents.router)
app.include_router(index.router)
app.include_router(compare.router)
app.include_router(theme.router)


@app.get("/api/postman.json", tags=["Sistema y Proveedores"])
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

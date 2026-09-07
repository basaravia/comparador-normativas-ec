"""Router para la gestión y servicio de documentos PDF y tabulación.
"""
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse

from api.schemas import DocumentItem, DocumentsListResponse, TabulateRequest, TabulateResponse
from src import service

router = APIRouter(prefix="/api/documents", tags=["Documentos"])

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
NORMATIVA_DIR = REPO_ROOT / "Normativa2026"
MANUAL_DIR = REPO_ROOT / "document_test"
UPLOAD_NORMATIVA_DIR = REPO_ROOT / "output" / "uploads" / "normativas"
UPLOAD_MANUAL_DIR = REPO_ROOT / "output" / "uploads" / "manuales"

# Almacén en memoria de DataFrames tabulados
_CACHE: dict[str, Any] = {
    "normativa_df": None,
    "manual_df": None,
    "normativa_index": None,
}


def get_document_cache() -> dict[str, Any]:
    return _CACHE


def _buscar_pdf(tipo: str, doc_id: str) -> Optional[Path]:
    directorios = [NORMATIVA_DIR, UPLOAD_NORMATIVA_DIR] if tipo == "normativa" else [MANUAL_DIR, UPLOAD_MANUAL_DIR]
    nombre = doc_id if doc_id.endswith(".pdf") else f"{doc_id}.pdf"
    for d in directorios:
        p = d / nombre
        if p.exists():
            return p
    return None


@router.get("", response_model=DocumentsListResponse)
def list_documents() -> DocumentsListResponse:
    """Lista todos los PDFs disponibles en las carpetas base y de subidas."""
    normativas: list[DocumentItem] = []
    manuales: list[DocumentItem] = []

    for d in [NORMATIVA_DIR, UPLOAD_NORMATIVA_DIR]:
        if d.exists():
            for f in sorted(d.glob("*.pdf")):
                normativas.append(
                    DocumentItem(
                        id=f.name,
                        nombre=f.stem,
                        tipo="normativa",
                        size_bytes=f.stat().st_size,
                        tiene_pdf=True,
                    )
                )

    for d in [MANUAL_DIR, UPLOAD_MANUAL_DIR]:
        if d.exists():
            for f in sorted(d.glob("*.pdf")):
                manuales.append(
                    DocumentItem(
                        id=f.name,
                        nombre=f.stem,
                        tipo="manual",
                        size_bytes=f.stat().st_size,
                        tiene_pdf=True,
                    )
                )

    return DocumentsListResponse(normativas=normativas, manuales=manuales)


@router.get("/{tipo}/{doc_id}/pdf")
def get_document_pdf(tipo: str, doc_id: str):
    """Entrega el archivo PDF binario para renderizado en PDF.js con soporte de byte-ranges."""
    ruta = _buscar_pdf(tipo, doc_id)
    if not ruta or not ruta.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Documento {doc_id} no encontrado en {tipo}",
        )

    return FileResponse(
        path=ruta,
        media_type="application/pdf",
        filename=ruta.name,
        headers={"Accept-Ranges": "bytes"},
    )


@router.post("/upload")
async def upload_document(tipo: str, file: UploadFile = File(...)):
    """Sube un documento PDF al almacenamiento de uploads."""
    if not file.filename or not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Solo se permiten archivos .pdf")

    destino_dir = UPLOAD_NORMATIVA_DIR if tipo == "normativa" else UPLOAD_MANUAL_DIR
    destino_dir.mkdir(parents=True, exist_ok=True)
    destino_path = destino_dir / file.filename

    with open(destino_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    return {
        "status": "ok",
        "id": file.filename,
        "size_bytes": destino_path.stat().st_size,
    }


@router.post("/tabular", response_model=TabulateResponse)
def tabulate_documents(req: TabulateRequest) -> TabulateResponse:
    """Ejecuta la tabulación de documentos mediante Docling."""
    normativa_paths = [_buscar_pdf("normativa", d) for d in req.normativas]
    manual_paths = [_buscar_pdf("manual", d) for d in req.manuales]

    normativa_paths = [p for p in normativa_paths if p]
    manual_paths = [p for p in manual_paths if p]

    if not normativa_paths or not manual_paths:
        raise HTTPException(
            status_code=400,
            detail="Se requiere al menos un archivo normativo y un manual existente",
        )

    t0 = time.time()
    cfg = service.ServiceConfig(do_ocr=req.do_ocr)
    n_df, m_df = service.tabular(normativa_paths, manual_paths, cfg)

    _CACHE["normativa_df"] = n_df
    _CACHE["manual_df"] = m_df
    _CACHE["normativa_index"] = None

    return TabulateResponse(
        status="ok",
        normativa_elementos=len(n_df),
        manual_secciones=len(m_df),
        elapsed_seconds=round(time.time() - t0, 2),
    )

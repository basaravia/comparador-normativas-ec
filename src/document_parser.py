"""Phase 1: Tabulación de documentos — PDF → DataFrame estructurado.

NormativaParser : MarkItDown + regex  → artículos, disposiciones, anexos
ManualParser    : Docling HybridChunker → secciones semánticas con jerarquía
"""
from __future__ import annotations

import re
import logging
import sys
from pathlib import Path
from typing import Optional

import pandas as pd

from .config import DOCLING_MAX_TOKENS

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Patrones regex para documentos normativos ecuatorianos (del notebook 01)
# ──────────────────────────────────────────────────────────────────────────────
_PAT_ART = re.compile(
    r'(?:^|\n)(?:#{1,4}[ \t]+|[-*+][ \t]+|\d+\.[ \t]+)?[ \t]{0,6}'
    r'Art(?:ículo|iculo|\.)[ \t]+(\d+[\w]*)[ \t]*[.\-–—]?[ \t]*([^\n]{0,250})',
    re.MULTILINE | re.IGNORECASE,
)
_PAT_JERARQUIA = re.compile(
    r'(?:^|\n)(?:#{1,4}[ \t]+)?[ \t]{0,4}'
    r'(TÍTULO|CAPÍTULO|SECCIÓN|Título|Capítulo|Sección)[ \t]+'
    r'([IVXLCDM\d]+|PRIMERO|SEGUNDO|TERCERO|CUARTO|QUINTO|'
    r'SEXTO|SÉPTIMO|OCTAVO|NOVENO|DÉCIMO|ÚNICO)'
    r'[ \t]*[.\-]?[ \t]*\n?([^\n]{0,300})',
    re.MULTILINE,
)
_PAT_DISP = re.compile(
    r'(?:^|\n)[ \t]{0,4}'
    r'(DISPOSICIÓN(?:ES)?[ \t]+(?:TRANSITORIA|GENERAL|FINAL|DEROGATORIA|REFORMATORIA|SUSTITUTIVA)S?)',
    re.MULTILINE | re.IGNORECASE,
)
_PAT_RESOL = re.compile(
    r'(?:^|\n)[ \t]{0,4}(CONSIDERANDO|RESUELVE|CERTIFICA|DISPONE)[ \t]*:',
    re.MULTILINE,
)
_PAT_ANEXO = re.compile(
    r'(?:^|\n)[ \t]{0,4}(ANEXO[ \t]+(?:[IVXLCDM]+|\d+|Único|ÚNICO))'
    r'[ \t]*[.\-]?[ \t]*\n?([^\n]{0,400})',
    re.MULTILINE | re.IGNORECASE,
)
_PAT_FECHA = re.compile(
    r'\b(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})\b', re.IGNORECASE
)
_MESES = {
    'enero': '01', 'febrero': '02', 'marzo': '03', 'abril': '04',
    'mayo': '05', 'junio': '06', 'julio': '07', 'agosto': '08',
    'septiembre': '09', 'octubre': '10', 'noviembre': '11', 'diciembre': '12',
}
_PAT_TIPO_NORMA = re.compile(
    r'(LEY\s+ORGÁNICA|LEY\s+ORDINARIA|DECRETO\s+EJECUTIVO|REGLAMENTO|'
    r'RESOLUCIÓN|CIRCULAR|NORMA\s+TÉCNICA)',
    re.IGNORECASE,
)


class NormativaParser:
    """Parsea normativas ecuatorianas (PDF → DataFrame via MarkItDown + regex).

    Cada fila del DataFrame resultante es un artículo, disposición o anexo.
    Columnas de salida:
        element_id, doc_id, tipo_norma, titulo_norma, fecha,
        numero, encabezado, contenido, seccion, tipo_elemento,
        posicion, embed_text
    """

    def __init__(self) -> None:
        from markitdown import MarkItDown
        self._md = MarkItDown()

    def parse_pdf(self, pdf_path: str | Path) -> pd.DataFrame:
        """Parsea un PDF normativo y retorna un DataFrame estructurado."""
        pdf_path = Path(pdf_path)
        logger.info("Parseando normativa: %s", pdf_path.name)
        text = self._extract_text(pdf_path)
        records = self._parse_text(text, pdf_path.name)
        if not records:
            logger.warning("Sin artículos detectados en %s", pdf_path.name)
            return pd.DataFrame()
        df = pd.DataFrame(records)
        df["embed_text"] = df.apply(self._build_embed_text, axis=1)
        return df

    def parse_directory(self, directory: str | Path, pattern: str = "*.pdf") -> pd.DataFrame:
        """Parsea todos los PDFs en un directorio y concatena los resultados."""
        directory = Path(directory)
        pdfs = sorted(directory.glob(pattern))
        if not pdfs:
            logger.warning("No se encontraron PDFs en %s", directory)
            return pd.DataFrame()
        frames = []
        for p in pdfs:
            try:
                frames.append(self.parse_pdf(p))
            except Exception as e:
                logger.error("Error en %s: %s", p.name, e)
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    # ── Extracción de texto ───────────────────────────────────────────────

    def _extract_text(self, pdf_path: Path) -> str:
        result = self._md.convert(str(pdf_path))
        return result.text_content or ""

    # ── Parseo de texto ──────────────────────────────────────────────────

    def _parse_text(self, text: str, archivo: str) -> list[dict]:
        sections = self._extract_sections(text)
        fecha = self._extract_fecha(text)
        tipo_norma = self._extract_tipo_norma(text)
        titulo = next((ln.strip() for ln in text.split('\n') if ln.strip()), archivo)

        def _section_at(pos: int) -> str:
            active = [s[1] for s in sections if s[0] <= pos]
            return " > ".join(active[-3:]) if active else ""

        base = dict(doc_id=archivo, tipo_norma=tipo_norma,
                    titulo_norma=titulo[:200], fecha=fecha)

        records: list[dict] = []

        # Artículos
        art_matches = list(_PAT_ART.finditer(text))
        for i, m in enumerate(art_matches):
            numero = m.group(1)
            encabezado = m.group(2).strip()
            start = m.end()
            end = art_matches[i + 1].start() if i + 1 < len(art_matches) else len(text)
            contenido = text[start:end].strip()[:3000]
            records.append({
                **base,
                "numero": numero,
                "encabezado": encabezado[:250],
                "contenido": contenido,
                "seccion": _section_at(m.start()),
                "tipo_elemento": "articulo",
                "posicion": m.start(),
            })

        # Disposiciones
        for m in _PAT_DISP.finditer(text):
            label = m.group(1).strip()
            start = m.end()
            end = text.find('\n\n', start, start + 3000)
            contenido = text[start: end if end != -1 else start + 1500].strip()
            records.append({
                **base,
                "numero": label,
                "encabezado": label,
                "contenido": contenido[:3000],
                "seccion": _section_at(m.start()),
                "tipo_elemento": "disposicion",
                "posicion": m.start(),
            })

        # Anexos
        for m in _PAT_ANEXO.finditer(text):
            label = m.group(1).strip()
            titulo_anexo = m.group(2).strip() if m.group(2) else ""
            records.append({
                **base,
                "numero": label,
                "encabezado": titulo_anexo or label,
                "contenido": titulo_anexo,
                "seccion": _section_at(m.start()),
                "tipo_elemento": "anexo",
                "posicion": m.start(),
            })

        records.sort(key=lambda r: r["posicion"])
        for i, r in enumerate(records):
            r["element_id"] = f"{archivo}_{i:04d}"

        return records

    # ── Helpers privados ──────────────────────────────────────────────────

    def _extract_sections(self, text: str) -> list[tuple[int, str]]:
        sections = []
        for m in _PAT_JERARQUIA.finditer(text):
            kind, number, title = m.group(1), m.group(2), m.group(3).strip()
            label = f"{kind} {number}" + (f" — {title}" if title else "")
            sections.append((m.start(), label))
        return sections

    def _extract_fecha(self, text: str) -> str:
        for m in _PAT_FECHA.finditer(text[:3000]):
            mes = _MESES.get(m.group(2).lower(), "")
            if mes:
                return f"{m.group(3)}-{mes}-{m.group(1).zfill(2)}"
        return ""

    def _extract_tipo_norma(self, text: str) -> str:
        for m in _PAT_TIPO_NORMA.finditer(text[:1000]):
            return m.group(1).upper()
        return ""

    @staticmethod
    def _build_embed_text(row: pd.Series) -> str:
        parts = []
        if row["seccion"]:
            parts.append(row["seccion"])
        if row["tipo_elemento"] == "articulo":
            label = f"Artículo {row['numero']}"
        else:
            label = str(row["numero"])
        if row["encabezado"] and row["encabezado"] != row["numero"]:
            label += f": {row['encabezado']}"
        parts.append(label)
        if row["contenido"]:
            parts.append(str(row["contenido"])[:1200])
        return "\n".join(parts)


class ManualParser:
    """Parsea manuales internos bancarios (PDF → DataFrame via Docling HybridChunker).

    Utiliza análisis de layout ML + chunking semántico con preservación de jerarquía.
    Columnas de salida:
        chunk_id, doc_id, fuente, pagina_inicio, pagina_fin,
        jerarquia, titulo_seccion, texto, embed_text
    """

    def __init__(
        self,
        max_tokens: int = DOCLING_MAX_TOKENS,
        device: str = "auto",
    ) -> None:
        self.max_tokens = max_tokens
        self._device = self._resolve_device(device)

    def parse_pdf(self, pdf_path: str | Path) -> pd.DataFrame:
        """Parsea un manual PDF y retorna un DataFrame estructurado."""
        pdf_path = Path(pdf_path)
        logger.info("Parseando manual: %s (device=%s)", pdf_path.name, self._device)

        converter, chunker = self._build_pipeline()
        doc_result = converter.convert(str(pdf_path))
        chunks = list(chunker.chunk(doc_result.document))

        records = []
        for i, chunk in enumerate(chunks):
            headings = list(chunk.meta.headings) if chunk.meta.headings else []
            heading_path = " > ".join(headings) if headings else ""
            embed_text = (
                f"{heading_path}\n{chunk.text}".strip() if heading_path else chunk.text
            )
            page_no: Optional[int] = None
            if chunk.meta.page_info:
                page_no = chunk.meta.page_info.page_no

            records.append({
                "chunk_id": f"{pdf_path.stem}_{i:04d}",
                "doc_id": pdf_path.name,
                "fuente": pdf_path.name,
                "pagina_inicio": page_no,
                "pagina_fin": page_no,
                "jerarquia": heading_path,
                "titulo_seccion": headings[-1] if headings else "",
                "texto": chunk.text,
                "embed_text": embed_text,
            })

        df = pd.DataFrame(records)
        logger.info("Extraídos %d chunks de %s", len(df), pdf_path.name)
        return df

    def parse_directory(self, directory: str | Path, pattern: str = "*.pdf") -> pd.DataFrame:
        """Parsea todos los PDFs en un directorio."""
        directory = Path(directory)
        pdfs = sorted(directory.glob(pattern))
        frames = []
        for p in pdfs:
            try:
                frames.append(self.parse_pdf(p))
            except Exception as e:
                logger.error("Error en %s: %s", p.name, e)
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    # ── Pipeline Docling ──────────────────────────────────────────────────

    def _build_pipeline(self):
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import (
            PdfPipelineOptions,
            TableFormerMode,
            AcceleratorOptions,
            AcceleratorDevice,
        )
        from docling.chunking import HybridChunker

        device_map = {
            "mps": AcceleratorDevice.MPS,
            "cuda": AcceleratorDevice.CUDA,
            "cpu": AcceleratorDevice.CPU,
            "auto": AcceleratorDevice.AUTO,
        }
        device_enum = device_map.get(self._device, AcceleratorDevice.AUTO)

        opts = PdfPipelineOptions()
        opts.do_table_structure = True
        opts.table_structure_options.mode = TableFormerMode.ACCURATE
        opts.accelerator_options = AcceleratorOptions(num_threads=4, device=device_enum)

        if sys.platform == "darwin":
            try:
                from docling.datamodel.pipeline_options import OcrMacOptions
                opts.do_ocr = True
                opts.ocr_options = OcrMacOptions(force_full_page_ocr=False)
            except ImportError:
                opts.do_ocr = False
        else:
            opts.do_ocr = False

        converter = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
        )
        chunker = HybridChunker(max_tokens=self.max_tokens)
        return converter, chunker

    @staticmethod
    def _resolve_device(device: str) -> str:
        if device != "auto":
            return device
        try:
            import torch
            if torch.backends.mps.is_available():
                return "mps"
            if torch.cuda.is_available():
                return "cuda"
        except ImportError:
            pass
        return "cpu"

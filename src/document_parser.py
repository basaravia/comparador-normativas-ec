"""Phase 1: Tabulación de documentos — PDF → DataFrame estructurado.

NormativaParser : Docling (layout + OCR) + regex → artículos, disposiciones, anexos
ManualParser    : Docling HybridChunker → secciones semánticas con jerarquía
"""
from __future__ import annotations

import re
import logging
import sys
from collections import Counter
from pathlib import Path
from typing import Optional

import pandas as pd

from .config import DOCLING_MAX_TOKENS

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers Docling compartidos por NormativaParser y ManualParser
# ──────────────────────────────────────────────────────────────────────────────
def _resolve_device(device: str) -> str:
    """Resuelve 'auto' → mps/cuda/cpu según el hardware disponible."""
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


def _build_pdf_pipeline_options(device: str, do_ocr: bool, table_mode: str = "accurate"):
    """Opciones de pipeline PDF de Docling (layout + tablas + OCR nativo).

    En macOS usa OcrMacOptions (Vision del SO) → sin modelos que descargar.
    ``table_mode`` = "accurate" (por defecto) o "fast" (más estable en sesiones largas)."""
    from docling.datamodel.pipeline_options import (
        PdfPipelineOptions,
        TableFormerMode,
        AcceleratorOptions,
        AcceleratorDevice,
    )

    device_map = {
        "mps": AcceleratorDevice.MPS,
        "cuda": AcceleratorDevice.CUDA,
        "cpu": AcceleratorDevice.CPU,
        "auto": AcceleratorDevice.AUTO,
    }
    device_enum = device_map.get(device, AcceleratorDevice.AUTO)
    tf_mode = TableFormerMode.FAST if table_mode == "fast" else TableFormerMode.ACCURATE

    opts = PdfPipelineOptions()
    opts.do_table_structure = True
    opts.table_structure_options.mode = tf_mode
    opts.accelerator_options = AcceleratorOptions(num_threads=4, device=device_enum)

    if do_ocr and sys.platform == "darwin":
        try:
            from docling.datamodel.pipeline_options import OcrMacOptions
            opts.do_ocr = True
            opts.ocr_options = OcrMacOptions(force_full_page_ocr=False)
        except ImportError:
            opts.do_ocr = True
    else:
        opts.do_ocr = do_ocr
    return opts

# ──────────────────────────────────────────────────────────────────────────────
# Patrones regex para documentos normativos ecuatorianos (del notebook 01)
# ──────────────────────────────────────────────────────────────────────────────
# Ancla de artículo: solo hasta el número (incluye sufijos tipo "20-A").
# El encabezado/cuerpo se separan después con _PAT_HEADER_SPLIT.
_PAT_ART = re.compile(
    r'(?:^|\n)(?:#{1,4}[ \t]+|[-*+][ \t]+|\d+\.[ \t]+)?[ \t]{0,6}'
    r'Art(?:ículo|iculo|\.)[ \t]+(\d+(?:[ \t]*[-–][ \t]*[A-Za-z]+)?)',
    re.MULTILINE | re.IGNORECASE,
)
# Separa "<sep> EPÍGRAFE <sep> CUERPO". Tolera el estilo de Docling, que a veces
# pega el guión a la palabra ("1. -Objeto. -La") o lo omite ("Finalidad. Proteger").
# Señal del fin del epígrafe: un punto seguido (opcional guión) y CUERPO en mayúscula.
_PAT_HEADER = re.compile(
    r'^[ \t]*(?:[.:\-–—]+[ \t]*)*'      # separador inicial tras el número
    r'([^.\n]{2,90}?)'                  # epígrafe (sin punto interno)
    r'\.[ \t]*[-–—]?[ \t]*'            # separador: punto + guión opcional (pegado o no)
    r'(?=[A-ZÁÉÍÓÚÑ¿])(.+)$',          # el cuerpo empieza en mayúscula
    re.DOTALL,
)
# Aperturas de oración: si el "epígrafe" empieza así, es cuerpo, no un título.
_BODY_STARTERS = re.compile(
    r'^(esta|este|estos|estas|la|el|los|las|se|para|por|en|toda|todo|todos|todas|'
    r'ser[aá]n?|es|son|cr[eé]ase|cuando|sin|a[ \t]+fin|de[ \t]+acuerdo|'
    r'de[ \t]+conformidad|proteger|garantizar)\b',
    re.IGNORECASE,
)
# Contexto que delata una CITA a otra norma (no un artículo propio).
_PAT_REF_PRE = re.compile(
    r'\b(el|del|los|las|al|en|presente|mismo|citado|referido|dicho|este|esta)'
    r'[ \t]*$',
    re.IGNORECASE,
)
_PAT_REF_POST = re.compile(
    r'^[\s,.\d]*(?:n[uú]meral[\s\d,]*)?(?:de la|del)[ \t]+'
    r'(constituci|ley|c[oó]digo|reglamento|norma)',
    re.IGNORECASE,
)
# Líneas de artefacto (paginación, correos) a eliminar en la limpieza.
_PAT_FOOTER_LINE = re.compile(
    r'^\s*(?:\d{1,4}|\d{1,3}\s*/\s*\d{1,3}|[\w.+-]+@[\w.-]+\.\w+)\s*$'
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
    """Parsea normativas ecuatorianas (PDF → DataFrame via Docling + regex).

    Docling aporta análisis de layout (reflow de párrafos, orden de lectura,
    remoción de la mayoría de pies/cabeceras) y OCR nativo (ocrmac) para PDFs
    escaneados. El markdown resultante se cachea en ``cache_dir`` para que las
    re-ejecuciones no repitan la conversión (lenta). Un filtro de líneas
    repetidas elimina las cabeceras/pies que Docling deja pasar.

    Cada fila del DataFrame resultante es un artículo, disposición o anexo.
    Columnas de salida:
        orden, element_id, doc_id, tipo_norma, titulo_norma, fecha,
        numero, encabezado, contenido, seccion, tipo_elemento,
        tipo_bloque, es_referencia, posicion, embed_text

    tipo_bloque  : preambulo | articulado | disposicion | resolucion | anexo
    es_referencia: True si la fila es una cita a otra norma o vive en el
                   preámbulo (no es articulado propio) — útil para filtrar.
    """

    #: umbral bajo el cual se asume que la extracción sin OCR falló (escaneado)
    _MIN_CHARS = 200

    def __init__(
        self,
        device: str = "auto",
        do_ocr: bool = True,
        cache_dir: str | Path | None = "output/docling",
    ) -> None:
        self._device = _resolve_device(device)
        self._do_ocr = do_ocr
        self._cache_dir = Path(cache_dir) if cache_dir else None
        self._converter = None  # construido perezosamente en la 1ª conversión

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
        md = self._to_markdown(pdf_path)
        md = self._strip_repeated_lines(md)
        return self._clean_text(md)

    def _to_markdown(self, pdf_path: Path) -> str:
        """Convierte el PDF a markdown con Docling, usando caché en disco.

        No dispara descargas: reutiliza los modelos ya cacheados de Docling y
        el OCR nativo de macOS (ocrmac)."""
        cache = None
        if self._cache_dir:
            cache = self._cache_dir / f"{pdf_path.stem}.md"
            if cache.exists() and cache.stat().st_mtime >= pdf_path.stat().st_mtime:
                logger.info("Docling (caché): %s", cache.name)
                return cache.read_text(encoding="utf-8")

        converter = self._get_converter()
        result = converter.convert(str(pdf_path))
        md = result.document.export_to_markdown() or ""
        if len(md.strip()) < self._MIN_CHARS:
            logger.warning(
                "Extracción pobre en %s (%d chars); ¿PDF escaneado sin OCR?",
                pdf_path.name, len(md.strip()),
            )
        if cache is not None:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            cache.write_text(md, encoding="utf-8")
        return md

    def _get_converter(self):
        if self._converter is None:
            from docling.document_converter import DocumentConverter, PdfFormatOption
            from docling.datamodel.base_models import InputFormat
            opts = _build_pdf_pipeline_options(self._device, self._do_ocr)
            self._converter = DocumentConverter(
                format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
            )
        return self._converter

    @staticmethod
    def _strip_repeated_lines(text: str, min_repeats: int = 3, max_len: int = 90) -> str:
        """Elimina cabeceras/pies que Docling deja pasar: líneas cortas idénticas
        que se repiten en ≥N páginas (p.ej. 'ASAMBLEÍSTA POR LOJA', nombre del
        firmante). Genérico e independiente del idioma."""
        if not text:
            return ""
        lines = text.split("\n")

        def norm(s: str) -> str:
            return re.sub(r"\s+", " ", s.strip()).lower()

        counts = Counter(norm(ln) for ln in lines if ln.strip())
        repeated = {
            k for k, c in counts.items()
            if c >= min_repeats and 0 < len(k) <= max_len
        }
        return "\n".join(
            ln for ln in lines if not ln.strip() or norm(ln) not in repeated
        )

    @staticmethod
    def _clean_text(text: str) -> str:
        """Normaliza ruido residual: tabs, espacios repetidos y líneas de
        artefacto (paginación, correos). Preserva los saltos de párrafo."""
        if not text:
            return ""
        text = text.replace("\t", " ")
        kept = [
            ln for ln in text.split("\n")
            if not _PAT_FOOTER_LINE.match(ln)
        ]
        text = "\n".join(kept)
        # Colapsa corridas de espacios pero respeta los \n.
        text = re.sub(r"[ ]{2,}", " ", text)
        return text

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

        art_matches = list(_PAT_ART.finditer(text))
        block_at = self._build_block_resolver(text, art_matches)

        records: list[dict] = []

        # Artículos
        for i, m in enumerate(art_matches):
            numero = self._normalize_numero(m.group(1))
            start = m.end()
            end = art_matches[i + 1].start() if i + 1 < len(art_matches) else len(text)
            tail = text[start:end]
            encabezado, contenido = self._split_header_body(tail)
            bloque = block_at(m.start())
            es_ref = self._is_reference(text, m.start(), tail, bloque)
            records.append({
                **base,
                "numero": numero,
                "encabezado": encabezado[:250],
                "contenido": contenido[:3000],
                "seccion": _section_at(m.start()),
                "tipo_elemento": "articulo",
                "tipo_bloque": bloque,
                "es_referencia": es_ref,
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
                "tipo_bloque": "disposicion",
                "es_referencia": False,
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
                "tipo_bloque": "anexo",
                "es_referencia": False,
                "posicion": m.start(),
            })

        records.sort(key=lambda r: r["posicion"])
        self._flag_duplicate_articulos(records)
        for i, r in enumerate(records):
            r["orden"] = i
            r["element_id"] = f"{archivo}_{i:04d}"

        return records

    # ── Helpers privados ──────────────────────────────────────────────────

    @staticmethod
    def _normalize_numero(raw: str) -> str:
        """'20 - A' / '20–a' → '20-A';  '7' → '7'."""
        s = re.sub(r"[ \t]*[-–][ \t]*", "-", raw.strip())
        return s.upper()

    @staticmethod
    def _split_header_body(tail: str) -> tuple[str, str]:
        """Separa epígrafe y cuerpo. Un epígrafe válido es corto (≤12 palabras) y
        no es una apertura de oración; si no, se deja vacío y todo va al cuerpo."""
        m = _PAT_HEADER.match(tail)
        if m:
            head = m.group(1).strip(" .:-–—\t\n")
            if (2 <= len(head) and len(head.split()) <= 12
                    and not _BODY_STARTERS.match(head)):
                return head, m.group(2).strip()
        cleaned = re.sub(r"^[ \t]*[.:\-–—]+[ \t]*", "", tail).strip()
        return "", cleaned

    def _build_block_resolver(self, text: str, art_matches: list):
        """Devuelve una función pos → tipo_bloque
        (preambulo|articulado|disposicion|resolucion|anexo)."""
        ones = [m.start() for m in art_matches
                if self._normalize_numero(m.group(1)) == "1"]
        if ones:
            articulado_start = min(ones)
        elif art_matches:
            articulado_start = art_matches[0].start()
        else:
            articulado_start = len(text)

        boundaries: list[tuple[int, str]] = [(articulado_start, "articulado")]

        def _first_after(pat: re.Pattern) -> Optional[int]:
            for mm in pat.finditer(text):
                if mm.start() > articulado_start:
                    return mm.start()
            return None

        resuelve = re.compile(
            r"(?:^|\n)[ \t]{0,4}(RESUELVE|DISPONE|CERTIFICA|EXPIDE)[ \t]*:",
            re.MULTILINE,
        )
        for pat, name in ((_PAT_DISP, "disposicion"),
                          (resuelve, "resolucion"),
                          (_PAT_ANEXO, "anexo")):
            pos = _first_after(pat)
            if pos is not None:
                boundaries.append((pos, name))
        boundaries.sort()

        def _resolver(pos: int) -> str:
            current = "preambulo"
            for start, name in boundaries:
                if pos >= start:
                    current = name
                else:
                    break
            return current

        return _resolver

    def _is_reference(self, text: str, art_pos: int, tail: str, bloque: str) -> bool:
        """True si el 'artículo' es una cita a otra norma o vive en el preámbulo."""
        if bloque == "preambulo":
            return True
        if _PAT_REF_POST.match(tail):
            return True
        pre = text[max(0, art_pos - 40):art_pos]
        if _PAT_REF_PRE.search(pre):
            return True
        return False

    @staticmethod
    def _flag_duplicate_articulos(records: list[dict]) -> None:
        """Marca como referencia las repeticiones de un mismo número dentro del
        articulado (típico de documentos que citan artículos, p.ej. objeciones)."""
        seen: set[str] = set()
        for r in records:
            if r["tipo_elemento"] != "articulo" or r["es_referencia"]:
                continue
            key = r["numero"]
            if key in seen:
                r["es_referencia"] = True
            else:
                seen.add(key)

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
        self._device = _resolve_device(device)

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
            doc_items = getattr(chunk.meta, "doc_items", None)
            if doc_items:
                prov = getattr(doc_items[0], "prov", None)
                if prov:
                    page_no = prov[0].page_no

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
        from docling.chunking import HybridChunker

        # FAST mode evita el crash de TableFormer en conversiones live (sin caché)
        opts = _build_pdf_pipeline_options(self._device, do_ocr=True, table_mode="fast")
        converter = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
        )
        chunker = HybridChunker(max_tokens=self.max_tokens)
        return converter, chunker

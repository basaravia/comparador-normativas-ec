#!/usr/bin/env python3
"""Inspección profunda de PDFs para el guardián de confidencialidad.

El escáner rápido (`scan_confidencial.py`) solo intenta la capa de texto: si el PDF es un
escaneo, no ve nada y lo declara "no escaneado". Este script es el escalón siguiente, para
usar bajo demanda —no en un hook— cuando hay que decidir sobre un PDF concreto.

Escalera, de más barata a más cara. Solo se escala si el paso anterior no basta:

  1. Capa de texto     pymupdf → pypdf → pdfplumber → pdfminer
  2. Si sale vacía     → el PDF es un escaneo → OCR
  3. OCR               ocrmac (Vision del SO) → tesseract → easyocr → docling
  4. Imágenes          se cuentan y se reportan: un membrete o un logo escaneado
                       identifica a la entidad aunque no haya una sola letra extraíble

Uso:
    inspeccionar_pdf.py archivo.pdf [más.pdf …]
    inspeccionar_pdf.py archivo.pdf --ocr          # fuerza OCR aunque haya capa de texto
    inspeccionar_pdf.py archivo.pdf --paginas 1-5
    inspeccionar_pdf.py archivo.pdf --texto        # vuelca el texto extraído a stdout
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from capacidades import hay, inventario  # noqa: E402

UMBRAL_VACIO = 50  # caracteres por página por debajo de los cuales se asume escaneo


# ── 1 · capa de texto ─────────────────────────────────────────────────────────

def _pymupdf(p: Path, paginas) -> str:
    import fitz
    doc = fitz.open(str(p))
    idx = paginas or range(len(doc))
    return "\n".join(doc[i].get_text() for i in idx if i < len(doc))


def _pypdf(p: Path, paginas) -> str:
    from pypdf import PdfReader
    pgs = PdfReader(str(p)).pages
    idx = paginas or range(len(pgs))
    return "\n".join((pgs[i].extract_text() or "") for i in idx if i < len(pgs))


def _pdfplumber(p: Path, paginas) -> str:
    import pdfplumber
    with pdfplumber.open(str(p)) as pdf:
        idx = paginas or range(len(pdf.pages))
        return "\n".join((pdf.pages[i].extract_text() or "") for i in idx if i < len(pdf.pages))


def _pdfminer(p: Path, paginas) -> str:
    from pdfminer.high_level import extract_text
    return extract_text(str(p), page_numbers=list(paginas) if paginas else None)


EXTRACTORES = {"pymupdf": _pymupdf, "pypdf": _pypdf, "pdfplumber": _pdfplumber, "pdfminer": _pdfminer}


def extraer_texto(p: Path, paginas=None) -> tuple[str, str]:
    """Prueba la escalera hasta que una devuelva algo. Retorna (texto, método)."""
    inv = inventario()
    for nombre in inv["pdf"]["disponibles"]:
        try:
            t = EXTRACTORES[nombre](p, paginas)
            if t and t.strip():
                return t, nombre
        except Exception:
            continue  # extractor caído: prueba el siguiente, no abortes
    return "", "ninguno"


# ── 2 · OCR ───────────────────────────────────────────────────────────────────

def _paginas_a_png(p: Path, destino: Path, paginas=None, dpi=200) -> list[Path]:
    """Rasteriza con pymupdf, que ya está y no necesita poppler."""
    import fitz
    doc = fitz.open(str(p))
    idx = list(paginas) if paginas else range(len(doc))
    salidas = []
    for i in idx:
        if i >= len(doc):
            break
        png = destino / f"pag_{i:04d}.png"
        doc[i].get_pixmap(dpi=dpi).save(str(png))
        salidas.append(png)
    return salidas


def _ocr_ocrmac(imgs: list[Path]) -> str:
    from ocrmac import ocrmac
    partes = []
    for img in imgs:
        # Vision del SO: sin descargas ni RAM de modelo. Español + inglés.
        res = ocrmac.OCR(str(img), language_preference=["es-ES", "en-US"]).recognize()
        partes.append("\n".join(t for t, _conf, _box in res))
    return "\n".join(partes)


def _ocr_tesseract(imgs: list[Path]) -> str:
    partes = []
    for img in imgs:
        r = subprocess.run(["tesseract", str(img), "stdout", "-l", "spa+eng"],
                           capture_output=True, text=True)
        partes.append(r.stdout)
    return "\n".join(partes)


def _ocr_easyocr(imgs: list[Path]) -> str:
    import easyocr
    inv = inventario()
    lector = easyocr.Reader(["es", "en"], gpu=inv["hardware"]["acelerador"] != "cpu")
    return "\n".join("\n".join(lector.readtext(str(i), detail=0)) for i in imgs)


OCRS = {"ocrmac": _ocr_ocrmac, "tesseract": _ocr_tesseract, "easyocr": _ocr_easyocr}


def ocr(p: Path, paginas=None) -> tuple[str, str]:
    inv = inventario()
    disponibles = [o for o in inv["ocr"]["disponibles"] if o in OCRS]
    if not disponibles:
        return "", "ninguno"
    with tempfile.TemporaryDirectory() as tmp:
        try:
            imgs = _paginas_a_png(p, Path(tmp), paginas)
        except Exception as e:
            return "", f"no se pudo rasterizar: {e}"
        for nombre in disponibles:
            try:
                t = OCRS[nombre](imgs)
                if t and t.strip():
                    return t, nombre
            except Exception:
                continue
    return "", "ninguno"


# ── 3 · imágenes incrustadas ──────────────────────────────────────────────────

def contar_imagenes(p: Path) -> int:
    """Un membrete o un logo escaneado identifica a la entidad sin una sola letra."""
    if not hay("fitz"):
        return -1
    import fitz
    doc = fitz.open(str(p))
    return sum(len(pg.get_images(full=True)) for pg in doc)


# ── main ──────────────────────────────────────────────────────────────────────

def _rango(arg: str):
    if "-" in arg:
        a, b = arg.split("-", 1)
        return range(int(a) - 1, int(b))
    return [int(arg) - 1]


def inspeccionar(p: Path, forzar_ocr=False, paginas=None) -> dict:
    import fitz  # solo para el número de páginas; ya validado en la escalera
    n_pag = len(fitz.open(str(p))) if hay("fitz") else None

    texto, metodo = ("", "omitido") if forzar_ocr else extraer_texto(p, paginas)
    por_pagina = len(texto) / max(n_pag or 1, 1)
    escaneado = por_pagina < UMBRAL_VACIO

    texto_ocr, metodo_ocr = "", None
    if forzar_ocr or escaneado:
        texto_ocr, metodo_ocr = ocr(p, paginas)

    return {
        "archivo": str(p),
        "paginas": n_pag,
        "metodo_texto": metodo,
        "chars_texto": len(texto),
        "chars_por_pagina": round(por_pagina),
        "parece_escaneado": escaneado,
        "metodo_ocr": metodo_ocr,
        "chars_ocr": len(texto_ocr),
        "imagenes": contar_imagenes(p),
        "_texto": texto or texto_ocr,
    }


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 2
    forzar = "--ocr" in args
    volcar = "--texto" in args
    paginas = None
    if "--paginas" in args:
        paginas = _rango(args[args.index("--paginas") + 1])
    rutas = [a for a in args if a.endswith(".pdf")]

    for ruta in rutas:
        p = Path(ruta)
        if not p.exists():
            print(f"  {ruta}: no existe")
            continue
        r = inspeccionar(p, forzar, paginas)
        print(f"\n{r['archivo']}")
        print(f"  páginas          {r['paginas']}")
        print(f"  capa de texto    {r['metodo_texto']} · {r['chars_texto']} chars "
              f"({r['chars_por_pagina']}/pág)")
        print(f"  ¿escaneado?      {'SÍ — sin capa de texto útil' if r['parece_escaneado'] else 'no'}")
        if r["metodo_ocr"]:
            print(f"  OCR              {r['metodo_ocr']} · {r['chars_ocr']} chars")
        print(f"  imágenes         {r['imagenes']}"
              + ("   ← revisar: un logo o membrete identifica sin texto" if r["imagenes"] else ""))
        if volcar and r["_texto"]:
            print("\n--- texto ---")
            print(r["_texto"])
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Qué puede hacer esta máquina — y con qué coste.

Los scripts del guardián eligen su estrategia en función de lo que haya instalado y del
hardware disponible, en vez de asumir. Ejecutable directamente para ver el inventario:

    python capacidades.py
"""
from __future__ import annotations

import importlib.util
import os
import platform
import shutil
import sys


def hay(mod: str) -> bool:
    try:
        return importlib.util.find_spec(mod) is not None
    except (ImportError, ValueError):
        return False


def hardware() -> dict:
    hw = {
        "so": sys.platform,
        "arch": platform.machine(),
        "cpus": os.cpu_count() or 1,
        "ram_gb": None,
        "acelerador": "cpu",
    }
    try:
        hw["ram_gb"] = round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / (1024**3))
    except (ValueError, AttributeError, OSError):
        pass
    if hay("torch"):
        import torch
        if torch.backends.mps.is_available():
            hw["acelerador"] = "mps"
        elif torch.cuda.is_available():
            hw["acelerador"] = "cuda"
    return hw


# ── escaleras de estrategia, de más barata a más cara ─────────────────────────
# El orden importa: se usa la primera disponible y solo se escala si hace falta.

EXTRACTORES_PDF = [
    ("pymupdf",   lambda: hay("fitz"),      "rápido, buena extracción de layout"),
    ("pypdf",     lambda: hay("pypdf"),     "puro python, suficiente con capa de texto"),
    ("pdfplumber", lambda: hay("pdfplumber"), "mejor con tablas"),
    ("pdfminer",  lambda: hay("pdfminer"),  "análisis de layout exhaustivo, lento"),
]

OCR = [
    ("ocrmac",     lambda: sys.platform == "darwin" and hay("ocrmac"),
     "Vision del SO: sin descargas, sin RAM extra, rápido"),
    ("tesseract",  lambda: shutil.which("tesseract") is not None,
     "binario del sistema, moderado"),
    ("easyocr",    lambda: hay("easyocr"),
     "modelos torch, puede usar acelerador, ~1GB RAM"),
    ("docling",    lambda: hay("docling"),
     "layout completo, el más caro; último recurso"),
]

NER = [
    ("heuristico",   lambda: True,
     "sin dependencias ni descargas, instantáneo, recall alto y precisión media"),
    ("transformers", lambda: hay("transformers"),
     "modelo NER en español; requiere descarga la primera vez (~500MB-1GB)"),
]


def _primera(escalera) -> str | None:
    return next((n for n, disp, _ in escalera if disp()), None)


def disponibles(escalera) -> list[str]:
    return [n for n, disp, _ in escalera if disp()]


def inventario() -> dict:
    return {
        "hardware": hardware(),
        "pdf": {"disponibles": disponibles(EXTRACTORES_PDF), "elegido": _primera(EXTRACTORES_PDF)},
        "ocr": {"disponibles": disponibles(OCR), "elegido": _primera(OCR)},
        "ner": {"disponibles": disponibles(NER), "elegido": _primera(NER)},
    }


def main() -> int:
    inv = inventario()
    hw = inv["hardware"]
    print("\nCAPACIDADES DE ESTA MÁQUINA\n")
    print(f"  hardware   {hw['arch']} · {hw['cpus']} cpus · {hw['ram_gb']}GB · acelerador={hw['acelerador']}")
    for clave, escalera in (("pdf", EXTRACTORES_PDF), ("ocr", OCR), ("ner", NER)):
        d = inv[clave]
        print(f"\n  {clave.upper():4} elegido: {d['elegido'] or '(ninguno)'}")
        for nombre, disp, nota in escalera:
            print(f"       {'·' if disp() else 'x'} {nombre:13} {nota}")
    if hw["ram_gb"] and hw["ram_gb"] <= 16:
        print("\n  Aviso: 16GB o menos. Evita OCR con modelos torch y extracción de PDF")
        print("  en paralelo — este proyecto ya ha visto OOM/segfault con faiss + torch.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())

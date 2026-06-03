# Extracción de Normativas Ecuatorianas 2026

Pipeline de extracción de texto y estructura (artículos, secciones, anexos) de documentos normativos ecuatorianos en PDF, usando dos frameworks comparados: **MarkItDown** (Microsoft) y **Docling** (IBM Research).

## Documentos procesados

| Archivo | Tipo | Páginas |
|---------|------|---------|
| `LEY-ORGANICA-PARA-EL-FORTALECIMIENTO-DE-LA-CIBERSEGURIDAD_202652616421988.pdf` | Ley Orgánica | 104 |
| `PDL-DERECHOS-DIGITALES.pdf` | Proyecto de Ley | 42 |
| `Proyecto-de-Ley-Organica-Organica-para-Reprimir-y-Prevenir-el-Lavado-de-Activos-y-la-Financiacion-del-Terrorismo.pdf` | Proyecto de Ley | 60 (mixto: escaneado + digital) |
| `Proyecto-de-Ley-Transformacion-Digital-y-Audiovisual.pdf` | Proyecto de Ley | 32 |
| `Resoluci_n_N_SPDP_SPD_2026_0009_R_1771536870.pdf` | Resolución | 8 (escaneado) |

## Entorno

**Conda:** `puce-tesis` (Python 3.13.5)

```bash
conda activate puce-tesis
```

Dependencias principales:

| Paquete | Versión |
|---------|---------|
| docling | 2.55.1 |
| markitdown | 0.1.6 |
| torch | 2.8.0 (MPS) |
| openpyxl | 3.1.5 |
| ocrmac | 1.0.1 |

## Notebooks

### `01_markitdown_normativas.ipynb` — MarkItDown

Extrae texto plano vía `pdfminer`. Rápido, sin GPU, ideal para PDFs digitales bien formados.

**Parámetros configurables:**

```python
DEVICE      = "cpu"    # "cpu" | "mps" | "cuda"
LLM_BACKEND = "none"   # "none" | "ollama" | "docker-model-runner"
LLM_MODEL   = "llava:7b"  # modelo multimodal para docs escaneados
```

- `LLM_BACKEND = "none"` — extracción directa de texto (recomendado para PDFs digitales)
- `LLM_BACKEND = "ollama"` — usa Ollama en `localhost:11434` con modelo multimodal
- `LLM_BACKEND = "docker-model-runner"` — usa Docker Model Runner en `localhost:12434`

**Salida:** `output/markitdown/`

---

### `02_docling_normativas.ipynb` — Docling

Pipeline ML completo con análisis de layout, OCR y detección de tablas (TableFormer). Genera Markdown semántico (headings, listas, tablas). Requiere GPU/MPS para velocidad razonable.

**Parámetros configurables:**

```python
DEVICE               = "mps"      # "cpu" | "mps" (Apple Silicon) | "cuda" (NVIDIA)
NUM_THREADS          = 8
ENABLE_OCR           = True
OCR_BACKEND          = "auto"     # "auto" | "easyocr" | "mac"
FORCE_FULL_PAGE_OCR  = False      # True para docs 100% escaneados
OCR_CONFIDENCE       = 0.35
ENABLE_TABLES        = True
TABLE_MODE           = "accurate" # "accurate" | "fast"
```

**Configuración recomendada por tipo de documento:**

| Tipo de documento | `OCR_BACKEND` | `FORCE_FULL_PAGE_OCR` | `TABLE_MODE` |
|-------------------|---------------|-----------------------|--------------|
| Digital (texto seleccionable) | `auto` | `False` | `accurate` |
| Mixto (portada escaneada + texto digital) | `auto` | `False` | `accurate` |
| 100% escaneado | `auto` | `True` | `fast` |

En macOS con MPS, `auto` selecciona automáticamente **Apple Vision Framework** (`ocrmac`), que es 3–7× más rápido que EasyOCR con resultados equivalentes.

**Salida:** `output/docling/`

---

## Estructura del output

```
output/
├── markitdown/
│   ├── <doc>.md                     # texto extraído en Markdown
│   ├── normativas_markitdown.json   # estructura parseada (artículos, secciones, anexos)
│   └── normativas_markitdown.xlsx   # tabla Excel por normativa
└── docling/
    ├── <doc>.md                     # markdown semántico (headings, listas, tablas)
    ├── <doc>_docling.json           # estructura nativa de Docling
    ├── normativas_docling.json      # estructura parseada
    └── normativas_docling.xlsx      # tabla Excel por normativa
```

### Columnas del Excel

| Columna | Descripción |
|---------|-------------|
| `NUMERO` | Número del artículo |
| `ARTICULO` | Texto completo (encabezado + contenido) |
| `PAGINA` | Página del PDF (Docling) / `N/D` (MarkItDown) |
| `SECCION` | Última sección jerárquica antes del artículo (TÍTULO · CAPÍTULO · SECCIÓN) |
| `FECHA` | Primera fecha encontrada en el encabezado del documento |

## Parser de estructura normativa

Compartido por ambos notebooks. Captura los patrones del ordenamiento jurídico ecuatoriano:

- **Artículos:** `Art. N.-` · `Artículo N.-` · con prefijos Markdown (`## `, `- `, `1. `)
- **Jerarquía:** `TÍTULO N` · `CAPÍTULO N` · `SECCIÓN N` (incluyendo formato heading `##`)
- **Disposiciones:** Transitorias, Generales, Finales, Derogatorias, Reformatorias
- **Secciones resolutorias:** `CONSIDERANDO:` · `RESUELVE:` · `CERTIFICA:`
- **Anexos:** `ANEXO I` · `ANEXO 1` · `ANEXO ÚNICO`

## Rendimiento (Apple M-series, MPS)

| Documento | MarkItDown | Docling |
|-----------|-----------|---------|
| Ciberseguridad (104 pp, digital) | ~5 s | ~58 s |
| Derechos Digitales (42 pp, digital) | ~2 s | ~43 s |
| Lavado de Activos (60 pp, mixto) | ~3 s | ~37 s |
| Transformación Digital (32 pp) | ~2 s | ~43 s |
| Resolución SPDP (8 pp, escaneado) | — | ~14 s |

## Notas conocidas

- **Proyecto de Ley Transformación Digital:** MarkItDown extrae texto vacío (el PDF puede estar protegido o ser imagen sin capa de texto). Docling extrae texto vía OCR.
- **Artículos con sub-numeración** (e.g. `20-A`, `20-J`): capturados correctamente por el patrón `\d+[\w]*`.
- **Docling genera Markdown semántico:** algunos artículos aparecen como headings (`##`) o ítems de lista (`-`). El parser maneja ambos formatos.

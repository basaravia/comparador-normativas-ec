# Comparador Automatizado de Normativas vs Manuales Internos

Pipeline de 5 fases para analizar el cumplimiento de manuales bancarios internos
respecto a normativas ecuatorianas (SBS, BCE, SEPS, UAF, Asamblea Nacional).

---

## Interfaz Streamlit

`streamlit_app.py` (rama `feature/streamlit-ui`) expone el mismo pipeline de
`master.ipynb` como app web: carga/selección de PDFs de normativa y manual,
configuración en la barra lateral de los modelos fundacionales (embeddings,
LLM, reranker, umbrales de búsqueda — parámetros centralizados en
`src/config.py`), ejecución con progreso en vivo y dashboard de resultados.

```bash
conda run -n puce-tesis pip install -r dependencies/requirements.txt   # instala streamlit
conda run -n puce-tesis streamlit run streamlit_app.py
```

Requiere Docker Model Runner corriendo en `localhost:12434` (o la URL que se
configure en la barra lateral) para los pasos de embeddings/LLM. Los logs de
cada ejecución se imprimen en la terminal donde corre `streamlit run` y se
guardan al finalizar en `output/logs/run_<timestamp>.log`.

---

## Arquitectura del pipeline

```text
┌─────────────────────────────────────────────────────────────────────────┐
│  FASE 1 — Tabulación de documentos           src/document_parser.py     │
│                                                                         │
│  Normativa2026/*.pdf                                                    │
│       │                                                                 │
│       ▼  NormativaParser                                                │
│  [Docling layout+OCR] → reflow párrafos, remoción cabeceras/pies        │
│  [caché output/docling/*.md] → 0 s en re-ejecución (offline)           │
│  [regex articulado] → artículos, disposiciones, anexos                  │
│  [block segmentation] → preambulo / articulado / disposicion / anexo   │
│  [citation detection] → es_referencia=True para citas a otras normas   │
│       │                                                                 │
│       ▼  normativa_df  (1 fila = 1 artículo / disposición / anexo)     │
│                                                                         │
│  document_test/*.pdf                                                    │
│       │                                                                 │
│       ▼  ManualParser                                                   │
│  [Docling layout+OCR] → orden de lectura, tablas                       │
│  [HybridChunker] → chunks semánticos con jerarquía de encabezados      │
│       │                                                                 │
│       ▼  manual_df  (1 fila = 1 sección / chunk semántico)             │
└─────────────────────────────────────────────────────────────────────────┘
          │                            │
          ▼                            ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  FASE 2 — Motor de búsqueda                  src/search_engine.py       │
│                                                                         │
│  normativa_df                                                           │
│       │                                                                 │
│       ▼  NormativaIndex                                                 │
│  [Embeddings] LangChainDMR (qwen3-embedding) | SentenceTransformers    │
│  [FAISS]      índice L2 sobre embed_text de cada artículo              │
│  [BM25-like]  lexical_scan → artículos citados por número en el texto  │
│  [Reranker]   qwen3-reranker-vllm (post-FAISS opcional)                │
│       │                                                                 │
│       ▼  candidates[]  (artículos semánticamente relevantes + léxicos) │
└─────────────────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  FASE 3+4 — Retrieve-then-Grade + Análisis   src/llm_grader.py         │
│                                                                         │
│  manual_df[sección] + candidates[]                                      │
│       │                                                                 │
│       ▼  LLMGrader                                                      │
│  [grade_candidates]   LLM califica cada candidato (relevante / no)     │
│  [analyze_comparison] LLM genera análisis de cumplimiento estructurado │
│       │                                                                 │
│       ▼  ComparisonResult                                               │
│     tipo_coincidencia | nivel_cumplimiento | analisis_general          │
│     normativas_aplicables | recomendaciones                            │
└─────────────────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  FASE 5 — Pipeline concurrente completo      src/comparator.py         │
│                                                                         │
│  DocumentComparator.run(manual_df, normativa_df, max_workers=N)        │
│       │                                                                 │
│       ▼  results_df                                                     │
│  [Excel formateado]  output/comparado/reporte_comparacion.xlsx         │
│  [JSON]              output/comparado/reporte_comparacion.json         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Estructura del repositorio

```text
compara_docs/
├── master.ipynb                  ← notebook principal (5 fases)
├── environment.yml               ← freeze completo del entorno de desarrollo (no usar para replicar)
├── dependencies/                 ← entorno reproducible (Apple Silicon 16GB): environment.yml, setup_apple_silicon.sh
├── Normativa2026/                ← PDFs de normativas ecuatorianas
│   ├── PDL-DERECHOS-DIGITALES.pdf
│   ├── LEY-ORGANICA-PARA-EL-FORTALECIMIENTO-DE-LA-CIBERSEGURIDAD_*.pdf
│   ├── Proyecto-de-Ley-*-Lavado-de-Activos-*.pdf
│   ├── Proyecto-de-Ley-Transformacion-Digital-y-Audiovisual.pdf
│   ├── Resoluci_n_N_SPDP_*.pdf
│   └── L1-XVI-cap-{II,III,IV,V}.pdf    ← pendientes de cachear
├── document_test/                ← PDFs de manuales internos bancarios
├── src/
│   ├── document_parser.py        ← NormativaParser + ManualParser
│   ├── search_engine.py          ← NormativaIndex (FAISS + lexical + reranker)
│   ├── embeddings.py             ← LangChainDMREmbeddings / SentenceTransformers
│   ├── llm_grader.py             ← LLMGrader (grade + analyze)
│   ├── comparator.py             ← DocumentComparator (pipeline concurrente)
│   ├── config.py                 ← constantes globales
│   └── __init__.py               ← exports públicos
└── output/
    ├── docling/                  ← caché markdown (*.md) + JSON nativo Docling
    │   ├── PDL-DERECHOS-DIGITALES.md
    │   ├── LEY-ORGANICA-*.md
    │   ├── Proyecto-de-Ley-*-Lavado-*.md
    │   ├── Proyecto-de-Ley-Transformacion-*.md
    │   └── Resoluci_n_N_SPDP_*.md
    └── comparado/                ← salida del pipeline (generada al ejecutar)
        ├── normativa_tabulada.json
        ├── manual_tabulado.json
        ├── faiss_index/
        └── reporte_comparacion.xlsx
```

---

## Módulos (`src/`)

### `document_parser.py` — Fase 1

#### `NormativaParser`

Extrae artículos, disposiciones y anexos de PDFs normativos ecuatorianos.

**Flujo interno:**

1. `_to_markdown()` — convierte PDF con Docling (layout ML + OCR nativo macOS). Lee de caché `output/docling/*.md` si ya existe.
2. `_strip_repeated_lines()` — elimina cabeceras/pies repetidos (nombre de ponente, email institucional, paginación).
3. `_clean_text()` — normaliza tabs, espacios y líneas de artefacto.
4. `_parse_text()` — regex sobre el markdown limpio:
   - `_PAT_ART` captura número con sufijos (`20-A`, `20-J`).
   - `_build_block_resolver()` segmenta en `preambulo / articulado / disposicion / resolucion / anexo`.
   - `_split_header_body()` separa epígrafe y cuerpo (compatible con estilo Docling y markitdown).
   - `_is_reference()` marca citas a otras normas (`es_referencia=True`).
   - `_flag_duplicate_articulos()` marca duplicados del mismo número.

**DataFrame de salida — `normativa_df`:**

| Columna | Tipo | Descripción |
| --- | --- | --- |
| `orden` | int | Posición absoluta en el documento |
| `element_id` | str | `{archivo}_{orden:04d}` — identificador único |
| `doc_id` | str | Nombre del archivo PDF |
| `tipo_norma` | str | LEY ORGÁNICA / RESOLUCIÓN / REGLAMENTO / … |
| `titulo_norma` | str | Primera línea no vacía del documento |
| `fecha` | str | `YYYY-MM-DD` (extraída del preámbulo) |
| `numero` | str | Número normalizado del artículo (`20-A`, `104`) |
| `encabezado` | str | Epígrafe del artículo (si existe, ≤250 chars) |
| `contenido` | str | Cuerpo del artículo (≤3 000 chars) |
| `seccion` | str | Jerarquía activa `TÍTULO I — CAPÍTULO II > …` |
| `tipo_elemento` | str | `articulo` / `disposicion` / `anexo` |
| `tipo_bloque` | str | `preambulo` / `articulado` / `disposicion` / `resolucion` / `anexo` |
| `es_referencia` | bool | True = cita a otra norma o artículo del preámbulo |
| `posicion` | int | Offset de bytes en el texto para trazabilidad |
| `embed_text` | str | Texto listo para embeddings (`seccion + número + encabezado + contenido`) |

#### `ManualParser`

Extrae secciones semánticas de manuales internos bancarios con Docling `HybridChunker`.

**DataFrame de salida — `manual_df`:**

| Columna | Descripción |
| --- | --- |
| `chunk_id` | `{stem}_{i:04d}` |
| `doc_id` | Nombre del archivo |
| `fuente` | Nombre del archivo |
| `pagina_inicio` | Página PDF del chunk |
| `pagina_fin` | Página PDF del chunk |
| `jerarquia` | `Capítulo > Sección > Subsección` |
| `titulo_seccion` | Último heading del chunk |
| `texto` | Texto del chunk |
| `embed_text` | `jerarquia + "\n" + texto` |

---

### `search_engine.py` — Fase 2: `NormativaIndex`

- **`build(normativa_df)`** — crea índice FAISS L2 sobre `embed_text`.
- **`semantic_search(query, top_k)`** — búsqueda por embedding coseno.
- **`lexical_scan(texto, normativa_df)`** — detecta artículos citados por número (`Art. 5`, `artículo 12`) en el texto del manual.
- **`rerank(query, candidates, top_n)`** — reranking con `qwen3-reranker-vllm` (opcional).
- **`save/load(path)`** — persistencia del índice FAISS en disco.

**Backends de embeddings (`embeddings.py`):**

| Clase | Modelo | Uso recomendado |
| --- | --- | --- |
| `LangChainDMREmbeddings` | `ai/qwen3-embedding:latest` (2560d) | Producción — mayor calidad en español legal |
| `SentenceTransformersEmbeddings` | `paraphrase-multilingual-mpnet` | Offline sin Docker Model Runner |

---

### `llm_grader.py` — Fases 3+4: `LLMGrader`

- **`grade_candidates(texto_manual, candidates)`** — el LLM califica cada candidato (relevante / no) con razonamiento.
- **`analyze_comparison(chunk, lexical_matches, graded_candidates)`** — genera `ComparisonResult` estructurado:
  - `tipo_coincidencia`: `exacta / parcial / referencia / sin_coincidencia`
  - `nivel_cumplimiento`: `cumple / parcial / omision / conflicto`
  - `analisis_general`, `normativas_aplicables`, `recomendaciones`

---

### `comparator.py` — Fase 5: `DocumentComparator`

- **`run(manual_df, normativa_df, max_workers)`** — pipeline concurrente completo.
- **`run_sample(manual_df, normativa_df, n)`** — valida sobre N secciones antes del run completo.
- **`summary(results_df)`** — resumen estadístico de cumplimiento.
- **`export_excel(results_df, output_path)`** — Excel formateado con colores por nivel.

---

## Estado actual

### Fase 1.1 — NormativaParser (Docling)

Migración de `markitdown` a `Docling` completada y validada offline. **Cero descargas necesarias**: los modelos Docling están en `~/.cache/huggingface/hub/models--ds4sd--docling-*` y el OCR usa el framework Vision nativo de macOS (`ocrmac`).

**Resultados validados (2026-07-02, `HF_HUB_OFFLINE=1`):**

| Normativa | Artículos reales | Referencias | Epígrafes | Notas |
| --- | --- | --- | --- | --- |
| PDL-Derechos-Digitales | 39 | 5 | 32/39 | reflow completo, cabeceras limpias |
| Ley-Ciberseguridad | 43 | 27 | 28/43 | objeción presidencial (cita arts. 20-A…20-J) |
| Lavado-de-Activos | 104 | 0 | 3/104 | artículos sin epígrafe (formato normal) |
| Transformación-Digital | 41 | 0 | 11/41 | **era 0 bytes con markitdown; rescatado por OCR** |
| Resolución-SPDP | 10 | 0 | 0/10 | resolución sin epígrafes (correcto) |

Cabeceras/pies residuales en `contenido`: **0** ("ASAMBLEÍSTA POR LOJA" eliminado por `_strip_repeated_lines`).

### Fases 1.2, 2, 3+4, 5

Implementadas en sus módulos. Pendiente validación end-to-end completa en `master.ipynb` (requiere Docker Model Runner con `qwen3-embedding` + `gemma4`).

---

## `master.ipynb` — flujo del notebook

| Sección | Celda | Contenido |
| --- | --- | --- |
| Configuración | 0 | Setup de paths y logging |
| | 1 | Imports de todos los módulos `src/` |
| Fase 1.1 | 2–3 | `NormativaParser` → `normativa_df` (guardado en JSON + Excel) |
| Fase 1.2 | 4–5 | `ManualParser` → `manual_df` (guardado en JSON) |
| Fase 2.1 | 6 | Inicializar backend de embeddings (DMR o SentenceTransformers) |
| Fase 2.2 | 7 | Construir índice FAISS sobre `normativa_df` |
| Fase 2.3 | 8–10 | Verificar búsqueda semántica, reranking y léxica |
| Fases 3+4 | 11–15 | `LLMGrader`: grade de candidatos + análisis comparativo |
| Fase 5 | 16–17 | `DocumentComparator.run_sample()` + `.run()` completo |
| Resultados | 18–20 | Resumen estadístico, omisiones críticas, exportación Excel/JSON |
| Uso modular | 21–22 | Carga de índice existente + análisis incremental |

> **Nota Fase 1.1:** La celda actual itera sobre `NORMATIVA_DIR.glob("*.pdf")`, lo que incluye `L1-XVI-cap-*.pdf` (no en caché). Mientras esos PDFs no estén pre-cacheados, usar `parse_pdf()` explícitamente sobre los 5 stems cacheados para evitar el segfault MPS al intentar convertirlos.

---

## Entorno

**Conda:** `puce-tesis` (Python 3.13.5)

```bash
conda activate puce-tesis
```

Dependencias principales:

| Paquete | Versión | Rol |
| --- | --- | --- |
| docling | 2.55.1 | Extracción PDF (layout ML + OCR) |
| ocrmac | 1.0.1 | OCR nativo macOS (Vision framework, sin descargas) |
| torch | 2.8.0 | Acelerador MPS (Apple Silicon) |
| faiss-cpu | — | Índice de vectores |
| langchain | — | Integración embeddings / LLM |
| openpyxl | 3.1.5 | Exportación Excel |
| pandas | — | DataFrames |

> **Sin red / datos móviles:** el pipeline completo de Fase 1 corre offline. Las fases 2–5 requieren Docker Model Runner local (no red externa).

### Variables de entorno

| Variable | Default | Rol |
| --- | --- | --- |
| `ORG_DISPLAY_NAME` | *(vacío)* | Nombre de la entidad en el título de la app. Sin definir, la UI muestra solo "Comparador Normativo". |

Se leen del entorno o de un `.env` local, que está en `.gitignore`. El nombre de
la entidad y las rutas a sus documentos internos no se escriben en el código: el
repositorio no debe identificar al cliente.

---

## Ejecución rápida

```bash
conda activate puce-tesis
jupyter lab master.ipynb
```

Para ejecutar solo la Fase 1 (offline, segundos):

```python
from src import NormativaParser
import pandas as pd

parser = NormativaParser(cache_dir="output/docling")  # lee caché, 0 conversiones

stems = [
    "PDL-DERECHOS-DIGITALES",
    "LEY-ORGANICA-PARA-EL-FORTALECIMIENTO-DE-LA-CIBERSEGURIDAD_202652616421988",
    "Proyecto-de-Ley-Organica-Organica-para-Reprimir-y-Prevenir-el-Lavado-de-Activos-y-la-Financiacion-del-Terrorismo",
    "Proyecto-de-Ley-Transformacion-Digital-y-Audiovisual",
    "Resoluci_n_N_SPDP_SPD_2026_0009_R_1771536870",
]
frames = [parser.parse_pdf(f"Normativa2026/{s}.pdf") for s in stems]
normativa_df = pd.concat(frames, ignore_index=True)

# Filtrar solo artículos reales (excluir citas del preámbulo)
arts = normativa_df[
    (normativa_df["tipo_elemento"] == "articulo") &
    (~normativa_df["es_referencia"])
]
```

---

## Limitaciones conocidas

- **`parse_directory("Normativa2026")`** — causa segfault (RC=139) al intentar convertir `L1-XVI-cap-*.pdf` con MPS. Workaround: usar `parse_pdf()` por archivo o pre-cachear primero esos PDFs en WiFi con `device="cpu"`.
- **Epígrafes en Lavado de Activos** — solo 3/104: los artículos no tienen título en el PDF original (formato `"Artículo 2.- Esta Ley tiene por finalidad…"`).
- **Resolución SPDP** — 0/10 epígrafes: las resoluciones ecuatorianas no llevan epígrafe por estándar.
- **Email institucional** — 2 menciones en el preámbulo de Derechos Digitales (inline dentro de párrafo legal, marcadas como `es_referencia=True`).

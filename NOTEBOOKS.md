# Notebooks — Guía rápida

Entorno conda: **`puce-tesis`** (Python 3.13.5)

---

## `master.ipynb` — notebook principal (pipeline completo)

Es el notebook de producción: corre las 5 fases del pipeline (`src/`, ver
`architecture/ARCHITECTURE.md`) más dos secciones de verificación de la Ola 2/3. Los
notebooks `00`/`01`/`02` de abajo son anteriores a `src/` y sirven para depurar un PDF
suelto o probar un backend, no para correr el comparador completo.

| Sección | Contenido |
| --- | --- |
| Fases 1–5 | Tabulación (Docling), índice FAISS híbrido, `LLMGrader`, `DocumentComparator` — el mismo pipeline que expone `streamlit_app.py` |
| Uso modular | Cargar el índice FAISS desde disco y correr un análisis incremental sin re-indexar |
| **Fase 6** | **Verificación de subsanaciones** de las olas 0-2: cada celda contrasta el defecto corregido contra el comportamiento anterior, con corpus sintético — no necesita `document_test/` ni un modelo vivo |
| **Fase 7** | **Doble vía y modelo de cobertura (Ola 3)**: `run_dual()`, `CoverageLink`/`LinkTable`, la alerta de cobertura que solo la Vía 2 puede producir, y la verificación de que el costo es la suma de las vías, no el producto — también con corpus sintético |

Tabla celda-a-celda completa en el README, sección [`master.ipynb` — flujo del
notebook](../README.md#masteripynb--flujo-del-notebook).

**Fase 1.1 (nota de robustez, no del plan):** la celda de parseo de normativas lee
`Normativa2026/*.pdf` del directorio y por defecto solo procesa los PDFs con caché
Docling en `output/docling/*.md`. `CONVERTIR_SIN_CACHE = True` convierte el resto en
vivo, forzando `device="cpu"` para evitar el segfault MPS conocido en Apple Silicon.

---

## 00 · `00_pruebas.ipynb` — OCR con visión LLM

**Cuándo usarlo:** el PDF es una imagen escaneada y no tiene capa de texto (ej. `Proyecto-de-Ley-Transformacion-Digital-y-Audiovisual.pdf`).

Usa MarkItDown con un modelo multimodal en Docker Model Runner para hacer OCR página a página.

**Requisito previo:** tener Docker Desktop abierto con el modelo `ai/qwen3-vl:4B-UD-Q4_K_XL` corriendo en `localhost:12434`.

**Parámetro clave:**
```python
LLM_MODEL = "ai/qwen3-vl:4B-UD-Q4_K_XL"
PDF_PATH  = "Normativa2026/..."
```

**Salida:** texto Markdown del PDF impreso en pantalla.

---

## 01 · `01_markitdown_normativas.ipynb` — Extracción y parseo de normativas

**Cuándo usarlo:** los PDFs son digitales (texto seleccionable). Procesa todos los PDFs de `Normativa2026/` y extrae artículos, secciones y anexos.

**Parámetros clave:**
```python
DEVICE      = "cpu"    # no necesita GPU
LLM_BACKEND = "none"   # "ollama" o "docker-model-runner" para docs escaneados
```

**Flujo:**
1. MarkItDown extrae el texto de cada PDF
2. El parser identifica artículos (`Art. N.-`), jerarquía (TÍTULO · CAPÍTULO · SECCIÓN) y disposiciones
3. Exporta resultados a Excel y JSON

**Salida:**
```
output/markitdown/
├── <doc>.md                    # texto crudo
├── normativas_markitdown.json  # artículos + secciones parseados
└── normativas_markitdown.xlsx  # una hoja por normativa
```

**Nota:** `Proyecto-de-Ley-Transformacion-Digital-y-Audiovisual.pdf` queda vacío porque es escaneado — usar `00_pruebas.ipynb` para ese caso.

---

## 02 · `02_rag_index.ipynb` — Índice semántico FAISS

**Cuándo usarlo:** quieres buscar por significado en cualquier conjunto de PDFs (ej. políticas corporativas en `document_test/`).

Genera chunks con contexto jerárquico, los embebe con un modelo multilingüe optimizado para español y los indexa en FAISS para búsqueda por similitud coseno.

**Parámetros clave:**
```python
DOCS_DIR    = Path("document_test")          # carpeta con los PDFs
EMBED_MODEL = "intfloat/multilingual-e5-large"  # mejor calidad en español (1024 dims)
                                              # alternativa rápida: "multilingual-e5-small"
MAX_TOKENS  = 512
DEVICE      = "mps"   # Apple Silicon; usar "cpu" si no hay GPU
```

**Flujo:**
1. Docling convierte los PDFs preservando la estructura (headings, tablas, listas)
2. `HybridChunker` genera chunks que no cruzan secciones, con breadcrumb jerárquico
3. Cada chunk se embebe como `"Sección > Subsección\nTexto"` con prefijo `passage:`
4. FAISS indexa los vectores normalizados (búsqueda coseno exacta)

**Salida:**
```
output/rag_index/
├── index.faiss           # índice vectorial
└── chunks_metadata.json  # texto + metadatos de cada chunk
```

**Búsqueda:**
```python
resultados = buscar("conflicto de intereses", top_k=5)
mostrar_resultados(resultados)

# filtrar por documento
resultados = buscar("controles de acceso", top_k=3, source_filter="GSI")
```

**Cargar sin reprocesar:** si el kernel se reinicia, ejecutar solo la última celda ("Cargar índice existente") — no hace falta volver a correr todo.

---

## Validación

Los scripts de validación están en la raíz del proyecto:

```bash
conda run -n puce-tesis python validate_nb01_markitdown.py
conda run -n puce-tesis python validate_nb00_pruebas.py
conda run -n puce-tesis python validate_nb02_rag_index.py
```

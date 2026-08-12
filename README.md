# Comparador Automatizado de Normativas vs Manuales Internos

Pipeline de 5 fases para analizar el cumplimiento de manuales bancarios internos
respecto a normativas ecuatorianas (SBS, BCE, SEPS, UAF, Asamblea Nacional).

> **Estado:** Fase 1 del plan de mejoras, **olas 0 y 1 cerradas**. El trabajo vive en
> `feature/comparador-v2`; `main` conserva el baseline. Ver `PLAN_MEJORAS_ANEXO.md`
> para el alcance completo y qué queda por hacer.

---

## Puesta en marcha

```bash
git clone <repo> && cd comparador-normativas-ec
git checkout feature/comparador-v2

# 1 · Guardas de confidencialidad — ANTES de commitear nada
mkdir -p .claude && cp scripts/guardas/denylist.example.json .claude/denylist.json
#      …rellenar los patrones de identidad y de marca
bash scripts/guardas/instalar_guardas.sh

# 2 · Entorno
conda env create -f dependencies/environment.yml
conda activate normas_comparador

# 3 · Verificar
pytest -q                          # 175 passed
streamlit run streamlit_app.py
```

**Tres cosas no viajan en git, a propósito** (ver *Confidencialidad*):

| Ruta | Sin ella |
|---|---|
| `.claude/denylist.json` | Los hooks abortan: el escáner no puede validar nada |
| `assets/brand/brand.json` | La app arranca con la paleta placeholder, no la corporativa |
| `document_test/` | La pestaña de documentos no encuentra manuales que analizar |

Los pasos de embeddings y LLM requieren un backend de modelos en
`localhost:12434` (configurable en la barra lateral). Los logs de cada ejecución
salen por la terminal y se guardan en `output/logs/run_<timestamp>.log`, con las
credenciales redactadas.

---

## Interfaz Streamlit

`streamlit_app.py` expone el mismo pipeline de `master.ipynb` como app web: carga
de PDFs, configuración de modelos en la barra lateral, ejecución con progreso en
vivo y dashboard de resultados.

Lo que cambió con la Ola 1 y se nota al usarla:

- **Los desplegables de modelo se pueblan con la lista real del backend**, no con
  constantes escritas a mano. El indicador dice cuántos hay.
- **Preflight antes de ejecutar**: si el modelo de LLM o el de embeddings no existe,
  el botón queda deshabilitado y el error trae la lista de los que sí están. Antes
  eso se descubría a mitad de una corrida de horas.
- **Con el backend caído la corrida se detiene** y dice cuántas secciones quedaron
  sin procesar. Ninguna sale como `no_aplica`.
- **El umbral de score semántico ya afecta a la corrida.** Antes era decorativo
  fuera de la pestaña de índice.
- Las filas sin análisis utilizable se cuentan aparte en vez de desaparecer del
  filtro por nivel de cumplimiento.

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
│  [Embeddings] backend remoto | sentence-transformers (e5, con prefijo) │
│  [FAISS]      IndexFlatIP sobre embed_text · index_meta.json valida    │
│               que se cargue con el mismo modelo con que se construyó   │
│  [Léxico]     lexical_scan → citas por número; las que existen en dos  │
│               normativas salen como match_type="ambiguo"               │
│  [Reranker]   CrossEncoder local (post-FAISS, opcional)                │
│       │                                                                 │
│       ▼  candidates[]  (artículos relevantes + léxicos firmes/ambiguos)│
└─────────────────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  FASE 3+4 — Retrieve-then-Grade + Análisis   src/llm_grader.py         │
│                                                                         │
│  manual_df[sección] + candidates[]                                      │
│       │                                                                 │
│       ▼  LLMGrader        ← cliente construido por src/providers.py    │
│  [grade_candidates]   3 niveles: normal → repara JSON → prompt mínimo  │
│                       agotados → relevante=None, NUNCA True            │
│  [analyze_comparison] análisis estructurado; una cita ambigua no       │
│                       cuenta como coincidencia léxica                  │
│       │                                                                 │
│       ▼  ComparisonResult                                               │
│     tipo_coincidencia (lexica|semantica|ninguna)                       │
│     nivel_cumplimiento (cumple|parcial|omision|no_aplica)              │
│     analisis_general · analisis_lexico · analisis_semantico_top1..3    │
│     brechas · ner_general · entidades_financieras/normativas           │
└─────────────────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  FASE 5 — Pipeline concurrente completo      src/comparator.py         │
│                                                                         │
│  DocumentComparator.run(manual_df, normativa_df, max_workers=N)        │
│  [envío acotado] ventana de tareas en vuelo → un fallo de infra deja   │
│                  de enviar de inmediato, sin depender de que el        │
│                  modelo sea lento                                       │
│  [fail-fast]     backend caído → RunAbortedError con los parciales     │
│       │                                                                 │
│       ▼  results_df  (+ estado_analisis, independiente del veredicto)  │
│  [Excel]  output/comparador/reporte_comparacion.xlsx  ← design_tokens  │
│  [JSON]   output/comparador/reporte_comparacion.json                   │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Estructura del repositorio

```text
comparador-normativas-ec/
├── master.ipynb                  ← notebook principal (5 fases)
├── streamlit_app.py              ← app web sobre el mismo pipeline
├── pyproject.toml                ← pytest (pythonpath, marcadores) + ruff
├── PLAN_MEJORAS_ANEXO.md         ← plan de las tres fases y su estado
├── environment.yml               ← freeze histórico — NO usar para replicar
├── dependencies/                 ← entorno real: environment.yml, requirements.txt
├── .github/workflows/ci.yml      ← lint + suite rápida (sin torch/docling)
├── Normativa2026/                ← PDFs de normativas ecuatorianas (públicas)
├── document_test/                ← manuales internos — FUERA DE GIT
├── assets/brand/                 ← identidad visual — FUERA DE GIT
│   └── _placeholder/             ← …salvo el placeholder genérico, que sí se versiona
├── scripts/guardas/              ← compuerta de confidencialidad (ver su README)
├── src/
│   ├── bootstrap.py              ← preparación del proceso (workarounds nativos)
│   ├── config.py                 ← defaults NO sensibles
│   ├── settings.py               ← .env, precedencia UI>entorno>.env>config, redact()
│   ├── providers.py              ← ÚNICO sitio donde se construyen clientes de modelo
│   ├── errors.py                 ← taxonomía: qué aborta y qué degrada
│   ├── model_registry.py         ← list/validate models + preflight
│   ├── design_tokens.py          ← fuente única de paleta y tipografía
│   ├── document_parser.py        ← Fase 1: NormativaParser + ManualParser
│   ├── embeddings.py             ← backends + adaptador genérico de LangChain
│   ├── search_engine.py          ← Fase 2: NormativaIndex (FAISS + léxico + reranker)
│   ├── llm_grader.py             ← Fases 3+4: LLMGrader
│   └── comparator.py             ← Fase 5: DocumentComparator
├── app/
│   ├── theme.py                  ← CSS, consume design_tokens
│   └── logging_utils.py          ← buffer del panel + redacción de secretos
├── tests/
│   ├── fixtures/                 ← corpus sintético + dobles deterministas
│   └── test_*.py                 ← 175 pruebas, ninguna toca la red
└── output/
    ├── docling/                  ← caché markdown (regenerable)
    └── comparador/               ← salida del pipeline (fuera de git)
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
- **`lexical_scan(texto, normativa_df)`** — detecta artículos citados por número. Si
  ese número existe en varias normativas y el texto no desambigua, se emiten como
  `match_type="ambiguo"` con score reducido: ni ambas como ciertas (arista falsa),
  ni una elegida a dedo (cita inventada), ni descartadas (se perdería el hecho de
  que el manual sí cita un artículo).
- **`rerank(query, candidates, top_n)`** — reranking con `qwen3-reranker-vllm` (opcional).
- **`save/load(path)`** — persistencia con `index_meta.json`: proveedor, modelo y
  dimensión. `load()` **rechaza** un índice construido con otro modelo. Sin esa
  firma, dos modelos distintos de la misma dimensión (1536 es común) cargan sin
  protestar y devuelven vecinos sin sentido, en silencio.

**Backends de embeddings (`embeddings.py`):**

| Clase | Modelo | Uso recomendado |
| --- | --- | --- |
| `LangChainDMREmbeddings` | `ai/qwen3-embedding:latest` (2560d) | Producción — mayor calidad en español legal |
| `SentenceTransformersEmbeddings` | `intfloat/multilingual-e5-large` | Offline, sin backend de modelos |
| `LangChainEmbeddingsAdapter` | cualquiera de LangChain | Costura para añadir proveedores sin clase nueva |

Los prefijos `passage: `/`query: ` los **declara el backend** (`passage_prefix` /
`query_prefix`), no los fija el índice: e5 los exige y los modelos servidos por el
backend remoto no, y anteponerlos a ciegas degradaba sus embeddings.

---

### `llm_grader.py` — Fases 3+4: `LLMGrader`

- **`grade_candidates(texto_manual, candidates)`** — califica cada candidato con
  degradación en tres niveles: cadena normal → reparación del JSON → prompt mínimo.
  Agotados los tres, los candidatos quedan **`relevante=None`** y marcados para
  revisión. **Nunca `True`**: un parseo roto no puede colar falsos positivos de
  cumplimiento. Mismo criterio si el modelo omite un candidato de una respuesta
  por lo demás válida — ausencia de juicio no es juicio favorable.
- **`analyze_comparison(chunk, lexical_matches, graded_candidates)`** — genera
  `ComparisonResult`:
  - `tipo_coincidencia`: `lexica / semantica / ninguna` — una cita ambigua **no**
    cuenta como léxica
  - `nivel_cumplimiento`: `cumple / parcial / omision / no_aplica`
  - `analisis_general`, `analisis_lexico`, `analisis_semantico_top1..3`, `brechas`,
    `ner_general`, `entidades_financieras`, `entidades_normativas`

El cliente de modelo puede **inyectarse** (`chat_grader=`/`chat_analyst=`) o pedirse
por `ProviderSpec`; la firma clásica se conserva porque `master.ipynb` la usa.

---

### `comparator.py` — Fase 5: `DocumentComparator`

- **`run(manual_df, normativa_df, max_workers)`** — pipeline concurrente con **envío
  acotado**: mantiene una ventana de tareas en vuelo en vez de encolarlas todas, de
  modo que un fallo de infraestructura deja de enviar trabajo de inmediato. Con
  `submit()` de todas por adelantado, la cancelación dependía de que el modelo fuese
  lento.
- **`run_sample(...)`**, **`summary(...)`**, **`export_excel(...)`** — sin cambios de
  superficie; el Excel toma sus colores de `design_tokens`.

**`estado_analisis` ∈ `{ok, error_modelo, error_parseo, omitido}`** es independiente de
`nivel_cumplimiento`. Un fallo técnico nunca se expresa como veredicto: cuando el
análisis no se pudo hacer, el nivel queda vacío y el motivo va en `estado_analisis`.
Antes todo fallo salía como `no_aplica`, que es un veredicto legítimo —"se miró y no
hay norma aplicable"— y confundía las dos cosas.

> Para saber si una fila tiene veredicto, mirar `estado_analisis == "ok"`, **nunca**
> `nivel_cumplimiento is None`: pandas 3.0 cambió la inferencia de dtype y ese `None`
> se vuelve `NaN`. Si hace falta comprobar el nivel, `pd.isna()`.

---

### Módulos transversales (Ola 1)

| Módulo | Rol |
|---|---|
| `errors.py` | Taxonomía que separa **abortar** (backend caído, modelo inexistente) de **degradar una fila** (respuesta no parseable). Ante la duda, aborta: seguir produciendo veredictos sobre secciones que nadie analizó es peor que detenerse |
| `providers.py` | El **único** sitio donde se construyen clientes de modelo. Una prueba lo verifica. Es lo que hará barato añadir un proveedor de nube sin tocar el motor |
| `settings.py` | `.env` con precedencia UI > entorno > `.env` > `config.py`, y `redact()`, cableado en el formatter de logging para que ninguna credencial llegue a `output/logs/` |
| `model_registry.py` | `modelos_disponibles` / `validar_modelo` / `preflight`, con caché de 15 s para no golpear el backend en cada rerun de Streamlit |
| `design_tokens.py` | Fuente única de paleta y tipografía para UI y Excel. Antes los hex estaban duplicados a mano en dos archivos |
| `bootstrap.py` | Workarounds de arranque del proceso, fuera de la UI: cuando el frontend deje de ser Python, seguirán aplicándose |

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

### Plan de mejoras — olas 0 y 1 cerradas

| Ítem | Qué resuelve | Estado |
|---|---|---|
| 1 | La corrida se detiene si cae el backend, en vez de marcar todo `no_aplica` | ✅ |
| 4 | Valida el modelo antes de gastar tokens; el grading roto no asume relevancia | ✅ |
| §2.2 | Umbral de score cableado · aislamiento léxico entre normativas · prefijos e5 | ✅ |
| P-a | Costuras de proveedor (sin SDKs de nube) | ✅ |
| T | Tokens de diseño con fuente única | ✅ |
| 2, 3 | Sincronía de estado y checkpoints | Ola 2 |
| 5, 6, 7, 10 | Modelo N:N, doble vía, selector de alcance, revisión manual | Ola 3 |
| 8, 9 | Chunking semántico y papel de trabajo | Ola 4 |

Detalle y criterios de aceptación en `PLAN_MEJORAS_ANEXO.md`.

---

## Pruebas

```bash
pytest -q                 # suite rápida: 175 passed, sin red ni modelos
pytest -m e2e             # las lentas, requieren backend real
ruff check
```

Las pruebas usan un **corpus sintético** (`tests/fixtures/corpus.py`) que construye a
propósito los casos límite: artículo huérfano, sección que satisface artículos de dos
normas, y el mismo número de artículo en dos normativas citado sin desambiguar. Es
material inventado: la suite corre en CI sin depender de `document_test/`.

Los dobles (`tests/fixtures/dobles.py`) llevan contador de invocaciones —necesario
para verificar el coste en llamadas al LLM— y fallo programable, porque media Ola 1
trata de qué ocurre cuando el modelo falla.

CI corre lint y la suite rápida sin instalar torch, docling ni sentence-transformers:
son import perezoso y las pruebas que los necesitan van marcadas `e2e`.

---

## Confidencialidad

**El repositorio es público** y contiene una herramienta construida para un cliente
concreto. Nada que lo identifique puede llegar a él: ni su nombre o el de sus filiales,
ni su paleta corporativa —que junto con la tipografía identifica tanto como el nombre—,
ni el contenido o la estructura de sus manuales internos, ni hallazgos de auditoría
atribuibles.

La compuerta es **local**, no CI: CI corre *después* del push, cuando el material ya
es visible. Instalación y detalle en `scripts/guardas/README.md`.

| Pieza | Qué corta |
|---|---|
| filtro `nbstrip` | Salidas de notebook al entrar al índice; la copia local conserva las suyas |
| hook `pre-commit` | Texto, notebooks (fuente **y** salidas), xlsx/docx, PDF |
| hook `commit-msg` | El mensaje del commit — vector que ya filtró una vez aquí |
| hook `pre-push` | Última compuerta antes de lo público |

Herramientas bajo demanda: inspección de PDFs escaneados con OCR y detección de
entidades nombradas, para encontrar filiales que la denylist aún no conozca.

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

**Conda:** `normas_comparador` (Python 3.13.5), desde `dependencies/environment.yml`.

```bash
conda env create -f dependencies/environment.yml
conda activate normas_comparador
```

> `environment.yml` de la raíz es un freeze histórico de un entorno compartido con ~300
> paquetes ajenos. **No sirve para replicar**; se conserva solo como registro de qué
> versiones convivían cuando se validó el pipeline.

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

Plantilla completa y documentada en **`.env.example`**. Copiar a `.env`, que está en
`.gitignore`.

| Variable | Default | Rol |
| --- | --- | --- |
| `ORG_DISPLAY_NAME` | *(vacío)* | Nombre de la entidad en el título. Sin definir, la UI muestra solo "Comparador Normativo" |
| `DMR_BASE_URL` | `http://localhost:12434/engines/v1` | Endpoint del backend de modelos |
| `DMR_LLM_MODEL` / `DMR_EMBED_MODEL` | ver `config.py` | Modelos por defecto |
| `BRAND_LOGO_*` | placeholder | Rutas a los logotipos reales, fuera de git |
| `GUARDAS_ASUMIR_REVISADO` | — | Acuse explícito para archivos que el escáner no puede inspeccionar. Sin él, aborta |

**Precedencia:** UI (barra lateral) > variable de entorno > `.env` > defaults de
`config.py`. `config.py` conserva solo valores no sensibles; las credenciales salen del
entorno y pasan por `redact()` antes de llegar a cualquier log.

El nombre de la entidad y las rutas a sus documentos internos no se escriben en el
código: un clon limpio arranca sin nada que identifique al cliente.

---

## Ejecución rápida

```bash
conda activate normas_comparador
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

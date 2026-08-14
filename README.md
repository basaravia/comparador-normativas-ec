# Comparador Automatizado de Normativas vs Manuales Internos

Pipeline de 5 fases para analizar el cumplimiento de manuales bancarios internos
respecto a normativas ecuatorianas (SBS, BCE, SEPS, UAF, Asamblea Nacional).

> **Estado:** Fase 1 del plan de mejoras, **olas 0, 1 y 2 cerradas**; de la Ola 3 ya
> están fusionados el modelo de cobertura N:N (ítem 5) y el motor de doble vía (ítem 6).
> Faltan la UI de la doble vía, el selector de alcance (ítem 7) y el flag de revisión
> manual (ítem 10). El trabajo vive en `feature/comparador-v2`; `main` conserva el
> baseline. Ver `PLAN_MEJORAS_ANEXO.md` para el alcance completo y qué queda por hacer.

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
pytest -q                          # 261 passed, 1 skipped
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

Lo que se sumó en la Ola 2:

- **La UI dejó de orquestar.** `streamlit_app.py` ya no construye sus propios backends
  ni pasa por alto `settings`; todo el flujo entre pestañas vive en `src/service.py`
  (S10), que Streamlit y, más adelante, una API HTTP pueden consumir por igual.
- **Cada corrida tiene su carpeta.** `output/runs/<run_id>/` en vez de la ruta fija de
  antes — dos corridas ya no se pisan el reporte, y el `run_id` viaja en
  `session_state` en vez de todo el estado de la corrida.
- **La corrida sobrevive a un refresco del navegador.** El registro de proceso vive en
  `app/run_manager.py`, protegido por lock, con un botón para cancelar cooperativamente.
- **Checkpoints con reanudación sin reprocesar.** `src/checkpoint.py` guarda entradas y
  resultados parciales; motor conectado (`comparator.py`, `service.py`), aunque la UI
  todavía no expone una sección propia de "reanudar corrida".

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
│  [Excel]  output/runs/<run_id>/reporte_comparacion.xlsx ← design_tokens│
│  [JSON]   output/runs/<run_id>/reporte_comparacion.json                │
└─────────────────────────────────────────────────────────────────────────┘
```

**Ola 3 (ítems 5 y 6, motor ya fusionado):** sobre este mismo pipeline corre un segundo
recorrido, en sentido opuesto — `src/manual_index.py` indexa el manual y `src/dual.py`
pregunta *"¿qué sección cubre este artículo?"*, no solo *"¿qué artículo aplica a esta
sección?"*. Las aristas de ambas vías conviven en `src/coverage.py` (`CoverageLink` /
`LinkTable`), con caché de grading compartida para que el costo sea la suma de las dos
vías y no el producto. Diagrama completo en `architecture/ARCHITECTURE.md`.

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
│   ├── manual_index.py           ← Ola 3 (ítem 6): ManualIndex, FAISS invertido sobre el manual
│   ├── llm_grader.py             ← Fases 3+4: LLMGrader
│   ├── comparator.py             ← Fase 5: DocumentComparator
│   ├── coverage.py               ← Ola 3 (ítem 5): CoverageLink / LinkTable, modelo N:N
│   ├── dual.py                   ← Ola 3 (ítem 6): run_dual(), Vía 1 + Vía 2
│   ├── checkpoint.py             ← Ola 2 (ítem 3): persistencia incremental y reanudación
│   └── service.py                ← Ola 2 (S10): orquestación sin Streamlit
├── app/
│   ├── theme.py                  ← CSS, consume design_tokens
│   ├── run_manager.py            ← Ola 2 (ítem 2): registro de corridas a nivel de proceso
│   └── logging_utils.py          ← buffer del panel + redacción de secretos
├── tests/
│   ├── fixtures/                 ← corpus sintético + dobles deterministas
│   └── test_*.py                 ← 261 pruebas + 1 skip, ninguna toca la red
└── output/
    ├── docling/                  ← caché markdown (regenerable)
    └── runs/<run_id>/            ← salida del pipeline por corrida (fuera de git)
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

### Módulos Ola 2 — orquestación y corridas

| Módulo | Rol |
|---|---|
| `service.py` | Orquestación del pipeline sin depender de Streamlit (S10). Sin estado: DataFrames e índice entran y salen por parámetro. Aquí vive `RunPaths` — cada corrida escribe bajo `output/runs/<run_id>/` |
| `app/run_manager.py` | Registro de corridas **a nivel de proceso**, no de `session_state`: sobrevive a un refresco del navegador, con espejo en disco (`state.json`) y cancelación cooperativa |
| `checkpoint.py` | Persistencia incremental: guarda filas completadas **y** las entradas (DataFrames + índice FAISS), para reanudar sin re-tabular ni recalcular embeddings. Conectado en `comparator.py`/`service.py`; la UI de Streamlit todavía no tiene una sección propia de "reanudar" |

### Módulos Ola 3 — doble vía y cobertura (ítems 5 y 6)

| Módulo | Rol |
|---|---|
| `coverage.py` | `CoverageLink` / `LinkTable`: la arista (artículo ↔ sección) como unidad, no la fila aplanada. `upsert` conserva la mejor observación de cada arista, no la última — el resultado no depende del orden en que corrieron las vías |
| `manual_index.py` | `ManualIndex`: índice FAISS invertido sobre el manual, para que la Vía 2 pueda preguntar "¿qué sección cubre este artículo?" — módulo propio en vez de una subclase de `NormativaIndex` (justificación en su docstring) |
| `dual.py` | `run_dual()`: corre la Vía 1 (manual→normativa) y la Vía 2 (normativa→manual) con **caché de grading compartida**, así el costo es la suma de las dos vías y no el producto |

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

### Plan de mejoras — olas 0, 1 y 2 cerradas; Ola 3 en curso

| Ítem | Qué resuelve | Estado |
|---|---|---|
| 1 | La corrida se detiene si cae el backend, en vez de marcar todo `no_aplica` | ✅ |
| 4 | Valida el modelo antes de gastar tokens; el grading roto no asume relevancia | ✅ |
| §2.2 | Umbral de score cableado · aislamiento léxico entre normativas · prefijos e5 | ✅ |
| P-a | Costuras de proveedor (sin SDKs de nube) | ✅ |
| T | Tokens de diseño con fuente única | ✅ |
| S10 | UI como vista delgada; orquestación en `service.py` | ✅ Ola 2 |
| 2, 3 | Registro de corridas a nivel de proceso + checkpoints con reanudación | ✅ Ola 2 (motor conectado; sin sección de reanudación en la UI aún) |
| 5 | Modelo de cobertura N:N artículo↔sección | ✅ Ola 3 |
| 6 | Doble vía (motor) — falta la UI | ✅ motor · ⬜ UI — Ola 3 |
| 7 | Selector de alcance (dos selectores, confirmado) | ⬜ Ola 3 |
| 10 | Flag de revisión manual (el modelo ya lo transporta) | ⬜ Ola 3 |
| 8, 9 | Chunking semántico y papel de trabajo | Ola 4 |

Detalle y criterios de aceptación en `PLAN_MEJORAS_ANEXO.md`.

---

## Pruebas

```bash
pytest -q                 # suite rápida: 261 passed, 1 skipped, sin red ni modelos
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
| **Fase 6** | **38–52** | **Verificación de subsanaciones** — cada celda demuestra un defecto corregido, contrastándolo con el comportamiento anterior. Corre en segundos con el corpus sintético: no necesita `document_test/` ni un modelo vivo |
| **Fase 7** | **53–65** | **Doble vía y modelo de cobertura (Ola 3)** — `run_dual()`, `CoverageLink`/`LinkTable`, la alerta de cobertura que solo la Vía 2 puede producir, y la verificación de que el costo es la suma de las dos vías, no el producto. Corpus sintético, no necesita `document_test/` |

> **Nota Fase 1.1:** la celda itera sobre `NORMATIVA_DIR.glob("*.pdf")` y por defecto solo
> procesa los PDFs con caché Docling en `output/docling/*.md` (hoy 5 de 9; faltan los
> `L1-XVI-cap-*`). `CONVERTIR_SIN_CACHE = True` los convierte en vivo forzando
> `device="cpu"` para evitar el segfault MPS — más lento, pero seguro.
>
> Estos ajustes de la Fase 1.1 (rutas, guardas de caché) son detalles de robustez para
> probar el pipeline end-to-end sin levantar la UI; no son parte de los ítems del plan.

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
from pathlib import Path
from src import NormativaParser
import pandas as pd

CACHE_DIR = Path("output/docling")
parser = NormativaParser(cache_dir=str(CACHE_DIR))  # lee caché, 0 conversiones

# Los documentos se leen del directorio, no de una lista quemada — así una normativa
# nueva no exige tocar este ejemplo. Por defecto solo se procesan los que ya tienen
# caché Docling (ver "Nota Fase 1.1" arriba).
pdfs = [p for p in sorted(Path("Normativa2026").glob("*.pdf"))
        if (CACHE_DIR / f"{p.stem}.md").exists()]
frames = [parser.parse_pdf(p) for p in pdfs]
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

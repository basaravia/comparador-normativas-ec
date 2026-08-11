# Plan de trabajo — Ítems 1 a 10 del Anexo + backends multi-proveedor

> **Estado: PROPUESTA — pendiente de aprobación.** Ninguna rama ni código se ha creado todavía.
> Fuentes: `Informe_Consolidado_Comparador_Normativo.docx` (versión actualizada, con la
> definición completa de la "doble vía") + sus 5 capturas de pantalla · solicitud del usuario
> del 4-ago-2026 sobre proveedores de nube (ítem P).
> Repo: `normativas-ecuador-2026`, base actual `feature/streamlit-ui` (commit `befa7ef`).

---

## 1. Qué pide el anexo (ítems 1–10)

| # | Ítem | Blq. | Prioridad | Dependencia |
|---|------|------|-----------|-------------|
| 1 | Detener el proceso cuando falle la conexión al modelo (no marcar todo `no_aplica` con el error embebido) | B | Alta | — |
| 2 | Corregir desincronización de estado al refrescar/cambiar de pestaña en una corrida | C | Alta | — |
| 3 | Checkpoints y recuperación de procesos largos interrumpidos | C | Alta | — |
| 4 | Validar modelos disponibles (list models al DMR) + no asumir "todo relevante" al fallar el parseo del grading | B | Alta | — |
| 5 | Modelo de datos artículo↔sección **N:N** en proceso y resultado | A | Alta | — |
| 6 | **Análisis en doble vía**: (1) por sección del manual → cumplimiento + alerta; (2) por artículo de la normativa → cobertura/adopción + brechas | A | Alta | Ítem 5 |
| 7 | Selector de alcance por lista (artículos/secciones), no solo por cantidad | A/B | Alta | Pto. pendiente 1 |
| 8 | Chunking semántico por sección + pruebas de retrieval en español | B | Alta | — |
| 9 | Plantilla de exportación a Excel en formato "Papel de Trabajo" | D | Alta | Ítems 5 y 6 |
| 10 | Flag de revisión manual para artículos/secciones sin cumplimiento evidente (ambas vías) | A | Media-Alta | Ítems 5 y 6 |

**Premisa no negociable del Bloque A:** el 100 % de la normativa debe quedar cubierto por
algún control del manual. Eso es exactamente lo que la Vía 2 debe verificar y alertar.

### Añadido fuera del anexo

| # | Ítem | Prioridad | Origen |
|---|------|-----------|--------|
| **P** | **Backends multi-proveedor**: alternativas de nube a DMR (Azure AI Foundry, Groq, Vertex AI) para LLM y embeddings, con `.env` para endpoints y credenciales | Alta (habilitante) | Solicitud del usuario, 4-ago-2026 |

No está en el anexo, pero es **habilitante del ítem 4**: `list models` es específico de cada
proveedor. Si el registro de modelos se construye solo contra DMR, hay que reescribirlo
después. Por eso va **antes** del ítem 4 en la Ola 1.

---

## 2. Diagnóstico del repo (verificado en código)

### 2.1 Confirmaciones de los bugs reportados

| Ítem | Causa raíz localizada | Evidencia |
|------|----------------------|-----------|
| 1 | `analyze_comparison()` captura **toda** excepción y devuelve `nivel_cumplimiento="no_aplica"` con el error dentro de `analisis_general` | `src/llm_grader.py:293-299` |
| 1 | `DocumentComparator.run()` captura la excepción por fila y la sustituye por `_empty_result()`, que también es `no_aplica` | `src/comparator.py:91-93`, `src/comparator.py:222-238` |
| 1 | No hay cancelación: el `ThreadPoolExecutor` sigue enviando las filas restantes aunque el modelo ya no responda | `src/comparator.py:81-98` |
| 4 | Al fallar el parseo del grading: `logger.warning(... "Se asumen todos relevantes")` y devuelve `relevante=True` para todos | `src/llm_grader.py:235-237` |
| 4 | Aun con parseo exitoso, un candidato cuyo `element_id` no aparezca en la respuesta queda `relevante=True` por defecto | `src/llm_grader.py:243-248` |
| 4 | `_check_dmr()` solo comprueba `status_code==200` de `/models`; **no** lee la lista ni valida que el modelo configurado exista | `streamlit_app.py:60-68` |
| 4 | Los modelos del sidebar son constantes hardcodeadas, no la lista real del DMR | `streamlit_app.py:91-114` |
| 2 | La corrida es **bloqueante dentro del script-run** de Streamlit: al refrescar, la sesión nueva nace vacía mientras los hilos siguen vivos en el proceso | `streamlit_app.py:352-406` |
| 2 | El handler de logs escribe en `st.session_state` desde hilos worker (sin `ScriptRunContext`) y falla en silencio → el panel "Registro de ejecución" queda vacío | `app/logging_utils.py:30-38` |
| 3 | No existe persistencia parcial: `results_df` solo se materializa al terminar el `run()` completo | `src/comparator.py:98` |
| 5 | La relación artículo↔sección se **aplana a strings** al exportar; se pierde la trazabilidad N:N | `src/comparator.py:240-259` |
| 7 | Solo hay cantidad (`n_sample`) y la selección es **aleatoria** (`sample(random_state=42)`) | `streamlit_app.py:336-340`, `streamlit_app.py:355` |
| 8 | La normativa se trocea solo por regex de artículo, con truncado duro a 3000 caracteres; no hay chunking semántico ni evaluación de retrieval | `src/document_parser.py:309-333` |
| 9 | `export_excel()` produce una sola hoja plana; no es un papel de trabajo ni es configurable | `src/comparator.py:111-165` |

### 2.2 Tres defectos adicionales encontrados, no listados en el informe

Son de bajo costo y alto impacto sobre la calidad de los resultados. Propongo corregirlos
en la Ola 1 (rama `fix/config-wiring`), porque los ítems 6 y 10 dependen de que los
umbrales funcionen de verdad.

1. **El slider "Score semántico mínimo" no tiene efecto en la corrida.**
   `_process_row()` llama `semantic_search(embed_text, top_k=...)` sin `min_score`
   (`src/comparator.py:178`), así que usa el valor de `config.py` (0.30), no el del sidebar.
   `DocumentComparator.__init__` ni siquiera recibe el umbral (`streamlit_app.py:366-371`).
   El informe pide que la alerta de la Vía 1 se apalanque "en los umbrales de similitud ya
   existentes en la app" — hoy ese control es decorativo fuera de la pestaña 2.

2. **`lexical_scan()` cruza artículos entre normativas distintas.**
   Compara solo por `numero` sobre el `normativa_df` completo (`src/search_engine.py:201-220`).
   Con varias normas cargadas, un "Art. 5" del manual matchea el Art. 5 de *todas* ellas.
   Con el modelo N:N (ítem 5) esto se vuelve crítico: genera aristas falsas de cobertura.

3. **Los prefijos del backend local se anulan.**
   `NormativaIndex.build()` y `semantic_search()` fuerzan `prefix=""`
   (`src/search_engine.py:99`, `src/search_engine.py:136`), pero
   `SentenceTransformersEmbeddings` usa `intfloat/multilingual-e5-large`, que **requiere**
   `passage: ` / `query: `. El backend local rinde por debajo de su capacidad. Entra dentro
   del ítem 8 (calidad de retrieval en español).

4. **El índice FAISS persistido no registra con qué modelo se generó.**
   `save()` escribe `index.faiss` + `normativa_meta.json` y nada más
   (`src/search_engine.py:107-122`). Hoy el daño se limita a un error críptico de dimensión.
   Con proveedores de nube el riesgo cambia de naturaleza: dos modelos distintos de **la misma
   dimensión** (1536 es un valor muy común) cargan sin protestar y devuelven vecinos sin
   sentido, en silencio. Se corrige dentro del ítem P.

---

## 3. Decisiones y supuestos

| # | Punto | Decisión propuesta |
|---|-------|--------------------|
| S1 | **Punto pendiente 1 del informe** (¿un selector o dos?) | **Dos selectores**, uno por vía: alcance normativo (artículos) y alcance del manual (secciones). La doble vía del Bloque A lo vuelve necesario: la Vía 2 se define sobre artículos y la Vía 1 sobre secciones. El campo "Número de secciones a analizar" se conserva como preset "Muestra rápida". Si el negocio confirma otra cosa, solo cambia la UI de la pestaña 3, no el motor. |
| S2 | Estado de fila fallida | Se introduce `estado_analisis` (`ok` / `error_modelo` / `error_parseo` / `omitido`) **separado** de `nivel_cumplimiento`. Un fallo técnico nunca vuelve a expresarse como `no_aplica`. |
| S3 | Costo de la Vía 2 | Las aristas N:N se comparten entre vías y el grading se cachea por par `(articulo, seccion)`. La Vía 2 solo gasta LLM en el veredicto por artículo y en la búsqueda inversa de artículos sin aristas. Sin esto, el costo se duplicaría. |
| S4 | Alcance de este plan | Ítems 1–10 **+ ítem P**. Los ítems 11–18 (limpieza de portada/índice, UX no técnico, contraste del sidebar, hilos por backend, VLM, módulo E, costos) quedan fuera; se anotan como *follow-up* al final. |
| S5 | Compatibilidad | `master.ipynb` sigue funcionando: los métodos actuales (`run()`, `export_excel()`) se mantienen como fachada sobre la nueva arquitectura. |
| S6 | Hardware | Todo se diseña para M1 16 GB con DMR local: `max_workers` bajo, checkpoints frecuentes, evaluación de retrieval sin LLM. La nube levanta ese techo, pero **no puede ser un requisito**. |
| S7 | Proveedor por defecto | **DMR local sigue siendo el default.** La nube es opt-in y no debe poder activarse por accidente: exige proveedor explícito en el sidebar *y* credenciales presentes en `.env`. |
| S8 | LLM y embeddings se eligen por separado | **Groq no ofrece API de embeddings.** La app ya tiene dos secciones distintas en el sidebar; se formaliza que el proveedor de LLM y el de embeddings son independientes y combinables (p. ej. LLM en Groq + embeddings en DMR local). |
| S9 | Reranker | Sigue siendo **local** (`CrossEncoder`) con cualquier proveedor. Ninguno de los tres candidatos de nube expone reranking en su API de forma homogénea, y el reranker local ya funciona. |

---

## 4. Arquitectura objetivo

```text
┌───────────────────────────────────────────────────────────────────────────┐
│  FASE 1 — Tabulación                    src/document_parser.py            │
│  NormativaParser → normativa_df (1 fila = 1 artículo)                     │
│  ManualParser    → manual_df   (1 fila = 1 sección)                       │
│         + NUEVO  src/chunking.py → sub-chunks semánticos por artículo     │
│                  (parent-child: se recupera el chunk, se devuelve el art.)│
└───────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌───────────────────────────────────────────────────────────────────────────┐
│  FASE 2 — Índices                       src/search_engine.py (refactor)   │
│  SemanticIndex (genérico)                                                 │
│    ├── NormativaIndex  → artículos       (Vía 1: sección → artículos)     │
│    └── ManualIndex     → secciones NUEVO (Vía 2: artículo → secciones)    │
└───────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌───────────────────────────────────────────────────────────────────────────┐
│  FASE 3 — Doble vía                     src/comparator.py (refactor)      │
│                                                                           │
│   Vía 1  sección → artículos      Vía 2  artículo → secciones             │
│   ────────────────────────        ────────────────────────────            │
│   cumple/parcial/omisión           cubierto/parcial/no_cubierto           │
│   + alerta de incumplimiento       + brechas de cobertura                 │
│           │                                 │                             │
│           └────────────┬────────────────────┘                             │
│                        ▼                                                  │
│         src/coverage.py  ← NUEVO: tabla de aristas N:N                    │
│         CoverageLink(articulo_id, seccion_id, origen, scores, veredicto)  │
│         · vista_manual_df     (agregado por sección)   → Vía 1            │
│         · vista_normativa_df  (agregado por artículo)  → Vía 2            │
│         · cobertura_global    (% artículos cubiertos, brechas)            │
└───────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌───────────────────────────────────────────────────────────────────────────┐
│  FASE 4 — Entregable                    src/papel_trabajo.py ← NUEVO      │
│  Excel multi-hoja dirigido por plantilla templates/papel_trabajo.yaml     │
│  Resumen · Vía 1 · Vía 2 · Matriz N:N · Revisión manual · Trazabilidad    │
└───────────────────────────────────────────────────────────────────────────┘

Transversal:
  src/errors.py         ← taxonomía de errores (fail-fast vs. degradado)
  src/model_registry.py ← list/validate models, por proveedor
  src/checkpoint.py     ← persistencia incremental + reanudación
  src/scope.py          ← filtros de alcance (puros, testeables)
  app/run_manager.py    ← corridas en background a nivel de proceso + re-attach

┌───────────────────────────────────────────────────────────────────────────┐
│  CAPA DE PROVEEDORES (ítem P)          src/providers.py + src/settings.py │
│                                                                           │
│   .env  ──►  Settings  ──►  ProviderSpec ──┬─► build_chat_model()         │
│   (endpoints, claves)   ▲                  ├─► build_embedding_backend()  │
│                         │                  ├─► list_models()              │
│              UI > env > .env > config.py   └─► capabilities               │
│                                                                           │
│   LLM          │ DMR (default) · Azure AI Foundry · Groq · Vertex AI      │
│   Embeddings   │ DMR (default) · Azure AI Foundry · Vertex AI · local ST  │
│   Reranker     │ siempre local (CrossEncoder)                             │
│                                                                           │
│   Groq no expone embeddings → LLM y embeddings se eligen por separado     │
└───────────────────────────────────────────────────────────────────────────┘
        │ consumen la capa: llm_grader.py · embeddings.py · model_registry.py
        ▼
```

---

## 5. Estrategia de ramas

### 5.1 Base

`main` está **20 commits por detrás** de `feature/streamlit-ui`. Antes de abrir trabajo nuevo:

1. **PR `feature/streamlit-ui` → `main`** (merge del baseline que ya funciona).
   Sin esto, el PR final de estos 10 ítems mezclaría el baseline con las mejoras y sería
   imposible de revisar.
2. Cortar la rama de integración desde `main`:

```bash
git checkout main && git pull
git checkout -b feature/comparador-v2
git push -u origin feature/comparador-v2
```

### 5.2 Ramas por ítem

Todas salen de `feature/comparador-v2` y vuelven ahí por PR. Al cerrar las tres olas, un
único PR `feature/comparador-v2` → `main`.

| Ola | Rama | Ítems | Depende de |
|-----|------|-------|-----------|
| 0 | `feature/comparador-v2` | integración | `main` |
| 1 | `fix/llm-failfast` | 1 | — |
| 1 | `feature/provider-backends` | **P** | `fix/llm-failfast` (comparte `src/errors.py`) |
| 1 | `feature/model-registry` | 4 | `feature/provider-backends` |
| 1 | `fix/config-wiring` | §2.2 (3 defectos extra) | — |
| 1 | `feature/run-manager` | 2 | — |
| 1 | `feature/run-checkpoints` | 3 | `feature/run-manager` |
| 2 | `feature/coverage-model` | 5 | Ola 1 integrada |
| 2 | `feature/dual-analysis` | 6 | `feature/coverage-model` |
| 2 | `feature/scope-selector` | 7 | `feature/coverage-model` |
| 2 | `feature/review-flag` | 10 | `feature/dual-analysis` |
| 3 | `feature/semantic-chunking` | 8 | — (paralelizable desde el día 1) |
| 3 | `feature/papel-trabajo` | 9 | `feature/dual-analysis` |

**Paralelizable de verdad:** `feature/semantic-chunking` (ítem 8) no toca ningún archivo de
las otras ramas salvo `document_parser.py`/`search_engine.py`; puede arrancar en paralelo con
la Ola 1 si hay una segunda persona o agente. `fix/config-wiring` también es independiente.

**Convención de commits:** la ya usada en el repo (`feat:`, `fix:`, `chore:`, `docs:`,
`refactor:`, `test:`).

---

## 6. Plan detallado por ítem

### Ítem 1 — Fail-fast ante caída del modelo · `fix/llm-failfast` · ~1.5 j

**Problema (captura 1 del informe):** las 5 secciones salen `no_aplica` con
`Error en análisis LLM: error while getting model "docker.io/ai/smollm2-vll…"` incrustado en
`analisis_general`. El auditor recibe un papel de trabajo que dice "no aplica" cuando en
realidad el modelo nunca respondió.

**Cambios**

- **NUEVO `src/errors.py`**
  ```
  ComparadorError
   ├─ LLMUnavailableError    # conexión, timeout, 5xx, "error while getting model" → ABORTA
   ├─ ModelNotFoundError     # el modelo no está en el DMR                          → ABORTA
   ├─ GradingParseError      # la respuesta no mapea al esquema                     → degrada 1 fila
   └─ RunAbortedError        # cancelación del usuario o abort en cascada
  ```
  Función `classify_llm_exception(exc) -> ComparadorError` que traduce las excepciones de
  `openai`/`httpx`/`langchain` en esta taxonomía.
- `src/llm_grader.py`: los `except Exception` de `analyze_comparison()` (`:293`) y
  `grade_candidates()` (`:235`) clasifican antes de decidir. Los errores de infraestructura
  se **relanzan**; solo los de contenido degradan la fila.
- `src/comparator.py`: `run()` distingue error de fila (se registra con
  `estado_analisis="error_parseo"`) de error de infraestructura → cancela los futures
  pendientes (`executor.shutdown(cancel_futures=True)`), marca las filas no procesadas como
  `omitido` y relanza `LLMUnavailableError`.
- `_empty_result()` deja de usar `no_aplica`: `nivel_cumplimiento=None` +
  `estado_analisis="error_*"`.
- `streamlit_app.py`: `st.error()` explícito con el modelo, la URL y cuántas secciones
  quedaron sin procesar; los resultados parciales se conservan y se etiquetan como parciales.
- **Umbral de tolerancia configurable:** `max_fallos_consecutivos` (default 3) — tres fallos
  de fila seguidos también abortan.

**DoD**
- Con el DMR apagado, la corrida se detiene en < 15 s con mensaje claro; ninguna fila queda
  como `no_aplica`.
- El Excel/JSON nunca contiene un mensaje de error dentro de `analisis_general`.

**Tests** — `tests/test_failfast.py`: grader falso que lanza `APIConnectionError` →
`comparator.run` relanza `LLMUnavailableError`; grader que falla solo en la fila 2 →
la corrida termina y esa fila queda `estado_analisis="error_parseo"`.

---

### Ítem P — Backends multi-proveedor + `.env` · `feature/provider-backends` · ~2 j

**Por qué va antes del ítem 4:** el "list models" del ítem 4 es distinto en cada proveedor
(DMR y Azure OpenAI exponen endpoint de listado; Groq también vía su API compatible con
OpenAI; Vertex AI **no** tiene un equivalente directo y necesita catálogo estático). Construir
el registro contra DMR y adaptarlo después es reescribirlo.

**Estado actual:** todo está cableado a DMR. `LLMGrader.__init__` instancia
`ChatOpenAI(base_url=..., api_key="ignored")` directamente (`src/llm_grader.py:180-197`) y
`LangChainDMREmbeddings` hace lo propio con `OpenAIEmbeddings`
(`src/embeddings.py:56-65`). **No hay una sola lectura de variables de entorno en el código**
(`src/`, `app/`, `streamlit_app.py`): `python-dotenv` está declarado en
`dependencies/requirements.txt` pero nunca se usa, y `config.py` tiene los endpoints
hardcodeados. `.env` ya está en `.gitignore`.

**Cambios**

- **NUEVO `src/settings.py`**
  - Carga `.env` con `python-dotenv` (ya declarado, hoy sin usar).
  - Precedencia explícita: **UI > variable de entorno > `.env` > defaults de `config.py`**.
  - `config.py` deja de ser fuente de credenciales; conserva solo defaults no sensibles.
  - `redact(valor)` para claves y URLs con token — se usa en logs, panel de ejecución y hoja
    de trazabilidad. **Ninguna credencial puede llegar a `output/logs/run_*.log` ni al Excel.**

- **NUEVO `src/providers.py`**
  ```python
  class Provider(StrEnum):
      DMR          = "dmr"            # local, por defecto
      AZURE_OPENAI = "azure_openai"   # Foundry — deployments de Azure OpenAI
      AZURE_AI     = "azure_ai"       # Foundry — catálogo serverless
      GROQ         = "groq"
      VERTEX       = "vertex"
      LOCAL_ST     = "local_st"       # sentence-transformers (solo embeddings)

  @dataclass(frozen=True)
  class ProviderCapabilities:
      chat: bool
      embeddings: bool
      listado_modelos: bool
      salida_estructurada: str        # json_schema | function_calling | prompt
      concurrencia_recomendada: int   # 1 (DMR local) … 8–16 (nube)
      timeout_s: int
      max_retries: int
      requiere_env: tuple[str, ...]
      costo_1m_tokens: tuple[float, float] | None   # (entrada, salida)
  ```
  Fábricas: `build_chat_model(spec)`, `build_embedding_backend(spec)`, `list_models(spec)`,
  `validate(spec)` → `ProviderConfigError` con la lista exacta de variables que faltan.

  | Proveedor | Chat | Embeddings | Autenticación |
  |-----------|------|-----------|---------------|
  | DMR | `ChatOpenAI(base_url)` | `OpenAIEmbeddings(base_url)` | ninguna |
  | Azure OpenAI (Foundry) | `AzureChatOpenAI` | `AzureOpenAIEmbeddings` | `AZURE_OPENAI_API_KEY` o `DefaultAzureCredential` |
  | Azure AI Foundry (serverless) | `AzureAIChatCompletionsModel` | según el modelo | `AZURE_AI_ENDPOINT` + `AZURE_AI_API_KEY` |
  | Groq | `ChatGroq` | ✗ **no ofrece** | `GROQ_API_KEY` |
  | Vertex AI | `ChatVertexAI` | `VertexAIEmbeddings` (`text-multilingual-embedding-002`, fuerte en español) | ADC / `GOOGLE_APPLICATION_CREDENTIALS` + `project` + `location` |

- **NUEVO `.env.example`** (commiteado, sin valores) con todas las claves documentadas.
  `.env` ya está ignorado por git — se verifica en CI que no se cuele.

- `src/llm_grader.py`: `LLMGrader` recibe un `BaseChatModel` inyectado (o un `ProviderSpec`)
  en vez de construir `ChatOpenAI`. Los `timeout`/`max_retries` hardcodeados (120/180 s,
  `max_retries=0`, calibrados para gemma4 en M1) pasan a venir del `ProviderSpec`: en nube
  conviene timeout más corto y 2 reintentos con backoff.

- `src/embeddings.py`: **NUEVO** `LangChainEmbeddingsAdapter`, que envuelve cualquier objeto
  `Embeddings` de LangChain en la interfaz `EmbeddingBackend` existente (batching +
  normalización L2). `LangChainDMREmbeddings` pasa a ser un caso particular. Azure y Vertex
  entran sin código nuevo por proveedor.

- `src/search_engine.py`: `save()` escribe `index_meta.json` con `proveedor + modelo + dim +
  fecha`; `load()` rechaza cargar si no coincide con el backend activo (§2.2, defecto 4).

- `streamlit_app.py`: selector de proveedor **independiente** para LLM y para embeddings, con
  indicador de credenciales (`🟢 configurado` / `🔴 faltan AZURE_OPENAI_API_KEY`). Las claves
  se leen de `.env`; si se permite introducirlas por UI, es con `type="password"` y sin
  persistirlas. Seleccionar Groq como proveedor de embeddings es imposible por capacidades.

- **Dependencias opcionales:** `dependencies/requirements-cloud.txt` con `langchain-groq`,
  `langchain-google-vertexai` y `langchain-azure-ai`. **No entran al entorno base** de M1
  16 GB; import perezoso con mensaje claro de qué instalar si falta. Azure OpenAI no necesita
  nada nuevo (`langchain-openai` ya lo trae) y `azure-identity`/`azure-core` ya están en el
  entorno.

**Efectos colaterales que salen casi gratis**

- **Ítem 15 del anexo** (rango de "Hilos concurrentes" según backend): con
  `concurrencia_recomendada` en el `ProviderSpec`, el slider ajusta su rango y valor sugerido
  al proveedor activo. Queda cubierto de hecho.
- **Ítem 18 del anexo** (costos estimados): `costo_1m_tokens` + el contador de llamadas del
  ítem 6 dan la estimación por corrida sin trabajo adicional.

**DoD**
- Cambiar de DMR a Azure AI Foundry (o Groq, o Vertex) sin tocar código: solo `.env` + sidebar.
- Combinación mixta funcionando: LLM en Groq + embeddings en DMR local.
- `grep` sobre `output/logs/`, el JSON y el Excel de una corrida en nube: **cero credenciales**.
- Un índice FAISS construido con un modelo y cargado con otro se rechaza con mensaje explícito.
- Sin `requirements-cloud.txt` instalado, la app arranca igual y explica qué falta al elegir
  un proveedor de nube.

**Tests** — `tests/test_providers.py` (construcción por proveedor con env mockeado, error
claro por credenciales faltantes, Groq+embeddings rechazado por capacidades, precedencia
UI > env > `.env` > default), `tests/test_settings_redaction.py` (ninguna clave sobrevive a
`redact`, ni en logs ni en la hoja de trazabilidad), `tests/test_index_meta.py` (rechazo por
modelo distinto). Todo sin red: las fábricas se mockean.

---

### Ítem 4 — Validación de modelos + grading sin falsos positivos · `feature/model-registry` · ~2 j

**Problema (capturas 3 y 4):** `Field required: candidatos … Got 1 validation error for
GradingResult … Se asumen todos relevantes.` Al cambiar de modelo, el parseo falla y **todo
candidato pasa como relevante** — el riesgo espejo del ítem 1: allí se pierden secciones,
aquí se cuelan falsos positivos de cumplimiento.

**Cambios**

- **NUEVO `src/model_registry.py`** — construido **sobre la capa de proveedores del ítem P**,
  no contra DMR directamente.
  - `list_models(spec) -> list[ModelInfo]`, delegando en `providers.list_models`: endpoint de
    listado en DMR / Azure OpenAI / Groq, y catálogo estático versionado para Vertex AI, que
    no expone un equivalente.
  - `validate_model(spec, model_id)` → `ModelNotFoundError` con la lista de modelos
    disponibles **de ese proveedor** en el mensaje.
  - `preflight(config)` → verifica credenciales, LLM **y** modelo de embeddings antes de
    arrancar; con caché corta (TTL 15 s) para no golpear el proveedor en cada rerun.
- `streamlit_app.py`: el `selectbox` de modelo LLM y el de embeddings se pueblan desde
  `list_models()` del proveedor activo, con fallback a las constantes de `config.py` si no
  responde. El botón "Ejecutar comparación" queda deshabilitado si el preflight falla.
- `src/llm_grader.py`, robustez del grading en tres niveles:
  1. `OutputFixingParser` (LangChain) como reintento de reparación del JSON.
  2. Reintento con prompt simplificado (sin `format_instructions` largas) para modelos chicos.
  3. Si aún falla → `GradingParseError`: los candidatos quedan
     `relevante=None`, `requiere_revision=True`, `motivo="grading_no_parseable"`.
     **Nunca `True`.**
- Igual criterio en `:243-248`: un candidato ausente de la respuesta ya no se asume relevante.
- El estado degradado viaja hasta la UI y el Excel (enlaza con el ítem 10).

**DoD**
- Configurar un modelo inexistente → error antes de gastar un solo token, con la lista real
  de modelos disponibles.
- Forzar un fallo de parseo → 0 candidatos marcados `relevante=True` por defecto; la fila
  aparece en la hoja "Revisión manual".

**Tests** — `tests/test_model_registry.py` (respuestas `/models` mockeadas con `respx`/monkeypatch),
`tests/test_grading_degradation.py` (LLM falso que devuelve JSON inválido).

---

### Ítem 2 — Sincronía de estado de la corrida · `feature/run-manager` · ~2.5 j

**Problema:** la corrida bloquea el script-run. Al refrescar, Streamlit crea una sesión nueva
con `session_state` vacío mientras los hilos siguen vivos → la terminal avanza y la web
muestra "En espera…".

**Cambios**

- **NUEVO `app/run_manager.py`**
  - `RunHandle`: `run_id`, `estado` (`pendiente|corriendo|abortando|completado|fallido`),
    `progreso`, `total`, `iniciado_en`, `config_hash`, `cancel_event`, `error`.
  - Registro **a nivel de proceso** (no de sesión), protegido por lock.
  - `start_run(config, scope) -> run_id` lanza la corrida en un hilo propio con
    `streamlit.runtime.scriptrunner.add_script_run_ctx` cuando aplique.
  - `get_active_runs()`, `attach(run_id)`, `cancel(run_id)`.
  - Espejo en disco: `output/runs/<run_id>/state.json` (permite detectar corridas huérfanas
    incluso tras reiniciar el proceso de Streamlit).
- `streamlit_app.py`: `session_state` guarda **solo** `run_id`. Al cargar, si hay una corrida
  activa se re-adjunta y muestra progreso real. Refrescar o cambiar de pestaña ya no crea una
  corrida nueva; el botón "Ejecutar" se convierte en "Cancelar" mientras haya una activa.
- Polling con `@st.fragment(run_every="2s")` (Streamlit 1.59 lo soporta) en vez de escribir
  widgets desde el callback.
- `app/logging_utils.py`: buffer `deque` de proceso por `run_id` en lugar de
  `st.session_state`, así los logs de los hilos worker sí llegan al panel.

**DoD**
- Con una corrida en marcha: F5 → la barra sigue en el mismo punto; cambiar de pestaña y
  volver → idem; abrir una segunda pestaña del navegador → ve la misma corrida.
- No es posible lanzar dos corridas simultáneas sobre la misma configuración.

**Tests** — `tests/test_run_manager.py` (ciclo de vida, cancelación, re-attach tras limpiar
`session_state`), más un caso en `tests/test_streamlit_app_smoke.py` con `AppTest`.

---

### Ítem 3 — Checkpoints y reanudación · `feature/run-checkpoints` · ~2 j

**Cambios**

- **NUEVO `src/checkpoint.py`**
  - `CheckpointStore(run_dir)`: `manifest.json` (config, hashes de documentos, alcance,
    versión de esquema) + `rows.jsonl` (append por unidad completada, escritura atómica).
  - `completed_ids()`, `append(unidad, resultado)`, `load_partial() -> DataFrame`.
  - Invalidación: si cambian el hash de los documentos, el modelo o el alcance, la corrida
    no es reanudable (se avisa y se ofrece empezar de cero).
- `DocumentComparator.run(..., checkpoint=None)`: salta las unidades ya completadas y hace
  `append` en cada `progress_callback`.
- UI, pestaña 3: sección "Corridas reanudables" con `run_id`, fecha, avance
  (`142/380`) y botón "Reanudar". Al terminar, el `run_dir` se conserva para trazabilidad.
- Purga configurable de corridas antiguas (default: conservar 20).

**DoD**
- Matar el proceso de Streamlit a mitad de corrida y reanudar → no se repite ninguna llamada
  LLM ya completada y el resultado final es idéntico al de una corrida ininterrumpida.

**Tests** — `tests/test_checkpoint.py`: reanudación tras interrupción simulada, invalidación
por cambio de configuración, resistencia a un `rows.jsonl` truncado.

---

### Ítem 5 — Modelo de datos N:N · `feature/coverage-model` · ~3 j

**Problema:** hoy el resultado es un DataFrame con una fila por sección del manual y los
artículos aplanados a texto (`src/comparator.py:240-259`). No se puede responder "¿qué
secciones cubren el Art. 35?" sin volver a correr todo. El informe además sube el requisito
de 1:N a **N:N**: una sección puede tener que satisfacer artículos de varias normas a la vez.

**Cambios**

- **NUEVO `src/coverage.py`**
  ```python
  @dataclass(frozen=True)
  class CoverageLink:
      articulo_element_id: str   # incluye doc_id → soporta varias normativas
      articulo_doc_id: str
      articulo_numero: str
      seccion_chunk_id: str
      seccion_doc_id: str
      seccion_jerarquia: str
      origen: str                # lexico | semantico_v1 | semantico_v2 | manual
      score_semantico: float | None
      score_reranker: float | None
      score_grade: float | None
      relevante: bool | None     # None = no determinado (ver ítem 4)
      razon: str
  ```
  - `LinkTable`: contenedor con `upsert()` (dedupe por `(articulo, seccion)`, conserva el
    mejor score y acumula orígenes), `to_dataframe()`, `save()/load()`.
  - Agregaciones: `vista_manual(link_table, ...)`, `vista_normativa(link_table, ...)`,
    `cobertura_global(...)` → `% artículos cubiertos`, `artículos sin cobertura`.
- `src/comparator.py`: `_process_row()` deja de aplanar; emite `CoverageLink`s.
  `run()` devuelve un `ComparisonBundle(links, vista_manual, vista_normativa, cobertura,
  metadatos)`. `results_df` se mantiene como propiedad derivada para no romper `master.ipynb`.
- **Corrección incluida:** `lexical_scan()` acota el match por `doc_id`/norma mencionada para
  no generar aristas cruzadas entre normativas (§2.2, defecto 2).
- Persistencia: `output/comparador/links.parquet` + `coverage.json`.

**DoD**
- Consulta directa en ambos sentidos: `links.query("articulo_numero=='35'")` devuelve todas
  las secciones que lo cubren, con score y origen.
- Con dos normativas cargadas, ningún artículo de la norma A aparece ligado por vía léxica a
  una sección que citaba la norma B.

**Tests** — `tests/test_coverage_model.py`: dedupe, agregaciones en ambos sentidos, cálculo de
cobertura, aislamiento entre documentos, round-trip de persistencia.

---

### Ítem 6 — Análisis en doble vía · `feature/dual-analysis` · ~4 j

**Es el corazón del informe.** El cambio es de lógica de comparación (Fase 3), no de parsing.

**Vía 1 — manual → normativa** (evolución de lo existente)
Por cada sección del manual en alcance: recuperar artículos candidatos de **todas** las
normativas cargadas, graduar, analizar. Si no cumple → alerta con *qué* artículos no satisface
y *por qué*, apoyada en los umbrales de la app (`min_semantic_score`, `faiss_top_k`,
`reranker_top_n` — ver la corrección de §2.2 defecto 1, sin la cual el umbral no se aplica).
Unidad de resultado: **la sección del manual**.

**Vía 2 — normativa → manual** (nueva)
Por cada artículo en alcance: ¿está cubierto por alguna sección del manual? Se necesita un
índice inverso.

**Cambios**

- `src/search_engine.py` → refactor a `SemanticIndex` genérico (parametrizado por
  `text_col`/`id_col`); `NormativaIndex` y **`ManualIndex`** quedan como subclases finas.
  API pública actual intacta.
- `src/comparator.py`:
  - `run_via_manual(...)` — Vía 1.
  - `run_via_normativa(...)` — Vía 2: busca secciones por artículo sobre `ManualIndex`,
    gradúa (reusando la caché de grading), y emite un veredicto por artículo:
    `nivel_adopcion ∈ {cubierto, parcial, no_cubierto, no_aplica}` + `brechas` +
    `secciones_que_lo_cubren`.
  - `run_dual(...)` — orquesta ambas y consolida sobre la misma `LinkTable`.
  - **Caché de grading** por `(articulo_element_id, seccion_chunk_id)` compartida entre vías:
    evita duplicar el gasto de LLM (supuesto S3).
- **Alerta de cobertura:** al cerrar, si `cobertura_global < 100 %`, la UI muestra un banner
  rojo con el conteo y el listado de artículos sin cobertura, y el dato entra al papel de
  trabajo. Es la premisa no negociable del Bloque A.
- Nuevo esquema Pydantic `AdopcionResult` en `llm_grader.py` para el veredicto por artículo
  (paralelo a `ComparisonResult`, que se conserva para la Vía 1).
- UI, pestaña 4: dos sub-pestañas — "Por sección (Vía 1)" y "Por artículo (Vía 2)" — más una
  tarjeta de cobertura global.

**DoD**
- Una corrida produce las dos vistas y el % de cobertura sobre el alcance seleccionado.
- Un artículo sin ninguna sección relacionada aparece como `no_cubierto` y dispara la alerta.
- El número de llamadas LLM ≈ `|secciones| + |artículos|` (no el producto), verificable con un
  contador en los logs.

**Tests** — `tests/test_dual_analysis.py` con grader falso determinista: cobertura 100 %,
cobertura parcial, artículo huérfano, sección que satisface artículos de dos normas distintas,
y verificación del reuso de caché (conteo de invocaciones).

---

### Ítem 7 — Selector de alcance por lista · `feature/scope-selector` · ~1.5 j

**Supuesto S1: dos selectores.**

**Cambios**

- **NUEVO `src/scope.py`** (funciones puras, sin Streamlit)
  - `filtrar_articulos(normativa_df, doc_ids, numeros, secciones, incluir_referencias=False,
    tipos_elemento=...)`.
  - `filtrar_secciones(manual_df, doc_ids, jerarquias, chunk_ids)`.
  - `RunScope` (dataclass) serializable → entra en el `manifest.json` del checkpoint y en la
    hoja de trazabilidad del papel de trabajo.
- UI, pestaña 3 rediseñada:
  - **Alcance normativo**: multiselect de artículos con filtro por norma y por
    título/capítulo, búsqueda por número/epígrafe, presets "Todo el articulado" /
    "Excluir referencias" (usa `es_referencia`, ya existente) / "Solo disposiciones".
  - **Alcance del manual**: multiselect de secciones agrupadas por jerarquía.
  - "Muestra rápida (N)" se conserva como preset y deja de ser aleatoria: toma las primeras N
    del alcance vigente, con opción "aleatoria reproducible" explícita.
  - Contador en vivo: "42 artículos × 18 secciones · ~60 llamadas LLM · ~35 min estimados".

**DoD**
- Se puede correr exactamente "Art. 35 y 36 de la Ley X contra el capítulo 5 del manual" sin
  tocar código.
- El alcance queda registrado en el checkpoint y en el papel de trabajo.

**Tests** — `tests/test_scope.py` (filtros, presets, vacíos) + caso `AppTest` de la pestaña 3.

---

### Ítem 8 — Chunking semántico + evaluación de retrieval en español · `feature/semantic-chunking` · ~3 j

**Cambios**

- **NUEVO `src/chunking.py`**
  - `chunk_articulo(row, max_tokens)`: los artículos que exceden el presupuesto se subdividen
    respetando fronteras semánticas (numerales, literales, incisos — patrones ya presentes en
    los documentos ecuatorianos), con solape configurable.
  - Modelo **parent-child**: se indexa el sub-chunk, se devuelve el artículo padre. Preserva
    "el artículo como unidad de resultado" del Bloque A mientras mejora el recall.
  - Elimina el truncado ciego a 3000 caracteres de `document_parser.py:327`.
- `src/search_engine.py`: `build()` indexa sub-chunks y agrupa por `articulo_element_id` al
  devolver; **se restauran los prefijos** `passage:`/`query:` del backend local
  (§2.2, defecto 3).
- **Arnés de evaluación**
  - `tests/data/retrieval_gold_es.yaml`: 30–50 consultas en español (redactadas desde los
    manuales reales) con los artículos esperados.
  - `scripts/eval_retrieval.py`: recall@k, MRR, nDCG@10 por backend/configuración; salida a
    `output/eval/retrieval_<fecha>.json` + tabla comparativa en markdown.
  - `tests/test_retrieval_es.py` con marcador `@pytest.mark.retrieval` y umbral mínimo
    (recall@5 ≥ 0.80) que falla si una regresión lo baja.

**DoD**
- Tabla comparativa antes/después por configuración (chunking on/off, con/sin reranker,
  qwen3 vs. granite) con métricas reproducibles.
- La suite de retrieval corre sin LLM (solo embeddings), así que es barata de repetir.

**Tests** — los del arnés, más `tests/test_chunking.py` (fronteras, solape, integridad
padre-hijo, artículos cortos que no se subdividen).

---

### Ítem 9 — Papel de Trabajo (Excel) · `feature/papel-trabajo` · ~2.5 j

**Cambios**

- **NUEVO `src/papel_trabajo.py`** + **NUEVO `templates/papel_trabajo.yaml`**
  - La plantilla declara hojas, columnas, etiquetas, orden, anchos y formato condicional;
    cambiar el papel de trabajo no exige tocar código Python (requisito "plantilla
    configurable, campos genéricos").
  - Hojas propuestas:
    1. **Resumen** — entidad, normativas y manual evaluados, alcance, fecha, modelos usados,
       **% de cobertura** y semáforo por nivel.
    2. **Vía 1 — Manual** — una fila por sección: jerarquía, artículos aplicables, nivel de
       cumplimiento, análisis, brechas, prioridad.
    3. **Vía 2 — Normativa** — una fila por artículo: norma, número, epígrafe, nivel de
       adopción, secciones que lo cubren, brechas, prioridad.
    4. **Matriz N:N** — tabla de aristas artículo × sección con scores y origen.
    5. **Revisión manual** — solo lo marcado por el ítem 10, con el motivo.
    6. **Trazabilidad** — modelos, umbrales, `run_id`, hashes de documentos, duración, versión
       del código. Un papel de trabajo de auditoría tiene que ser reproducible.
  - Reutiliza el formato visual existente (`PatternFill` por nivel, `freeze_panes`, anchos) de
    `src/comparator.py:111-165`, que queda como fachada delegando aquí.
- Columna `prioridad` derivada de nivel + criticidad del artículo (heurística documentada y
  sobreescribible en la plantilla).

**DoD**
- El Excel se abre en Excel/LibreOffice sin advertencias, con las 6 hojas pobladas y navegables.
- Cambiar una etiqueta de columna en el YAML se refleja sin tocar Python.

**Tests** — `tests/test_papel_trabajo.py`: generación desde un bundle sintético, lectura de
vuelta con `openpyxl`, verificación de hojas/columnas/formato, y plantilla alterada.

---

### Ítem 10 — Flag de revisión manual · `feature/review-flag` · ~1 j

**Cambios**

- `src/coverage.py`: `requiere_revision_manual: bool` + `motivos_revision: list[str]` en ambas
  vistas. Disparadores:
  - score en la banda de indecisión (`min_semantic_score ± delta`, configurable);
  - `relevante is None` por fallo de parseo del grading (ítem 4);
  - conflicto entre coincidencia léxica y veredicto semántico;
  - artículo sin cobertura (Vía 2);
  - `nivel_cumplimiento == "parcial"` con brechas declaradas.
- UI: filtro "Solo revisión manual" en la pestaña 4 y contador destacado.
- Excel: hoja dedicada (ítem 9).
- **Explícito:** la herramienta marca y explica; no intenta resolver estos casos
  automáticamente, tal como pide el Bloque A.

**DoD** — Ninguna fila marcada para revisión aparece como veredicto cerrado en el resumen; la
hoja "Revisión manual" lista el motivo de cada una.

**Tests** — `tests/test_review_flag.py`: un caso por disparador.

---

## 7. Módulos: mapa de cambios

### Nuevos

| Archivo | Ítem | Propósito |
|---------|------|-----------|
| `src/errors.py` | 1, 4, P | Taxonomía de errores: abortar vs. degradar |
| `src/providers.py` | **P** | Fábricas y capacidades por proveedor (DMR, Azure, Groq, Vertex) |
| `src/settings.py` | **P** | Carga de `.env`, precedencia de configuración, redacción de secretos |
| `.env.example` | **P** | Plantilla de endpoints y credenciales (sin valores) |
| `dependencies/requirements-cloud.txt` | **P** | Extras opcionales de nube, fuera del entorno base |
| `src/model_registry.py` | 4 | `list_models` / `validate_model` / `preflight`, por proveedor |
| `src/checkpoint.py` | 3 | Persistencia incremental y reanudación |
| `src/coverage.py` | 5, 6, 10 | `CoverageLink`, `LinkTable`, vistas y cobertura |
| `src/scope.py` | 7 | Filtros de alcance (puros) |
| `src/chunking.py` | 8 | Sub-chunking semántico parent-child de artículos |
| `src/papel_trabajo.py` | 9 | Exportador Excel dirigido por plantilla |
| `app/run_manager.py` | 2, 3 | Corridas en background a nivel de proceso + re-attach |
| `templates/papel_trabajo.yaml` | 9 | Definición de hojas y columnas |
| `scripts/eval_retrieval.py` | 8 | CLI de evaluación de retrieval |
| `tests/data/retrieval_gold_es.yaml` | 8 | Gold set en español |

### Modificados

| Archivo | Ítems | Alcance del cambio |
|---------|-------|--------------------|
| `src/llm_grader.py` | 1, 4, 6, **P** | Clasificación de errores, grading robusto, `AdopcionResult`, chat model inyectado |
| `src/embeddings.py` | **P** | `LangChainEmbeddingsAdapter` genérico; DMR pasa a ser un caso particular |
| `src/comparator.py` | 1, 3, 5, 6 | Fail-fast, checkpoints, aristas N:N, `run_dual` |
| `src/search_engine.py` | 5, 6, 8, **P** | `SemanticIndex` genérico + `ManualIndex`, léxico por documento, prefijos, `index_meta.json` |
| `src/document_parser.py` | 8 | Integración del sub-chunking, sin truncado ciego |
| `src/config.py` | varios, **P** | Nuevos parámetros; deja de ser fuente de credenciales |
| `streamlit_app.py` | 1, 2, 3, 4, 6, 7, 10, **P** | Preflight, re-attach, reanudación, selectores, doble vía, filtros, selector de proveedor |
| `app/logging_utils.py` | 2, **P** | Buffer de proceso por `run_id`; redacción de secretos |
| `dependencies/requirements.txt` | **P** | `python-dotenv` pasa de declarado a usado |
| `README.md` | todos | Arquitectura, flujo y configuración de proveedores |
| `TODO.md` | todos | Reemplazado por el seguimiento de este plan |

---

## 8. Secuencia de ejecución

```
Ola 0 · Base                        ~0.5 j
  └─ PR feature/streamlit-ui → main + rama de integración

Ola 1 · Fiabilidad (ítems 1,P,4,2,3)  ~10 j  ← nada de lo demás es confiable sin esto
  ├─ fix/llm-failfast          (1)
  ├─ feature/provider-backends (P)   ← antes que el registry, o hay que reescribirlo
  ├─ feature/model-registry    (4)
  ├─ fix/config-wiring         (§2.2)
  ├─ feature/run-manager       (2)
  └─ feature/run-checkpoints   (3)

Ola 2 · Núcleo metodológico (5,6,7,10)  ~9.5 j
  ├─ feature/coverage-model  (5)
  ├─ feature/dual-analysis   (6)
  ├─ feature/scope-selector  (7)
  └─ feature/review-flag     (10)

Ola 3 · Calidad y entregable (8,9)  ~5.5 j
  ├─ feature/semantic-chunking (8)   ← puede arrancar en paralelo desde la Ola 1
  └─ feature/papel-trabajo     (9)

Total ≈ 25.5 jornadas en serie · ≈ 19 con el ítem 8 en paralelo
```

El ítem P añade ~2 jornadas a la Ola 1, pero descuenta trabajo después: cubre de hecho el
ítem 15 del anexo (hilos según backend) y deja el ítem 18 (costos) a un paso.

---

## 9. Riesgos

| Riesgo | Impacto | Mitigación |
|--------|---------|------------|
| La Vía 2 duplica el costo de LLM | Corridas de horas en M1 16 GB | Caché de grading compartida (S3) + selector de alcance (ítem 7) como control obligatorio |
| Indexar el manual sube el consumo de RAM | Segfault/OOM ya visto en el proyecto | Índices construidos en secuencia, nunca simultáneos; `EMBED_BATCH_SIZE` conservador; se mantiene el workaround `KMP_DUPLICATE_LIB_OK` |
| El refactor N:N rompe `master.ipynb` | Pérdida del flujo de trabajo actual | `results_df` y `export_excel()` se conservan como fachada (S5); prueba de regresión del notebook |
| Modelos pequeños (smollm2) no producen JSON válido | El ítem 4 degrada todo a "revisión manual" | El preflight advierte sobre modelos por debajo del mínimo recomendado; se documenta el mínimo viable |
| Punto pendiente 1 sin confirmar | Retrabajo en la UI de la pestaña 3 | La lógica va en `src/scope.py` (independiente de la UI); un cambio de criterio solo afecta widgets |
| El gold set de retrieval usa manuales confidenciales | Fuga de material corporativo | Las consultas se redactan parafraseadas y el gold set referencia solo IDs de artículos públicos; `document_test/` sigue en `.gitignore` |
| **Los manuales internos del banco salen a un proveedor de nube** | Riesgo de confidencialidad y de residencia de datos; puede ser un incumplimiento contractual | **El más serio del ítem P.** DMR local sigue siendo el default (S7); la nube es opt-in explícito; el sidebar advierte al activarla; el proveedor usado queda registrado en la hoja de trazabilidad del papel de trabajo. Combinación recomendada si hay dudas: embeddings locales + LLM en nube, o al revés. **Confirmar con Legal/Seguridad del banco antes de usar nube con documentos reales** |
| Fuga de credenciales en logs, JSON o Excel | Exposición de claves de API | `redact()` obligatorio en `logging_utils`, panel de ejecución y hoja de trazabilidad; prueba automatizada que falla si una clave sobrevive; `.env` ya ignorado por git |
| Costos de nube sin control en el pipeline completo | Factura inesperada | El estimador de costo (`costo_1m_tokens` + contador de llamadas) se muestra **antes** de ejecutar, junto al contador del selector de alcance (ítem 7) |
| Los SDK de nube rompen el entorno de M1 16 GB | Entorno inservible | `requirements-cloud.txt` separado, import perezoso; el entorno base no cambia |

---

## 10. Aceptación global (ítems 1–10 + P)

- [ ] El proveedor de LLM y el de embeddings se cambian sin tocar código (`.env` + sidebar),
      entre DMR, Azure AI Foundry, Groq y Vertex AI, incluso combinados entre sí.
- [ ] Ninguna credencial aparece en logs, panel de ejecución, JSON ni Excel.
- [ ] Con el DMR caído, ninguna corrida produce filas `no_aplica`: se detiene y lo dice.
- [ ] Ningún candidato se marca relevante por defecto ante un fallo de parseo.
- [ ] El modelo configurado se valida contra la lista real del DMR antes de arrancar.
- [ ] Refrescar el navegador durante una corrida no pierde ni duplica el progreso.
- [ ] Una corrida interrumpida se reanuda sin repetir llamadas LLM.
- [ ] La relación artículo↔sección es consultable N:N en ambos sentidos, con varias normativas.
- [ ] Cada corrida entrega las dos vías y el % de cobertura, con alerta explícita si < 100 %.
- [ ] El alcance se elige por lista (artículos y secciones), no solo por cantidad.
- [ ] Existe una medición reproducible de retrieval en español, con umbral de regresión.
- [ ] El Excel es un papel de trabajo configurable, con trazabilidad completa de la corrida.
- [ ] Los casos no evidentes quedan marcados para el auditor, con motivo, sin resolución automática.

---

## 11. Fuera de alcance (follow-up)

Ítems 11–18 del anexo, para una fase siguiente:
limpieza de portada/índice (11) · ciclo de corrección y etiquetado (12) · rediseño UX para
auditor no técnico y configuración avanzada (13) · **bug de contraste del sidebar (14)** —
causa localizada en `app/theme.py:73-75`, donde `section[data-testid="stSidebar"] * { color:
#EAF0F6 !important }` pinta también el texto de los inputs sobre fondo claro; es un arreglo de
~1 h que conviene adelantar si molesta en las demos · nodo VLM para estructura vía índice
(16) · módulo de comparación entre versiones de la normativa (17, bloqueado por el punto
pendiente 3).

**Adelantados de hecho por el ítem P:** el 15 (rango de hilos según backend) queda cubierto
por `concurrencia_recomendada` en el `ProviderSpec`; el 18 (análisis de costos) queda a un
paso, con `costo_1m_tokens` ya modelado y el contador de llamadas del ítem 6.

## 12. Pendientes de definición con el negocio

1. **¿Un selector o dos?** — se avanza con el supuesto S1 (dos); confirmar antes de cerrar el ítem 7.
2. **Nota incompleta "Analizar las…"** del documento original — sin alcance determinable.
3. **Casos del módulo de comparación entre versiones** (Bloque E) — bloquea el ítem 17.

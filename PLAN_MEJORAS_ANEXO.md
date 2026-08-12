# Plan de trabajo — Ítems 1 a 10 del Anexo, en tres fases

> **Estado: PROPUESTA — pendiente de aprobación.** Ninguna rama ni código se ha creado todavía.
> Reemplaza la versión del 2026-08-11, que planteaba una única entrega contra Streamlit + DMR.
> Fuentes: `Informe_Consolidado_Comparador_Normativo.docx` (con la definición completa de la
> "doble vía") + sus 5 capturas · decisiones de producto del 2026-08-12 (fasado, destino de
> despliegue, frontend, identidad visual).
> Base verificada: `main` @ `e27d540`. Suite en verde (36 passed, 1 skipped, 1 deselected).

---

## 0. Qué cambia respecto de la versión anterior

| # | Antes | Ahora | Motivo |
|---|-------|-------|--------|
| 1 | Ola 0 = PR `feature/streamlit-ui` → `main` | **Ya está hecho.** Las ramas están sincronizadas (`0 0`). El commit base `befa7ef` que citaba el plan no existe: la historia se reescribió en `32710e5` | Verificado en git |
| 2 | Una sola entrega | **Tres fases**: piloto local → contenedor + frontend → Azure | Decisión de producto: validar el piloto antes de comprometer infraestructura |
| 3 | Ítem P = 4 proveedores de nube (Azure, Groq, Vertex) | **P-a** (costuras de proveedor, sin SDKs) en Fase 1 · **P-b** (Azure) en Fase 3. Groq y Vertex **fuera de alcance** | El destino es Azure AI Foundry / Azure OpenAI; los otros dos eran especulativos |
| 4 | Ítem 4 = registro multi-proveedor | Simplificado a DMR en Fase 1 | Sin multi-nube, es leer `/models` y validar |
| 5 | Ítems 2 y 3 en ramas separadas | **Fusionados** en `feature/run-manager` | Comparten el mismo registro de corridas con espejo en disco |
| 6 | Ítem 5 en la Ola 2 | **Adelantado**, y con `workspace_id` desde el diseño | Es el contrato de datos del que saldrán los tipos del frontend en Fase 2 |
| 7 | UI = Streamlit para siempre | Streamlit es la vista del piloto; **Vite + React + TypeScript** en Fase 2 | Decisión de producto |
| 8 | — | **`feature/service-layer`** como rama nueva y habilitante | Es lo que hace que cambiar de UI cueste una capa de presentación y no un rewrite |
| 9 | — | **Sistema de tokens de diseño** con fuente única | Hoy la paleta está duplicada a mano entre la UI y el Excel |
| 10 | — | **Prerrequisitos de repositorio** (Ola 0) | No hay `pyproject.toml`, ni CI, ni fixtures del pipeline, ni el entorno documentado |

---

## 1. Qué pide el anexo (ítems 1–10)

| # | Ítem | Blq. | Prioridad | Fase | Dependencia |
|---|------|------|-----------|------|-------------|
| 1 | Detener el proceso cuando falle la conexión al modelo (no marcar todo `no_aplica` con el error embebido) | B | Alta | 1 | — |
| 2 | Corregir desincronización de estado al refrescar/cambiar de pestaña en una corrida | C | Alta | 1 | — |
| 3 | Checkpoints y recuperación de procesos largos interrumpidos | C | Alta | 1 | Ítem 2 |
| 4 | Validar modelos disponibles + no asumir "todo relevante" al fallar el parseo del grading | B | Alta | 1 | P-a |
| 5 | Modelo de datos artículo↔sección **N:N** en proceso y resultado | A | Alta | 1 | — |
| 6 | **Análisis en doble vía**: (1) por sección del manual → cumplimiento + alerta; (2) por artículo de la normativa → cobertura/adopción + brechas | A | Alta | 1 | Ítem 5 |
| 7 | Selector de alcance por lista (artículos/secciones), no solo por cantidad | A/B | Alta | 1 | Ítem 5 · S1 |
| 8 | Chunking semántico por sección + pruebas de retrieval en español | B | Alta | 1 | — |
| 9 | Plantilla de exportación a Excel en formato "Papel de Trabajo" | D | Alta | 1 | Ítems 5 y 6 |
| 10 | Flag de revisión manual para artículos/secciones sin cumplimiento evidente (ambas vías) | A | Media-Alta | 1 | Ítems 5 y 6 |

**Los diez ítems del anexo caben en la Fase 1.** Las fases 2 y 3 no añaden capacidad analítica:
cambian el envoltorio (frontend profesional) y el sitio donde corre (Azure).

**Premisa no negociable del Bloque A:** el 100 % de la normativa debe quedar cubierto por
algún control del manual. Es lo que la Vía 2 debe verificar y alertar.

### Habilitantes fuera del anexo

| # | Ítem | Fase | Origen |
|---|------|------|--------|
| **P-a** | **Costuras de proveedor**: `settings.py` + `.env`, inyección del chat model, adaptador genérico de embeddings, metadatos del índice | 1 | Solicitud del 2026-08-04, reducida al fasado |
| **P-b** | **Backend de Azure**: Foundry / Azure OpenAI + Managed Identity | 3 | Destino de despliegue confirmado |
| **T** | **Tokens de diseño con fuente única** (UI + Excel + futuro React) | 1 | Identidad visual definida el 2026-08-12 |
| **R** | **Prerrequisitos de repositorio**: `pyproject.toml`, CI, fixtures, entorno dedicado | 1 | §2.3 |

---

## 2. Diagnóstico del repo

Verificado contra el código el 2026-08-12. Todas las referencias de línea reconfirmadas.

### 2.1 Confirmaciones de los bugs reportados

| Ítem | Causa raíz localizada | Evidencia |
|------|----------------------|-----------|
| 1 | `analyze_comparison()` captura **toda** excepción y devuelve `nivel_cumplimiento="no_aplica"` con el error dentro de `analisis_general` | `src/llm_grader.py:293-299` |
| 1 | `DocumentComparator.run()` captura la excepción por fila y la sustituye por `_empty_result()`, que también es `no_aplica` | `src/comparator.py:89-93`, `src/comparator.py:221-238` |
| 1 | No hay cancelación: el `ThreadPoolExecutor` sigue enviando las filas restantes aunque el modelo ya no responda | `src/comparator.py:81-98` |
| 4 | Al fallar el parseo del grading: `logger.warning(… "Se asumen todos relevantes")` y devuelve `relevante=True` para todos | `src/llm_grader.py:235-237` |
| 4 | Aun con parseo exitoso, un candidato cuyo `element_id` no aparezca en la respuesta queda `relevante=True` por defecto | `src/llm_grader.py:243-248` |
| 4 | `_check_dmr()` solo comprueba `status_code==200` de `/models`; **no** lee la lista ni valida que el modelo configurado exista | `streamlit_app.py:60-68` |
| 4 | Los modelos del sidebar son constantes hardcodeadas, no la lista real del DMR | `streamlit_app.py:91-114` |
| 2 | La corrida es **bloqueante dentro del script-run** de Streamlit: al refrescar, la sesión nueva nace vacía mientras los hilos siguen vivos en el proceso | `streamlit_app.py:352-406` |
| 2 | El handler de logs escribe en `st.session_state` desde hilos worker (sin `ScriptRunContext`) y falla en silencio → el panel "Registro de ejecución" queda vacío | `app/logging_utils.py:30-38` |
| 3 | No existe persistencia parcial: `results_df` solo se materializa al terminar el `run()` completo | `src/comparator.py:98` |
| 5 | La relación artículo↔sección se **aplana a strings** al exportar; se pierde la trazabilidad N:N | `src/comparator.py:240-259` |
| 7 | Solo hay cantidad (`n_sample`) y la selección es **aleatoria** (`sample(random_state=42)`) | `streamlit_app.py:336-340`, `streamlit_app.py:355` |
| 8 | La normativa se trocea solo por regex de artículo, con truncado duro a 3000 caracteres; no hay chunking semántico ni evaluación de retrieval | `src/document_parser.py:296-333` |
| 9 | `export_excel()` produce una sola hoja plana; no es un papel de trabajo ni es configurable | `src/comparator.py:111-165` |

### 2.2 Defectos adicionales encontrados, no listados en el informe

Bajo costo, alto impacto sobre la calidad de los resultados. Se corrigen en la Ola 1
(`fix/config-wiring`), porque los ítems 6 y 10 dependen de que los umbrales funcionen.

1. **El slider "Score semántico mínimo" no tiene efecto en la corrida.**
   `_process_row()` llama `semantic_search(embed_text, top_k=…)` sin `min_score`
   (`src/comparator.py:178`), así que usa el valor de `config.py` (0.30), no el del sidebar.
   `DocumentComparator.__init__` ni siquiera recibe el umbral (`streamlit_app.py:366-371`).
   El informe pide que la alerta de la Vía 1 se apalanque "en los umbrales de similitud ya
   existentes en la app" — hoy ese control es decorativo fuera de la pestaña 2.

2. **`lexical_scan()` cruza artículos entre normativas distintas.**
   Compara solo por `numero` sobre el `normativa_df` completo (`src/search_engine.py:188-220`).
   Con varias normas cargadas, un "Art. 5" del manual matchea el Art. 5 de *todas* ellas.
   Con el modelo N:N (ítem 5) esto se vuelve crítico: genera aristas falsas de cobertura.

3. **Los prefijos del backend local se anulan.**
   `NormativaIndex.build()` y `semantic_search()` fuerzan `prefix=""`
   (`src/search_engine.py:99`, `src/search_engine.py:136`), pero
   `SentenceTransformersEmbeddings` usa `intfloat/multilingual-e5-large`, que **requiere**
   `passage: ` / `query: `. El backend local rinde por debajo de su capacidad. Entra en el
   ítem 8 (calidad de retrieval en español).

4. **El índice FAISS persistido no registra con qué modelo se generó.**
   `save()` escribe `index.faiss` + `normativa_meta.json` y nada más
   (`src/search_engine.py:107-122`). Hoy el daño se limita a un error críptico de dimensión.
   Con proveedores de nube el riesgo cambia de naturaleza: dos modelos distintos de **la misma
   dimensión** (1536 es un valor muy común) cargan sin protestar y devuelven vecinos sin
   sentido, en silencio. Se corrige dentro de P-a.

5. **La paleta está duplicada a mano en dos archivos.**
   `app/theme.py:38-43` (`NIVEL_COLORS`) y `src/comparator.py:137-142` (los `PatternFill` del
   Excel) repiten los mismos hex escritos a mano: `E2EFDA`, `FFF2CC`, `FCE4D6`, `F2F2F2`. El
   docstring de `theme.py:36-37` dice que "coinciden"; coinciden porque alguien los copió. Al
   cambiar la identidad visual hay que tocar dos sitios o el Excel y la UI dejan de leerse
   igual. En Fase 2 se suma React como tercer consumidor. Se corrige en el ítem T.

### 2.3 Prerrequisitos de repositorio detectados

No son bugs del producto; son condiciones sin las cuales el plan no se puede ejecutar.

1. **El entorno documentado no existe.** `dependencies/environment.yml` define
   `normas_comparador`; en la máquina de desarrollo no está. Lo que ejecuta el proyecto es un
   entorno compartido con otro trabajo. P-a y el ítem 8 añaden dependencias: hacerlo sobre un
   entorno compartido rompe los dos proyectos a la vez. Además, `environment.yml` en la raíz es
   un freeze de ~300 paquetes que el propio `dependencies/README.md` desaconseja usar.

2. **`document_test/` no existe.** El lado "manual" del pipeline no es ejecutable de extremo a
   extremo. Sin manual no se validan los ítems 5, 6, 9 ni 10, y el gold set del ítem 8 no se
   puede redactar. El directorio está en `.gitignore` por confidencialidad, y así debe seguir.

3. **No hay fixtures ni dobles de prueba del pipeline.** Las 36 pruebas actuales cubren UI
   (`AppTest`), logging y progreso; ninguna ejercita `comparator`/`grader`/`index` con datos.
   El plan promete una docena de archivos de prueba nuevos y en cuatro de ellos asume "un
   grader falso determinista" que no existe. Si cada rama lo inventa por su cuenta, todas
   chocan en `tests/conftest.py`.

4. **No hay CI.** No existe `.github/`. Sin ella, el umbral de regresión del ítem 8
   (recall@5 ≥ 0.80) y la verificación de que no se cuele un `.env` son inejecutables.

5. **No hay `pyproject.toml`** (ni `pytest.ini`, ni lockfile, ni linter fijado). `import src`
   funciona por el `sys.path.insert` de `tests/conftest.py:26`. Doce ramas concurrentes sobre
   esa base generan conflictos evitables.

6. **`master.ipynb` no tiene prueba de regresión.** El supuesto S5 promete compatibilidad, pero
   nada la verifica. El contrato real es pequeño — el notebook solo usa `parse_pdf()`,
   `run_sample()` y `export_excel()` — y por eso mismo es barato fijarlo **antes** del
   refactor N:N, no después.

---

## 3. Estrategia de fases

### 3.1 Por qué

El destino es un contenedor en Azure con endpoint de Azure AI Foundry o Azure OpenAI. Pero no
hay todavía suscripción, recursos ni registros de aplicación en el tenant, y el valor del
producto está sin demostrar. Construir para Azure desde el inicio significa comprometer
infraestructura antes de saber si el piloto funciona.

El fasado invierte el orden: **primero el motor, en la máquina local; después el envoltorio;
al final la infraestructura.** El precio es real y conviene decirlo: el total fasado sale por
encima del construido-para-Azure-desde-el-inicio, porque parte de la UI del piloto se
reescribe. A cambio, hay algo demostrable en semanas en vez de meses, y las decisiones de
Azure se toman con evidencia.

### 3.2 Qué se construye en cada fase

| Fase | Entorno | Alcance | Qué demuestra |
|------|---------|---------|---------------|
| **1 — Piloto** | Mac local · DMR · Streamlit | Los 10 ítems del anexo + P-a + T + R | Que el análisis en doble vía produce un papel de trabajo útil |
| **2 — Producto** | Contenedor Linux · FastAPI + Vite/React/TS | Portabilidad, API, frontend profesional | Que es una aplicación, no un script con interfaz |
| **3 — Plataforma** | Azure · Foundry/AOAI · Entra ID | P-b, SSO, almacenamiento durable, worker, IaC | Que escala y cumple los requisitos corporativos |

### 3.3 Restricciones de "no cerrar puertas"

Esta es la disciplina que hace barato el fasado. Cada punto cuesta casi nada en la Fase 1 y es
lo que evita reescribir en la 2 y la 3.

> **Cómo se verifican** *(decidido el 2026-08-12, tras la auditoría de la Ola 1)*
>
> Son **criterio de cierre de fase**, no invariante por PR: se exigen ciertas al terminar
> la Fase 1, no en cada rama. La redacción original decía "obligatorio en toda la Fase 1"
> mientras §7 asignaba las dos primeras a ramas de la Ola 2 — una contradicción que en la
> práctica se resolvió sola, en silencio y a favor de la lectura laxa.
>
> El precio de esta lectura es que la deuda tiene que estar **declarada y con dueño**, o
> deja de ser deuda y pasa a ser un olvido:
>
> | Restricción | Estado al cerrar la Ola 1 | Dueño |
> |---|---|---|
> | 1 · `workspace_id` | Sin aplicar. Cero apariciones en el repo; `index_meta.json` nació sin él | `feature/coverage-model` (ítem 5) — `CoverageLink` debe nacer con él |
> | 2 · Rutas por corrida | Sin aplicar. `output/comparador/*` sigue fijo | `feature/service-layer` (Ola 2) |
> | 3 · Sin estado global | ✓ | — |
> | 4 · Config por entorno | Mecanismo sí, cableado a medias: la UI no pasa por `settings` | `feature/service-layer` |
> | 5 · Sin construcción directa de clientes | ✓ en `src/` desde `fix/provider-wiring`; `streamlit_app.py` pendiente | `feature/service-layer` |
> | 6 · Nada de macOS fuera de su sitio | ✓ desde `src/bootstrap.py` | — |
> | 7 · Cómputo independiente del proceso | n/a hasta el ítem 3 | `feature/run-manager` |
>
> **Ninguna de estas puede seguir abierta al cerrar la Fase 1**: §14 las da por ciertas.

1. **`workspace_id` en el modelo de datos desde el primer día**, aunque siempre valga `"local"`.
   Añadir el campo ahora a `CoverageLink`, al manifest del checkpoint y al papel de trabajo es
   gratis. Retro-fitearlo cuando ya hay resultados, Excel generados y un esquema publicado es
   de lo más caro que queda por delante. Es el seguro más barato de la lista.

2. **Rutas de salida por corrida, nunca fijas.** Hoy `streamlit_app.py:391` escribe siempre a
   `output/comparador/reporte_comparacion.xlsx`. Pasa a `output/runs/<run_id>/…`. El ítem 3 lo
   necesita igual para los checkpoints, así que no es trabajo extra — solo hay que no dejar la
   ruta fija "porque de momento hay un solo usuario".

3. **Ningún estado global de proceso para el pipeline.** El registro de corridas y los
   artefactos van a disco bajo `workspace_id`/`run_id` desde ya. Evita que la Fase 3 tenga que
   desmontar singletons cuando el autoescalado levante una segunda réplica.

4. **Configuración por entorno, nunca hardcodeada.** Es P-a. En Fase 1 apunta a DMR local; en
   Fase 3, a Azure. Mismo código.

5. **Costuras de proveedor para LLM, embeddings, parser/OCR, vector store y almacenamiento.**
   No hay que escribir las implementaciones de Azure. Solo que la interfaz exista y que
   `comparator.py` no llame a la implementación concreta como si fuera la única posible.

6. **Nada específico de macOS fuera de la implementación concreta.** `sys.platform == "darwin"`
   ya está aislado en `_build_pdf_pipeline_options` (`src/document_parser.py:66-74`), bien. Pero
   `KMP_DUPLICATE_LIB_OK` vive en `streamlit_app.py:21` y `tests/conftest.py:18`: es un
   workaround de arranque de proceso y debe moverse a la capa de bootstrap. Cuando el frontend
   deje de ser Python, ese `os.environ.setdefault` se pierde y aparece un segfault difícil de
   rastrear.

7. **El cómputo no depende de que el proceso siga vivo.** Es el ítem 3 tal cual. En Mac protege
   de que Streamlit se caiga a mitad de una corrida de horas; en contenedor, del redeploy.

---

## 4. Decisiones y supuestos

| # | Punto | Decisión |
|---|-------|----------|
| S1 | **Punto pendiente 1 del informe** (¿un selector o dos?) | **SUPUESTO, no confirmado. Dos selectores**, uno por vía: alcance normativo (artículos) y alcance del manual (secciones). La doble vía lo vuelve necesario: la Vía 2 se define sobre artículos y la Vía 1 sobre secciones. "Número de secciones a analizar" se conserva como preset "Muestra rápida". La lógica va en `src/scope.py`, independiente de la UI: si el negocio confirma otra cosa, solo cambian los widgets. **Confirmar antes de cerrar el ítem 7.** |
| S2 | Estado de fila fallida | Se introduce `estado_analisis` (`ok`/`error_modelo`/`error_parseo`/`omitido`) **separado** de `nivel_cumplimiento`. Un fallo técnico nunca vuelve a expresarse como `no_aplica`. |
| S3 | Costo de la Vía 2 | Las aristas N:N se comparten entre vías y el grading se cachea por par `(articulo, seccion)`. La Vía 2 solo gasta LLM en el veredicto por artículo y en la búsqueda inversa de artículos sin aristas. Sin esto, el costo se duplicaría. |
| S4 | Alcance | Ítems 1–10 + P-a + T + R en Fase 1. Los ítems 11–18 del anexo quedan fuera; se anotan como *follow-up* en §15. |
| S5 | Compatibilidad | `master.ipynb` sigue funcionando: `parse_pdf()`, `run_sample()` y `export_excel()` se mantienen como fachada sobre la nueva arquitectura. **Se fija con `tests/test_facade_compat.py` en la Ola 0**, antes de tocar nada. |
| S6 | Hardware de la Fase 1 | M1 16 GB con DMR local: `max_workers` bajo, checkpoints frecuentes, evaluación de retrieval sin LLM. |
| S7 | Proveedor | **DMR local es el default de desarrollo; Azure lo será de producción.** No son alternativas opt-in: son entornos distintos del mismo sistema. En Fase 1 solo existe DMR. |
| S8 | LLM y embeddings se eligen por separado | Se formaliza en P-a que el backend de LLM y el de embeddings son independientes y combinables. En Fase 1 ambos apuntan a DMR o al backend local de sentence-transformers. |
| S9 | Reranker | **Local (`CrossEncoder`) en Fase 1.** En Fase 3 se reevalúa: mantener un CrossEncoder en CPU dentro del contenedor es la pieza más pesada del stack y Azure ofrece reranking como servicio. |
| S10 | UI de la Fase 1 | **Streamlit se conserva como vista delgada**, no se rediseña. Montar SPA + API para un usuario en una Mac retrasaría el piloto sin añadirle capacidad. La condición es que `feature/service-layer` se haga igual: con la orquestación fuera de la UI, la Fase 2 reescribe presentación, no lógica. |
| S11 | Frontend de la Fase 2 | **Vite + React + TypeScript**, monorepo, tipos generados desde el OpenAPI de FastAPI. Los modelos Pydantic pasan a ser los tipos del frontend — otra razón para que `CoverageLink` esté temprano y estable. |
| S12 | Identidad del cliente | El repositorio **no identifica al cliente**. El nombre sale de `ORG_DISPLAY_NAME` (`app/theme.py:9-11`) y los valores de marca de `assets/brand/brand.json`, ambos fuera de git. Es la postura establecida en el commit `32710e5` y se mantiene. |

---

## 5. Arquitectura objetivo — Fase 1

```text
┌───────────────────────────────────────────────────────────────────────────┐
│  FASE 1 — Tabulación                    src/document_parser.py            │
│  NormativaParser → normativa_df (1 fila = 1 artículo)                     │
│  ManualParser    → manual_df   (1 fila = 1 sección)                       │
│         + NUEVO  src/chunking.py → sub-chunks semánticos por artículo     │
│                  (parent-child: se recupera el chunk, se devuelve el art.)│
└───────────────────────────────────────────────────────────────────────────┘
                              │
┌───────────────────────────────────────────────────────────────────────────┐
│  FASE 2 — Índices                       src/search_engine.py (refactor)   │
│  SemanticIndex (genérico)                                                 │
│    ├── NormativaIndex  → artículos       (Vía 1: sección → artículos)     │
│    └── ManualIndex     → secciones NUEVO (Vía 2: artículo → secciones)    │
└───────────────────────────────────────────────────────────────────────────┘
                              │
┌───────────────────────────────────────────────────────────────────────────┐
│  FASE 3 — Doble vía                     src/comparator.py (refactor)      │
│   Vía 1  sección → artículos      Vía 2  artículo → secciones             │
│   cumple/parcial/omisión           cubierto/parcial/no_cubierto           │
│   + alerta de incumplimiento       + brechas de cobertura                 │
│           └────────────┬────────────────────┘                             │
│         src/coverage.py  ← NUEVO: tabla de aristas N:N                    │
│         CoverageLink(workspace_id, articulo_id, seccion_id, origen,       │
│                      scores, veredicto)                                   │
│         · vista_manual_df     (agregado por sección)   → Vía 1            │
│         · vista_normativa_df  (agregado por artículo)  → Vía 2            │
│         · cobertura_global    (% artículos cubiertos, brechas)            │
└───────────────────────────────────────────────────────────────────────────┘
                              │
┌───────────────────────────────────────────────────────────────────────────┐
│  FASE 4 — Entregable                    src/papel_trabajo.py ← NUEVO      │
│  Excel multi-hoja dirigido por templates/papel_trabajo.yaml               │
│  Resumen · Vía 1 · Vía 2 · Matriz N:N · Revisión manual · Trazabilidad    │
└───────────────────────────────────────────────────────────────────────────┘

Transversal:
  src/errors.py         ← taxonomía de errores (fail-fast vs. degradado)
  src/settings.py       ← .env, precedencia, redacción de secretos      (P-a)
  src/providers.py      ← costuras: chat model, embeddings, listado     (P-a)
  src/model_registry.py ← list/validate models + preflight
  src/checkpoint.py     ← persistencia incremental + reanudación
  src/scope.py          ← filtros de alcance (puros, testeables)
  src/design_tokens.py  ← fuente única de paleta y tipografía            (T)
  src/service.py        ← orquestación sin Streamlit  ← HABILITANTE DE LA FASE 2
  app/run_manager.py    ← corridas en background + re-attach
```

**La costura que define la Fase 2 es `src/service.py`.** Todo lo que hoy vive en
`streamlit_app.py` y no es presentación se muda ahí: `_build_embedding_backend()` (`:207-214`),
el armado de `LLMGrader`/`DocumentComparator` (`:359-371`) y el flujo entre las cuatro
pestañas. Streamlit queda como una vista que llama a ese servicio; FastAPI, en la Fase 2, será
otra.

---

## 6. Estrategia de ramas — Fase 1

`main` ya contiene el baseline. Se corta la rama de integración y todas las demás salen de ahí:

```bash
git checkout main && git pull
git checkout -b feature/comparador-v2
git push -u origin feature/comparador-v2
```

| Ola | Rama | Ítems | Depende de | ~Jornadas |
|-----|------|-------|-----------|-----------|
| 0 | `chore/project-scaffold` | R | — | 1.5 |
| 0 | `test/pipeline-fixtures` | R, S5 | `chore/project-scaffold` | 1.5 |
| 1 | `fix/llm-failfast` | 1 | Ola 0 | 1.5 |
| 1 | `fix/config-wiring` | §2.2 (1–3) | Ola 0 | 1 |
| 1 | `feature/provider-seams` | **P-a** | `fix/llm-failfast` (comparte `src/errors.py`) | 1 |
| 1 | `feature/model-registry` | 4 | `feature/provider-seams` | 1 |
| 1 | `feature/design-tokens` | **T** | Ola 0 | 0.5 |
| 2 | `feature/service-layer` | S10 | Ola 1 | 2 |
| 2 | `feature/run-manager` | 2 + 3 | `feature/service-layer` | 3 |
| 3 | `feature/coverage-model` | 5 | Ola 1 | 3 |
| 3 | `feature/dual-analysis` | 6 | `feature/coverage-model` | 4 |
| 3 | `feature/scope-selector` | 7 | `feature/coverage-model` | 1.5 |
| 3 | `feature/review-flag` | 10 | `feature/dual-analysis` | 1 |
| 4 | `feature/semantic-chunking` | 8 | Ola 0 | 3 |
| 4 | `feature/papel-trabajo` | 9 | `feature/dual-analysis` | 2.5 |

**Paralelizable de verdad:** `feature/semantic-chunking` (ítem 8) solo toca
`document_parser.py`/`search_engine.py` y puede arrancar desde la Ola 1.
`fix/config-wiring` y `feature/design-tokens` también son independientes.

**Convención de commits:** la del repo (`feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`).

Al cerrar las cuatro olas, un único PR `feature/comparador-v2` → `main`.

---

## 7. Plan detallado — Fase 1

### Ola 0 · Cimientos

#### R1 — Andamiaje del proyecto · `chore/project-scaffold` · ~1.5 j

- **`pyproject.toml`**: metadatos, `[tool.pytest.ini_options]` con los marcadores (`e2e`,
  `retrieval`), `[tool.ruff]`, y `src`/`app` como paquetes para eliminar el `sys.path.insert`
  de `tests/conftest.py:26`.
- **Entorno dedicado** creado desde `dependencies/environment.yml`. `environment.yml` de la
  raíz se marca como freeze histórico o se elimina.
- **CI** (`.github/workflows/ci.yml`): `pytest -m "not e2e"` + `ruff`.
- **Compuerta de confidencialidad: local, no en CI.** El repositorio es **público**; un
  escaneo en CI corre *después* del push, cuando el material ya es visible. La compuerta
  tiene que estar en `pre-commit`, `commit-msg` y `pre-push`, y el filtro `clean` de git debe
  quitar las salidas de los notebooks antes de que entren al índice. Ya instalado en
  `.claude/scripts/` (`instalar_guardas.sh`); CI queda como segunda red, no como primera.

**DoD** — `pytest` corre sin el hack de `sys.path`; el CI falla ante un secreto commiteado.

#### R2 — Fixtures y dobles del pipeline · `test/pipeline-fixtures` · ~1.5 j

- `tests/fixtures/`: mini-corpus sintético versionado (normativa de ~12 artículos de dos
  normas distintas + manual de ~8 secciones) que ejercita los casos límite: artículo huérfano,
  sección que satisface artículos de dos normas, referencia léxica cruzada.
- Dobles deterministas: `FakeChatModel`, `FakeEmbeddingBackend`, `FakeGrader`, con contador de
  invocaciones (lo necesita el DoD del ítem 6).
- **`tests/test_facade_compat.py`**: fija `parse_pdf()`, `run_sample()`, `export_excel()` — el
  contrato que `master.ipynb` consume (S5).

**DoD** — Las nueve ramas siguientes escriben pruebas sin inventar infraestructura ni tocar
`conftest.py`. El corpus sintético no contiene material del cliente.

---

### Ola 1 · Fiabilidad

#### Ítem 1 — Fail-fast ante caída del modelo · `fix/llm-failfast` · ~1.5 j

**Problema (captura 1):** las 5 secciones salen `no_aplica` con `Error en análisis LLM: error
while getting model …` incrustado en `analisis_general`. El auditor recibe un papel de trabajo
que dice "no aplica" cuando el modelo nunca respondió.

**Cambios**

- **NUEVO `src/errors.py`**
  ```
  ComparadorError
   ├─ LLMUnavailableError    # conexión, timeout, 5xx, "error while getting model" → ABORTA
   ├─ ModelNotFoundError     # el modelo no está en el DMR                          → ABORTA
   ├─ GradingParseError      # la respuesta no mapea al esquema                     → degrada 1 fila
   └─ RunAbortedError        # cancelación del usuario o abort en cascada
  ```
  `classify_llm_exception(exc) -> ComparadorError` traduce las excepciones de
  `openai`/`httpx`/`langchain` a esta taxonomía.
- `src/llm_grader.py`: los `except Exception` de `analyze_comparison()` (`:293`) y
  `grade_candidates()` (`:235`) clasifican antes de decidir. Los errores de infraestructura se
  **relanzan**; solo los de contenido degradan la fila.
- `src/comparator.py`: `run()` distingue error de fila (`estado_analisis="error_parseo"`) de
  error de infraestructura → cancela los futures pendientes
  (`executor.shutdown(cancel_futures=True)`), marca las filas no procesadas como `omitido` y
  relanza `LLMUnavailableError`.
- `_empty_result()` deja de usar `no_aplica`: `nivel_cumplimiento=None` + `estado_analisis`.
- `streamlit_app.py`: `st.error()` con el modelo, la URL y cuántas secciones quedaron sin
  procesar; los resultados parciales se conservan y se etiquetan como parciales.
- **Umbral configurable:** `max_fallos_consecutivos` (default 3) también aborta.

**DoD** — Con el DMR apagado, la corrida se detiene en < 15 s con mensaje claro; ninguna fila
queda como `no_aplica`; el Excel/JSON nunca contiene un mensaje de error en `analisis_general`.

**Tests** — `tests/test_failfast.py`: grader que lanza `APIConnectionError` → `run()` relanza
`LLMUnavailableError`; grader que falla solo en la fila 2 → la corrida termina y esa fila queda
`estado_analisis="error_parseo"`.

---

#### §2.2 — Cableado de configuración · `fix/config-wiring` · ~1 j

Los tres defectos de §2.2 (1–3), que el ítem 6 necesita funcionando:

- `DocumentComparator.__init__` recibe `min_semantic_score` y `_process_row()` lo pasa a
  `semantic_search()` (`src/comparator.py:178`). El slider del sidebar deja de ser decorativo.
- `lexical_scan()` distingue las citas ambiguas de las firmes para no cruzar normativas
  (ver la enmienda de abajo).
- Se restauran los prefijos `passage:`/`query:` del backend local, declarados **por el
  backend** y no fijados por el índice.

> **Enmienda del criterio del defecto 2** *(decidida el 2026-08-12; el DoD original decía
> "ningún artículo de la norma A aparece ligado por vía léxica a una sección que citaba la
> norma B")*
>
> Cuando el manual cita "Art. 5" y ese número existe en dos normativas cargadas, hay tres
> salidas y dos son malas: devolver ambas como citas firmes fabrica una arista de
> cobertura falsa; elegir una arbitrariamente fabrica una cita que el texto no respalda.
>
> **La adoptada es la tercera: etiquetar, no descartar.** Se emiten como
> `match_type="ambiguo"`, con score reducido y una razón. Descartarlas —que fue la primera
> implementación— borraba el hecho de que el manual *sí* cita un artículo, y ese hecho lo
> necesitan el modelo N:N (ítem 5), la cobertura de la Vía 2 (ítem 6) —donde un artículo
> realmente citado aparecería como huérfano y produciría una brecha inexistente contra la
> premisa del Bloque A— y el flag de revisión manual (ítem 10).
>
> El motor de búsqueda no es la capa que decide tirar evidencia. Y es lo que pide el
> Bloque A: la herramienta marca y explica, no resuelve lo que no puede resolver.
>
> **La etiqueta obliga aguas abajo**, no solo en el buscador: una cita ambigua no cuenta
> para `tipo_coincidencia`, llega al prompt declarada como indicio no confirmado, y viaja
> a la fila en `articulos_lexicos_ambiguos`, separada de `articulos_lexicos`. Sin eso, el
> comportamiento visible sería idéntico al defecto original.

**DoD** — Cambiar el umbral en el sidebar altera el número de candidatos de una corrida.
Con dos normativas cargadas, ningún artículo de la norma A queda ligado **como cita
léxica firme** a una sección cuyo número también pertenece a la norma B; si lo está, es
como `ambiguo` y así se declara en el resultado y en el prompt.

**Tests** — `tests/test_config_wiring.py`, `tests/test_lexical_isolation.py`.

---

#### Ítem P-a — Costuras de proveedor · `feature/provider-seams` · ~1 j

**Alcance reducido respecto del plan anterior.** No se escribe ningún backend de nube. Se
construye únicamente la costura que permite añadirlos en la Fase 3 sin refactorizar.

**Estado actual:** todo está cableado a DMR. `LLMGrader.__init__` instancia
`ChatOpenAI(base_url=…, api_key="ignored")` directamente (`src/llm_grader.py:180-197`) y
`LangChainDMREmbeddings` hace lo propio con `OpenAIEmbeddings` (`src/embeddings.py:56-65`).
**No hay una sola lectura de variables de entorno en el código**: `python-dotenv` está
declarado en `dependencies/requirements.txt` pero nunca se usa, y `config.py` tiene los
endpoints hardcodeados. `.env` ya está en `.gitignore`.

**Cambios**

- **NUEVO `src/settings.py`** — carga `.env` con `python-dotenv`; precedencia explícita
  **UI > variable de entorno > `.env` > defaults de `config.py`**; `redact(valor)` para claves
  y URLs con token, usado en logs, panel de ejecución y hoja de trazabilidad.
- **NUEVO `src/providers.py`** — `ProviderSpec` + fábricas `build_chat_model(spec)`,
  `build_embedding_backend(spec)`, `list_models(spec)`. En Fase 1 hay una sola implementación
  (DMR) más el backend local de sentence-transformers. La interfaz se diseña para que Azure
  entre como una fábrica más.
- **NUEVO `.env.example`** commiteado, sin valores.
- `src/llm_grader.py`: `LLMGrader` recibe un `BaseChatModel` inyectado en vez de construirlo.
  Los `timeout`/`max_retries` hardcodeados (120/180 s, `max_retries=0`) pasan al `ProviderSpec`.
- `src/embeddings.py`: **NUEVO** `LangChainEmbeddingsAdapter`, que envuelve cualquier objeto
  `Embeddings` de LangChain en la interfaz `EmbeddingBackend` (batching + normalización L2).
  `LangChainDMREmbeddings` pasa a ser un caso particular.
- `src/search_engine.py`: `save()` escribe `index_meta.json` con `proveedor + modelo + dim +
  fecha`; `load()` rechaza cargar si no coincide con el backend activo (§2.2, defecto 4).
- `KMP_DUPLICATE_LIB_OK` se muda de `streamlit_app.py:21` a la capa de bootstrap (§3.3.6).

**DoD** — Ningún módulo de `src/` construye un cliente de LLM o de embeddings directamente.
Un índice FAISS construido con un modelo y cargado con otro se rechaza con mensaje explícito.
Ninguna credencial sobrevive a `redact()` en logs ni en el Excel.

**Tests** — `tests/test_providers.py` (construcción con env mockeado, precedencia,
redacción de secretos) y `tests/test_index_meta.py`. Todo sin red.

> *La redacción se probó dentro de `test_providers.py::TestRedaccionDeSecretos` en vez de
> en un archivo aparte; el contenido exigido está, el nombre del archivo no aporta.*

---

#### Ítem 4 — Validación de modelos + grading sin falsos positivos · `feature/model-registry` · ~1 j

**Problema (capturas 3 y 4):** `Field required: candidatos … Se asumen todos relevantes.` Al
cambiar de modelo, el parseo falla y **todo candidato pasa como relevante** — el riesgo espejo
del ítem 1: allí se pierden secciones, aquí se cuelan falsos positivos de cumplimiento.

**Cambios**

- **NUEVO `src/model_registry.py`**, sobre las costuras de P-a:
  `list_models(spec) -> list[ModelInfo]`; `validate_model(spec, model_id)` → `ModelNotFoundError`
  con la lista real disponible en el mensaje; `preflight(config)` verifica LLM **y** modelo de
  embeddings antes de arrancar, con caché corta (TTL 15 s) para no golpear el proveedor en cada
  rerun de Streamlit.
- `streamlit_app.py`: los `selectbox` de modelo se pueblan desde `list_models()` en vez de las
  constantes hardcodeadas (`:91-114`), con fallback a `config.py` si no responde. El botón
  "Ejecutar comparación" queda deshabilitado si el preflight falla.
- `src/llm_grader.py`, robustez del grading en tres niveles:
  1. `OutputFixingParser` como reintento de reparación del JSON.
  2. Reintento con prompt simplificado (sin `format_instructions` largas) para modelos chicos.
  3. Si aún falla → `GradingParseError`: los candidatos quedan `relevante=None`,
     `requiere_revision=True`, `motivo="grading_no_parseable"`. **Nunca `True`.**
- Igual criterio en `:243-248`: un candidato ausente de la respuesta ya no se asume relevante.

**DoD** — Configurar un modelo inexistente → error antes de gastar un token, con la lista real.
Forzar un fallo de parseo → 0 candidatos marcados `relevante=True`; la fila aparece en la hoja
"Revisión manual".

**Tests** — `tests/test_model_registry.py` (respuestas `/models` mockeadas),
`tests/test_grading_degradation.py` (LLM falso que devuelve JSON inválido).

---

#### Ítem T — Tokens de diseño · `feature/design-tokens` · ~0.5 j

**Problema:** §2.2 defecto 5 — la paleta está duplicada a mano entre `app/theme.py:38-43` y
`src/comparator.py:137-142`, y la paleta actual es un placeholder que el propio docstring de
`theme.py:3-7` admite haber inventado. Ver §8 para el sistema visual completo.

**Cambios**

- **NUEVO `src/design_tokens.py`** — fuente única. Carga los valores de marca desde
  `assets/brand/brand.json` (fuera de git, S12), con fallback a
  `assets/brand/brand.example.json` (versionado, neutro) para que un clon limpio arranque.
- `app/theme.py` consume los tokens en vez de definir `_PALETTE`.
- `src/comparator.py` consume los tokens para los `PatternFill` en vez de repetir los hex.
- Se aplica la separación cromo/dato por saturación y los mínimos de contraste de §8.
- **Se arregla de paso** el ítem 14 del anexo: `app/theme.py:89-91`
  (`section[data-testid="stSidebar"] * { color:#EAF0F6 !important }`) pinta también el texto de
  los inputs sobre fondo claro. Es ~1 h y molesta en las demos. *(La versión anterior del plan
  lo ubicaba en `:73-75`; la referencia ya derivó.)*

**DoD** — Cambiar un token en un archivo cambia a la vez la UI y el Excel. Ningún hex de marca
queda como literal en código versionado. El sidebar es legible.

**Tests** — `tests/test_design_tokens.py`: fuente única (ningún hex duplicado entre módulos),
fallback al placeholder sin `brand.json`, y verificación automatizada de los ratios de
contraste mínimos de §8.

---

### Ola 2 · Servicio y estado

#### S10 — Capa de servicio · `feature/service-layer` · ~2 j

**Es la rama que decide el costo de la Fase 2.** Sin ella, cambiar de UI es un rewrite; con
ella, es reescribir presentación.

**Cambios**

- **NUEVO `src/service.py`** — toda la orquestación que hoy vive en `streamlit_app.py`:
  construcción de backends (`:207-214`), armado de `LLMGrader`/`DocumentComparator`
  (`:359-371`), y las operaciones del flujo (`tabular()`, `construir_indice()`, `comparar()`,
  `exportar()`), con `workspace_id` y `run_id` como parámetros de primera clase (§3.3.1-2).
- `streamlit_app.py` queda como vista: widgets, estado de sesión y llamadas al servicio. Sin
  lógica de pipeline.
- Todas las rutas de salida pasan a `output/workspaces/<workspace_id>/runs/<run_id>/…`.

**DoD** — `streamlit_app.py` no importa nada de `src/` salvo `service` y `design_tokens`. El
servicio se ejercita desde una prueba sin Streamlit en el proceso.

**Tests** — `tests/test_service.py`, sin Streamlit importado.

---

#### Ítems 2 + 3 — Corridas y checkpoints · `feature/run-manager` · ~3 j

Los dos ítems comparten el mismo registro de corridas, así que se implementan juntos.

**Cambios**

- **NUEVO `app/run_manager.py`**
  - `RunHandle`: `run_id`, `workspace_id`, `estado`
    (`pendiente|corriendo|abortando|completado|fallido`), `progreso`, `total`, `iniciado_en`,
    `config_hash`, `cancel_event`, `error`.
  - Registro **a nivel de proceso** (no de sesión), protegido por lock, **con espejo en disco**
    en `output/workspaces/<ws>/runs/<run_id>/state.json`. El espejo es lo que permitirá, en la
    Fase 3, sustituir el registro en memoria por almacenamiento externo sin cambiar la interfaz.
  - `start_run()`, `get_active_runs()`, `attach(run_id)`, `cancel(run_id)`.
- **NUEVO `src/checkpoint.py`**
  - `CheckpointStore(run_dir)`: `manifest.json` (config, hashes de documentos, alcance,
    `workspace_id`, versión de esquema) + `rows.jsonl` (append por unidad completada, escritura
    atómica).
  - `completed_ids()`, `append(unidad, resultado)`, `load_partial() -> DataFrame`.
  - Invalidación: si cambian el hash de los documentos, el modelo o el alcance, la corrida no
    es reanudable; se avisa y se ofrece empezar de cero.
- `DocumentComparator.run(…, checkpoint=None)`: salta las unidades ya completadas y hace
  `append` en cada `progress_callback`.
- `streamlit_app.py`: `session_state` guarda **solo** `run_id`. Al cargar, si hay una corrida
  activa se re-adjunta. El botón "Ejecutar" pasa a "Cancelar" mientras haya una activa.
  Polling con `@st.fragment(run_every="2s")` (Streamlit 1.59 instalado lo soporta; el piso de
  `requirements.txt` sube de `>=1.38` a `>=1.59`).
- `app/logging_utils.py`: buffer `deque` de proceso por `run_id` en lugar de `st.session_state`,
  así los logs de los hilos worker sí llegan al panel (`:30-38`).
- Sección "Corridas reanudables" con `run_id`, fecha, avance (`142/380`) y botón "Reanudar".
  Purga configurable (default: conservar 20).

**DoD** — Con una corrida en marcha: F5 → la barra sigue en el mismo punto; cambiar de pestaña
y volver → idem; segunda pestaña del navegador → ve la misma corrida. Matar el proceso a mitad
y reanudar → no se repite ninguna llamada LLM ya completada y el resultado final es idéntico al
de una corrida ininterrumpida. No es posible lanzar dos corridas sobre la misma configuración.

**Tests** — `tests/test_run_manager.py` (ciclo de vida, cancelación, re-attach tras limpiar
`session_state`), `tests/test_checkpoint.py` (reanudación, invalidación por cambio de config,
resistencia a un `rows.jsonl` truncado), y un caso `AppTest` en
`tests/test_streamlit_app_smoke.py`.

---

### Ola 3 · Núcleo metodológico

#### Ítem 5 — Modelo de datos N:N · `feature/coverage-model` · ~3 j

**Problema:** hoy el resultado es un DataFrame con una fila por sección y los artículos
aplanados a texto (`src/comparator.py:240-259`). No se puede responder "¿qué secciones cubren
el Art. 35?" sin volver a correr todo. El informe sube el requisito de 1:N a **N:N**: una
sección puede tener que satisfacer artículos de varias normas a la vez.

**Este es además el contrato de datos de la Fase 2** (S11): de aquí saldrán los tipos de
TypeScript del frontend. Estabilidad prioritaria sobre elegancia.

**Cambios**

- **NUEVO `src/coverage.py`**
  ```python
  @dataclass(frozen=True)
  class CoverageLink:
      workspace_id: str          # §3.3.1 — "local" en Fase 1
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
  - `LinkTable`: `upsert()` (dedupe por `(articulo, seccion)`, conserva el mejor score y acumula
    orígenes), `to_dataframe()`, `save()/load()`.
  - Agregaciones: `vista_manual()`, `vista_normativa()`, `cobertura_global()` → `% artículos
    cubiertos`, `artículos sin cobertura`.
- `src/comparator.py`: `_process_row()` deja de aplanar; emite `CoverageLink`s. `run()` devuelve
  un `ComparisonBundle(links, vista_manual, vista_normativa, cobertura, metadatos)`.
  `results_df` se mantiene como propiedad derivada (S5).
- Persistencia: `links.parquet` + `coverage.json` bajo el `run_dir`.

**DoD** — Consulta directa en ambos sentidos: `links.query("articulo_numero=='35'")` devuelve
todas las secciones que lo cubren, con score y origen. `test_facade_compat.py` sigue verde.

**Tests** — `tests/test_coverage_model.py`: dedupe, agregaciones en ambos sentidos, cálculo de
cobertura, aislamiento entre documentos, round-trip de persistencia.

---

#### Ítem 6 — Análisis en doble vía · `feature/dual-analysis` · ~4 j

**Es el corazón del informe.** Cambio de lógica de comparación, no de parsing.

**Vía 1 — manual → normativa** (evolución de lo existente). Por cada sección en alcance:
recuperar artículos candidatos de **todas** las normativas cargadas, graduar, analizar. Si no
cumple → alerta con *qué* artículos no satisface y *por qué*, apoyada en los umbrales de la app
(que solo funcionan tras `fix/config-wiring`). Unidad de resultado: **la sección**.

**Vía 2 — normativa → manual** (nueva). Por cada artículo en alcance: ¿está cubierto por alguna
sección? Requiere índice inverso.

**Cambios**

- `src/search_engine.py` → refactor a `SemanticIndex` genérico (parametrizado por
  `text_col`/`id_col`); `NormativaIndex` y **`ManualIndex`** quedan como subclases finas. API
  pública actual intacta.
- `src/comparator.py`: `run_via_manual()`, `run_via_normativa()` (veredicto por artículo:
  `nivel_adopcion ∈ {cubierto, parcial, no_cubierto, no_aplica}` + `brechas` +
  `secciones_que_lo_cubren`), y `run_dual()` que orquesta ambas sobre la misma `LinkTable`.
- **Caché de grading** por `(articulo_element_id, seccion_chunk_id)` compartida entre vías
  (S3): sin ella el costo se duplica.
- **Alerta de cobertura:** si `cobertura_global < 100 %`, banner con el conteo y el listado de
  artículos sin cobertura, y el dato entra al papel de trabajo. Premisa del Bloque A.
- Nuevo esquema Pydantic `AdopcionResult` en `llm_grader.py`, paralelo a `ComparisonResult`.
- UI: dos sub-pestañas — "Por sección (Vía 1)" y "Por artículo (Vía 2)" — más tarjeta de
  cobertura global.

**DoD** — Una corrida produce las dos vistas y el % de cobertura sobre el alcance seleccionado.
Un artículo sin ninguna sección relacionada aparece como `no_cubierto` y dispara la alerta. El
número de llamadas LLM ≈ `|secciones| + |artículos|` (no el producto), verificable con el
contador de los dobles de la Ola 0.

**Tests** — `tests/test_dual_analysis.py`: cobertura 100 %, parcial, artículo huérfano, sección
que satisface artículos de dos normas, y verificación del reuso de caché por conteo de
invocaciones.

---

#### Ítem 7 — Selector de alcance por lista · `feature/scope-selector` · ~1.5 j

**Bajo el supuesto S1 (dos selectores), sin confirmar.**

**Cambios**

- **NUEVO `src/scope.py`** (funciones puras, sin Streamlit)
  - `filtrar_articulos(normativa_df, doc_ids, numeros, secciones, incluir_referencias=False,
    tipos_elemento=…)`.
  - `filtrar_secciones(manual_df, doc_ids, jerarquias, chunk_ids)`.
  - `RunScope` serializable → entra en el `manifest.json` del checkpoint y en la hoja de
    trazabilidad.
- UI, pestaña 3 rediseñada: **Alcance normativo** (multiselect de artículos con filtro por norma
  y por título/capítulo, búsqueda por número/epígrafe, presets "Todo el articulado" / "Excluir
  referencias" —usa `es_referencia`, ya existente— / "Solo disposiciones") y **Alcance del
  manual** (multiselect de secciones agrupadas por jerarquía). "Muestra rápida (N)" se conserva
  como preset y deja de ser aleatoria: toma las primeras N del alcance vigente, con opción
  "aleatoria reproducible" explícita. Contador en vivo: "42 artículos × 18 secciones · ~60
  llamadas LLM · ~35 min estimados".

**DoD** — Se puede correr exactamente "Art. 35 y 36 de la Ley X contra el capítulo 5 del manual"
sin tocar código. El alcance queda registrado en el checkpoint y en el papel de trabajo.

**Tests** — `tests/test_scope.py` (filtros, presets, vacíos) + caso `AppTest`.

---

#### Ítem 10 — Flag de revisión manual · `feature/review-flag` · ~1 j

**Cambios**

- `src/coverage.py`: `requiere_revision_manual: bool` + `motivos_revision: list[str]` en ambas
  vistas. Disparadores: score en la banda de indecisión (`min_semantic_score ± delta`,
  configurable); `relevante is None` por fallo de parseo (ítem 4); conflicto entre coincidencia
  léxica y veredicto semántico; artículo sin cobertura (Vía 2); `nivel_cumplimiento == "parcial"`
  con brechas declaradas.
- UI: filtro "Solo revisión manual" y contador destacado. Excel: hoja dedicada (ítem 9).
- **Explícito:** la herramienta marca y explica; no intenta resolver estos casos
  automáticamente, tal como pide el Bloque A.

**DoD** — Ninguna fila marcada para revisión aparece como veredicto cerrado en el resumen; la
hoja "Revisión manual" lista el motivo de cada una.

**Tests** — `tests/test_review_flag.py`: un caso por disparador.

---

### Ola 4 · Calidad y entregable

#### Ítem 8 — Chunking semántico + evaluación de retrieval · `feature/semantic-chunking` · ~3 j

**Cambios**

- **NUEVO `src/chunking.py`**
  - `chunk_articulo(row, max_tokens)`: los artículos que exceden el presupuesto se subdividen
    respetando fronteras semánticas (numerales, literales, incisos — patrones ya presentes en
    los documentos ecuatorianos), con solape configurable.
  - Modelo **parent-child**: se indexa el sub-chunk, se devuelve el artículo padre. Preserva "el
    artículo como unidad de resultado" del Bloque A mientras mejora el recall.
  - Elimina el truncado ciego a 3000 caracteres de `src/document_parser.py:327`.
- `src/search_engine.py`: `build()` indexa sub-chunks y agrupa por `articulo_element_id` al
  devolver.
- **Arnés de evaluación**
  - `tests/data/retrieval_gold_es.yaml`: 30–50 consultas en español con los artículos esperados.
  - `scripts/eval_retrieval.py`: recall@k, MRR, nDCG@10 por backend/configuración; salida a
    `output/eval/retrieval_<fecha>.json` + tabla comparativa en markdown.
  - `tests/test_retrieval_es.py` con marcador `@pytest.mark.retrieval` y umbral mínimo
    (recall@5 ≥ 0.80) que falla si una regresión lo baja. **Requiere el CI de la Ola 0.**

**DoD** — Tabla comparativa antes/después por configuración (chunking on/off, con/sin reranker,
qwen3 vs. granite) con métricas reproducibles. La suite corre sin LLM (solo embeddings).

**Tests** — los del arnés, más `tests/test_chunking.py` (fronteras, solape, integridad
padre-hijo, artículos cortos que no se subdividen).

---

#### Ítem 9 — Papel de Trabajo (Excel) · `feature/papel-trabajo` · ~2.5 j

**Cambios**

- **NUEVO `src/papel_trabajo.py`** + **NUEVO `templates/papel_trabajo.yaml`**
  - La plantilla declara hojas, columnas, etiquetas, orden, anchos y formato condicional;
    cambiar el papel de trabajo no exige tocar Python.
  - Hojas:
    1. **Resumen** — entidad, normativas y manual evaluados, alcance, fecha, modelos usados,
       **% de cobertura** y semáforo por nivel.
    2. **Vía 1 — Manual** — una fila por sección: jerarquía, artículos aplicables, nivel de
       cumplimiento, análisis, brechas, prioridad.
    3. **Vía 2 — Normativa** — una fila por artículo: norma, número, epígrafe, nivel de
       adopción, secciones que lo cubren, brechas, prioridad.
    4. **Matriz N:N** — aristas artículo × sección con scores y origen.
    5. **Revisión manual** — solo lo marcado por el ítem 10, con el motivo.
    6. **Trazabilidad** — modelos, umbrales, `workspace_id`, `run_id`, hashes de documentos,
       duración, versión del código. Un papel de trabajo de auditoría tiene que ser reproducible.
  - **Membrete** desde `assets/brand/` (§8): el logo es configuración del backend, no solo del
    frontend.
  - Consume `src/design_tokens.py` para los fills (ítem T), no hex literales.
  - `src/comparator.py:111-165` queda como fachada delegando aquí.
- Columna `prioridad` derivada de nivel + criticidad del artículo (heurística documentada y
  sobreescribible en la plantilla).

**DoD** — El Excel se abre en Excel/LibreOffice sin advertencias, con las 6 hojas pobladas y
navegables. Cambiar una etiqueta de columna en el YAML se refleja sin tocar Python. Sin
`brand.json`, el membrete cae al placeholder y el archivo se genera igual.

**Tests** — `tests/test_papel_trabajo.py`: generación desde un bundle sintético, lectura de
vuelta con `openpyxl`, verificación de hojas/columnas/formato, plantilla alterada, y ausencia
de `brand.json`.

---

## 8. Sistema visual y marca

La identidad visual de referencia se extrajo del sitio corporativo público de la entidad
(hoja de estilo principal, 684 reglas) el 2026-08-12. **Los valores concretos no se versionan**
(S12): viven en `assets/brand/brand.json`, fuera de git, con `assets/brand/brand.example.json`
versionado y neutro como fallback.

### 8.1 Rasgos del sistema

- **Familia cromática:** verde institucional oscuro como primario, verde lima como acento, un
  teal secundario, y una escala de neutros de blanco a gris muy oscuro.
- **Tipografía:** una sans humanista con fallback de sistema; la familia concreta está en
  `assets/brand/brand.json`. **Debe empaquetarse localmente**, no servirse desde un CDN externo:
  en banca los CDN suelen estar bloqueados, y en Azure con private endpoints no habrá salida a
  internet.
- **Radios:** 2 px predominante, 3–4 px ocasional, 50 % solo en elementos circulares. Esquinas
  **casi rectas**.
- **Botones:** primario sólido sin borde; acento con texto blanco en estado activo.
- **Escala tipográfica:** `h1` grande en versalitas (50 px, 35 px en breakpoint), `h2` mucho más
  pequeño (19 px). El salto es grande y es un rasgo distintivo, no un descuido.
- **Layout:** grid de Bootstrap, `text-transform:uppercase` y peso ligero en labels y navegación.

> **Advertencia de implementación.** Si el frontend de la Fase 2 se monta con la estética por
> defecto de Tailwind/shadcn (`rounded-lg`, sombras suaves, mucho aire) **no se va a parecer**,
> aunque los colores sean exactos. La forma pesa tanto como el color: los radios, las versalitas
> y la densidad son tokens de primera clase.

### 8.2 Regla cromo/dato — separación por saturación

Es la decisión de diseño más importante y resuelve dos problemas a la vez.

**El problema:** el semáforo de cumplimiento usa verde para "cumple". Si el color institucional
también es verde, el auditor no distingue *cromo de marca* de *esto cumple*. En una herramienta
donde el color **es** el dato, eso es un defecto funcional, no estético.

**La regla:**

- **Cromo = verde de marca saturado.** Cabecera, navegación, botón primario, estado activo. El
  acento lima **nunca porta texto** (ver 8.3).
- **Datos = tintes desaturados con texto oscuro encima + icono + etiqueta.** Es el patrón que el
  Excel ya usa. El relleno lleva el tono semántico a baja saturación — los rellenos no necesitan
  4.5:1 — y el texto va en el gris más oscuro de la escala.
- **Ningún estado del semáforo usa el verde institucional ni el lima.** Para "cumple" basta un
  tinte verde-azulado separado del verde de marca; la carga semántica la llevan el icono y la
  etiqueta.

Así el auditor distingue cromo de dato por **saturación antes que por tono**, y ningún estado
depende del color en solitario — que es además lo correcto para daltonismo (~8 % de los hombres),
en un entregable de auditoría.

### 8.3 Mínimos de contraste (medidos, WCAG 2.1)

Verificados sobre blanco el 2026-08-12. Se documentan junto a cada token en
`brand.example.json` y se verifican en `tests/test_design_tokens.py`.

| Rol | Ratio | Uso permitido |
|-----|-------|---------------|
| Primario institucional | **6.18:1** | Texto normal, titulares, fondo de botón con texto blanco ✔ |
| Hover del primario | **4.37:1** | Relleno de área ✔ · texto pequeño ✘ |
| Teal secundario | **3.14:1** | Relleno, borde, icono, texto grande ✔ · texto normal ✘ |
| Acento lima | **2.20:1** | Solo bordes y estados sin texto ✘ para cualquier texto |
| Gris medio | **5.74:1** | Texto secundario ✔ |
| Gris oscuro | **10.70:1** | Texto sobre tintes claros ✔ |

**Dos consecuencias que no son negociables:**

1. El sitio de referencia usa el lima para `h2` a 19 px — **2.19:1**, cuando AA pide 4.5:1.
   **No se replica.** Los titulares van en el primario institucional (6.18:1).
2. El teal no puede llevar texto pequeño encima, ni en el color ni como fondo con texto blanco.
   Sirve como relleno, borde o icono.

### 8.4 Marca y logotipos

Rutas configurables, con placeholders versionados. Los archivos reales **no entran a git**.

```
assets/brand/                     ← en .gitignore
  brand.json                        tokens reales (paleta, tipografía)
  logo_org_banner_240x64.svg        cabecera principal
  logo_org_mark_64x64.svg           isotipo (favicon, sidebar colapsado)
  logo_org_horizontal_320x80.svg    membrete del papel de trabajo (Excel/PDF)
  logo_org_mono_240x64.svg          monocromo sobre fondo de marca
  logo_org_favicon_32x32.png

assets/brand/_placeholder/        ← versionado, genérico, sin marca
  brand.example.json                valores neutros documentados con sus ratios
  (mismos nombres de logo: cajas grises rotuladas con la dimensión)
```

Resueltos vía `.env`, con fallback al placeholder:

```
BRAND_LOGO_BANNER=assets/brand/logo_org_banner_240x64.svg
BRAND_LOGO_MARK=assets/brand/logo_org_mark_64x64.svg
BRAND_LOGO_MEMBRETE=assets/brand/logo_org_horizontal_320x80.svg
```

Un clon limpio del repositorio arranca sin ningún elemento del cliente. Es lo que hace el
repositorio publicable y continúa la postura del commit `32710e5`.

---

## 9. Fase 2 — Contenedor y frontend (esbozo)

No se detalla hasta cerrar la Fase 1. Lo que ya se sabe:

**Bloqueantes verificados**

1. **`ocrmac` es macOS-only y está declarado sin condicionar** (`dependencies/requirements.txt:4`,
   `dependencies/environment.yml:23`). En Linux arrastra `pyobjc-framework-Vision` y el
   `pip install` falla. **La imagen no compila hoy.** Hay que separar requisitos por plataforma.
2. **El camino de OCR en Linux nunca se ha ejercitado.** `src/document_parser.py:66-74` cae a
   `opts.do_ocr = do_ocr` sin `ocr_options`, y Docling descarga su motor por defecto con pesos
   propios. Hay que elegirlo y probarlo.
3. **MPS desaparece.** `_resolve_device("auto")` (`src/document_parser.py:25-33`,
   `src/embeddings.py:136`) resuelve a CPU. El workaround `KMP_DUPLICATE_LIB_OK` y el bug de NaN
   del reranker en MPS dejan de aplicar en el contenedor pero siguen vivos en desarrollo: **dos
   perfiles de ejecución que hay que mantener conscientemente.**
4. **Peso de la imagen.** torch + Docling + CrossEncoder + faiss en el mismo proceso: varios GB
   de imagen y de RAM residente. Condiciona el SKU y el arranque en frío, y es lo que obliga a
   reevaluar S9.

**Alcance**

- `Dockerfile` multi-stage (build de Node → runtime de Python), `requirements` por plataforma.
- `api/` con FastAPI sobre `src/service.py`: contrato OpenAPI, SSE para progreso.
- `frontend/` con Vite + React + TypeScript; tipos generados desde el OpenAPI
  (`openapi-typescript` + `openapi-fetch`), de modo que los modelos Pydantic **son** los tipos
  del frontend. TanStack Table + Virtual para la matriz N:N (miles de aristas: una tabla no
  virtualizada se reescribe entera). TanStack Query para el estado de servidor.
- Retirada de `AppTest`: `tests/test_streamlit_app_*.py` se sustituyen por pruebas de API
  (`httpx.ASGITransport`) y de frontend (Vitest + Playwright).
- Streamlit se congela y se retira cuando el frontend esté a la par.

**Estimación:** ~16–20 jornadas, de las cuales 8–12 son el frontend.

---

## 10. Fase 3 — Azure (esbozo)

**Destino:** contenedor en Azure con endpoint de Azure AI Foundry o Azure OpenAI.
**Región prevista:** East US o East US 2 — están entre las mejor surtidas de modelos.
*(Nota: la residencia de datos fuera de la región es una decisión de cumplimiento del banco,
pendiente de confirmar.)*

**Alcance**

- **P-b** — backend de Azure sobre las costuras de P-a: `AzureChatOpenAI` /
  `AzureAIChatCompletionsModel` + `AzureOpenAIEmbeddings`, con **Managed Identity**
  (`DefaultAzureCredential`). En producción no hay clave de API que filtrar; el `redact()` de
  P-a sigue cubriendo el `.env` de desarrollo.
- **SSO con Entra ID**, restringido al tenant de la entidad (`signInAudience: AzureADMyOrg`).
  Dos registros de aplicación: SPA (auth code + PKCE, `@azure/msal-react`) y API (scope
  expuesto). En el backend, validación de firma, `iss`, `aud`, `exp` **y `tid`** — este último
  es el control que hace verdadera la restricción al tenant y es el que más se omite. Se
  recomienda una librería establecida en vez de validar el JWT a mano.
  **Modo `AUTH_DISABLED` para desarrollo local, con una prueba que falle si puede activarse en
  un entorno desplegado.**
- **Autorización**, no solo autenticación: roles (`Auditor`/`Admin`), quién puede lanzar
  corridas (gastan tokens), workspaces por persona o por equipo. Aquí es donde el
  `workspace_id` de §3.3.1 deja de valer `"local"`.
- **Almacenamiento durable** (Blob o Azure Files): el sistema de archivos del contenedor es
  efímero. El registro de corridas pasa de "en memoria con espejo en disco" a **externo** —
  varias réplicas rompen un registro en proceso.
- **Worker separado.** Una corrida dura horas; ninguna conexión a través del ingress sobrevive
  eso. El job lleva la *identidad* del usuario como dato (`oid`, `workspace_id`) y el worker usa
  su **propia** Managed Identity para llamar a Azure. **Nunca se almacena ni se reproduce el
  token del usuario.**
- **IaC (Bicep), ACR, CI/CD.**
- **Reevaluación de S9 y del vector store:** con multiusuario, sostener un índice FAISS y un
  CrossEncoder en memoria por cada conjunto de documentos no escala. Azure AI Search es
  multi-tenant por diseño, externaliza el índice y su semantic ranker sustituye al CrossEncoder.
  Document Intelligence resolvería a la vez el OCR de Linux y el peso de la imagen. Ambas
  decisiones se toman **con las costuras de P-a ya puestas**, así que son cambios de
  configuración, no refactors.

**Estimación:** ~13–15 jornadas, más lo que resulte de la reevaluación.

**Prerrequisitos externos, ninguno cubierto hoy:** suscripción y recursos creados; registros de
aplicación en el tenant (requiere administrador); postura del banco sobre residencia de datos.

---

## 11. Módulos: mapa de cambios (Fase 1)

### Nuevos

| Archivo | Ítem | Propósito |
|---------|------|-----------|
| `pyproject.toml` | R | Empaquetado, pytest, linter |
| `.github/workflows/ci.yml` | R | Pruebas + escaneo de secretos |
| `tests/fixtures/` | R | Mini-corpus sintético y dobles deterministas |
| `tests/test_facade_compat.py` | S5 | Fija el contrato que consume `master.ipynb` |
| `src/errors.py` | 1, 4 | Taxonomía: abortar vs. degradar |
| `src/settings.py` | **P-a** | `.env`, precedencia, redacción de secretos |
| `src/providers.py` | **P-a** | Costuras y fábricas de proveedor |
| `.env.example` | **P-a** | Plantilla de endpoints (sin valores) |
| `src/model_registry.py` | 4 | `list_models` / `validate_model` / `preflight` |
| `src/design_tokens.py` | **T** | Fuente única de paleta y tipografía |
| `assets/brand/_placeholder/` | **T** | Marca neutra versionada |
| `src/service.py` | S10 | Orquestación sin Streamlit — habilita la Fase 2 |
| `app/run_manager.py` | 2, 3 | Corridas en background + re-attach |
| `src/checkpoint.py` | 3 | Persistencia incremental y reanudación |
| `src/coverage.py` | 5, 6, 10 | `CoverageLink`, `LinkTable`, vistas y cobertura |
| `src/scope.py` | 7 | Filtros de alcance (puros) |
| `src/chunking.py` | 8 | Sub-chunking semántico parent-child |
| `src/papel_trabajo.py` | 9 | Exportador Excel dirigido por plantilla |
| `templates/papel_trabajo.yaml` | 9 | Definición de hojas y columnas |
| `scripts/eval_retrieval.py` | 8 | CLI de evaluación de retrieval |
| `tests/data/retrieval_gold_es.yaml` | 8 | Gold set en español |

### Modificados

| Archivo | Ítems | Alcance del cambio |
|---------|-------|--------------------|
| `src/llm_grader.py` | 1, 4, 6, **P-a** | Clasificación de errores, grading robusto, `AdopcionResult`, chat model inyectado |
| `src/embeddings.py` | **P-a** | `LangChainEmbeddingsAdapter` genérico; DMR pasa a caso particular |
| `src/comparator.py` | 1, 3, 5, 6, **T** | Fail-fast, checkpoints, aristas N:N, `run_dual`, fills desde tokens |
| `src/search_engine.py` | 5, 6, 8, §2.2, **P-a** | `SemanticIndex` + `ManualIndex`, léxico por documento, prefijos, `index_meta.json` |
| `src/document_parser.py` | 8 | Integración del sub-chunking, sin truncado ciego |
| `src/config.py` | varios | Nuevos parámetros; deja de ser fuente de credenciales |
| `streamlit_app.py` | todos | Vista delgada sobre `service.py`: preflight, re-attach, selectores, doble vía, filtros |
| `app/theme.py` | **T** | Consume `design_tokens`; corrige el contraste del sidebar (`:89-91`) |
| `app/logging_utils.py` | 2 | Buffer de proceso por `run_id`; redacción de secretos |
| `dependencies/requirements.txt` | **P-a**, 2 | `python-dotenv` pasa de declarado a usado; `streamlit>=1.59` |
| `.gitignore` | **T**, S12 | `assets/brand/` excepto `_placeholder/` |
| `README.md` | todos | Arquitectura, fases, configuración |
| `TODO.md` | todos | Reemplazado por el seguimiento de este plan |

---

## 12. Secuencia y esfuerzo

```
FASE 1 · Piloto local                                        ≈ 28 j
  Ola 0 · Cimientos                        3 j
    ├─ chore/project-scaffold        (R)   1.5
    └─ test/pipeline-fixtures        (R)   1.5
  Ola 1 · Fiabilidad                       5 j
    ├─ fix/llm-failfast              (1)   1.5
    ├─ fix/config-wiring           (§2.2)  1
    ├─ feature/provider-seams      (P-a)   1
    ├─ feature/model-registry        (4)   1
    └─ feature/design-tokens         (T)   0.5
  Ola 2 · Servicio y estado                5 j
    ├─ feature/service-layer       (S10)   2
    └─ feature/run-manager         (2+3)   3
  Ola 3 · Núcleo metodológico            9.5 j
    ├─ feature/coverage-model        (5)   3
    ├─ feature/dual-analysis         (6)   4
    ├─ feature/scope-selector        (7)   1.5
    └─ feature/review-flag          (10)   1
  Ola 4 · Calidad y entregable           5.5 j
    ├─ feature/semantic-chunking     (8)   3   ← paralelizable desde la Ola 1
    └─ feature/papel-trabajo         (9)   2.5

FASE 2 · Contenedor y frontend                          ≈ 16–20 j
FASE 3 · Azure                                          ≈ 13–15 j
                                                        ─────────────
                                                  TOTAL ≈ 57–63 j
```

Con el ítem 8 en paralelo, la Fase 1 baja a ≈ 25 jornadas.

**Sobre el total:** construir para Azure desde el inicio habría salido en ~48 jornadas. El
fasado cuesta más porque parte de la UI del piloto se reescribe. Es el precio de no comprometer
infraestructura antes de validar el producto, y con `feature/service-layer` ese sobrecoste se
concentra en la capa de presentación. **Conviene que sea una decisión explícita, no una
sorpresa.**

---

## 13. Riesgos

| Riesgo | Impacto | Mitigación |
|--------|---------|------------|
| **`document_test/` no está disponible** | Los ítems 5, 6, 9 y 10 no se validan de extremo a extremo y el gold set del ítem 8 no se puede redactar | El mini-corpus sintético de la Ola 0 cubre las pruebas automatizadas; la validación con material real es requisito de cierre de la Fase 1 |
| La Vía 2 duplica el costo de LLM | Corridas de horas en M1 16 GB | Caché de grading compartida (S3) + selector de alcance (ítem 7) como control obligatorio |
| Indexar el manual sube el consumo de RAM | Segfault/OOM ya visto en el proyecto | Índices construidos en secuencia, nunca simultáneos; `EMBED_BATCH_SIZE` conservador; se mantiene `KMP_DUPLICATE_LIB_OK` |
| El refactor N:N rompe `master.ipynb` | Pérdida del flujo de trabajo actual | `results_df` y `export_excel()` como fachada (S5), fijados por `test_facade_compat.py` **antes** del refactor |
| Modelos pequeños no producen JSON válido | El ítem 4 degrada todo a "revisión manual" | El preflight advierte sobre modelos por debajo del mínimo recomendado; se documenta el mínimo viable |
| **S1 sin confirmar** | Retrabajo en la UI de la pestaña 3 | La lógica va en `src/scope.py`, independiente de la UI; un cambio de criterio solo afecta widgets |
| El gold set de retrieval usa manuales confidenciales | Fuga de material corporativo | Consultas parafraseadas; el gold set referencia solo IDs de artículos públicos; `document_test/` sigue en `.gitignore` |
| **Se pierde la disciplina de §3.3** | La Fase 2 o la 3 se convierten en un rewrite | Las siete restricciones son criterio de revisión de PR, no recomendaciones |
| Fuga de credenciales o de identidad del cliente | Exposición **irreversible: el repo es público** | `redact()` obligatorio; `assets/brand/` y `.env` fuera de git; compuerta **local** pre-commit/commit-msg/pre-push + filtro que quita salidas de notebook (`.claude/scripts/instalar_guardas.sh`). CI es segunda red, no primera: corre después del push |
| **La imagen Linux no compila (`ocrmac`)** | Bloquea la Fase 2 entera | Detectado y documentado en §9; se resuelve en la primera rama de esa fase |
| Costos de nube sin control | Factura inesperada | Fase 3. El contador de llamadas del ítem 6 queda listo en Fase 1 para alimentar la estimación |

---

## 14. Aceptación — Fase 1

- [ ] Con el DMR caído, ninguna corrida produce filas `no_aplica`: se detiene y lo dice.
- [ ] Ningún candidato se marca relevante por defecto ante un fallo de parseo.
- [ ] El modelo configurado se valida contra la lista real del DMR antes de arrancar.
- [ ] Ningún módulo de `src/` construye un cliente de LLM o de embeddings directamente.
- [ ] Un índice FAISS construido con un modelo y cargado con otro se rechaza con mensaje claro.
- [ ] Refrescar el navegador durante una corrida no pierde ni duplica el progreso.
- [ ] Una corrida interrumpida se reanuda sin repetir llamadas LLM.
- [ ] La relación artículo↔sección es consultable N:N en ambos sentidos, con varias normativas.
- [ ] Cada corrida entrega las dos vías y el % de cobertura, con alerta explícita si < 100 %.
- [ ] El alcance se elige por lista (artículos y secciones), no solo por cantidad.
- [ ] Existe una medición reproducible de retrieval en español, con umbral de regresión en CI.
- [ ] El Excel es un papel de trabajo configurable, con trazabilidad completa de la corrida.
- [ ] Los casos no evidentes quedan marcados para el auditor, con motivo, sin resolución automática.
- [ ] `streamlit_app.py` no contiene lógica de pipeline: solo presentación sobre `service.py`.
- [ ] Un clon limpio del repositorio arranca sin ningún elemento identificable del cliente.
- [ ] Ningún hex de marca es un literal en código versionado; UI y Excel leen los mismos tokens.
- [ ] Todas las salidas viven bajo `output/workspaces/<workspace_id>/runs/<run_id>/`.
- [ ] `master.ipynb` sigue funcionando (`test_facade_compat.py` en verde).

---

## 15. Fuera de alcance (follow-up)

Ítems del anexo para una fase siguiente: limpieza de portada/índice (11) · ciclo de corrección
y etiquetado (12) · rediseño UX para auditor no técnico y configuración avanzada (13) · nodo VLM
para estructura vía índice (16) · módulo de comparación entre versiones de la normativa (17,
bloqueado por el punto pendiente 3).

**Adelantados de hecho:**
- **Ítem 14** (contraste del sidebar) — se corrige dentro del ítem T.
- **Ítem 15** (rango de hilos según backend) — las costuras de P-a lo dejan a un paso: basta
  añadir `concurrencia_recomendada` al `ProviderSpec`. Relevante solo en Fase 3, donde
  `MAX_WORKERS=1` (calibrado para DMR secuencial en M1, `src/config.py:61`) deja de aplicar.
- **Ítem 18** (análisis de costos) — el contador de llamadas del ítem 6 queda listo en Fase 1;
  falta solo el precio por token, que es dato de Fase 3.

---

## 16. Pendientes de definición

### Con el negocio

1. **¿Un selector o dos?** — se avanza con el supuesto S1 (dos). **Confirmar antes de cerrar el
   ítem 7.** Es lo único del anexo que sigue sin decidir y que afecta a la Fase 1.
2. **Nota incompleta "Analizar las…"** del documento original — sin alcance determinable.
3. **Casos del módulo de comparación entre versiones** (Bloque E) — bloquea el ítem 17.
4. **Disponibilidad de `document_test/`** — condiciona la validación de cierre de la Fase 1.

### Con TI / infraestructura (Fase 3)

5. Suscripción y recursos de Azure: proyecto de Foundry o recurso de Azure OpenAI, ACR.
6. Quién puede crear los registros de aplicación en el tenant (requiere administrador).
7. Postura del banco sobre residencia de datos fuera de la región.
8. Modelo de autorización: roles y si los workspaces son por persona o por equipo.

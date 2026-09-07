# Plan Fase 2 — Interfaz moderna, API HTTP y visores de evidencia

**Rama:** `feature/v4-modern-ui-pdf-viewer`
**Fecha:** 2026-09-06
**Precede:** `PLAN_MEJORAS_ANEXO.md` §9 («Fase 2 — Contenedor y frontend (esbozo)»), que este
documento sustituye y detalla.
**Estado de la Fase 1:** cerrada en `comparador-v3-linux` hasta el ítem 9 (papel de trabajo) e ítem 8
(chunking semántico + arnés de evaluación de retrieval). El pipeline, la capa de servicio
(`src/service.py`), el registro de corridas (`app/run_manager.py`), los checkpoints
(`src/checkpoint.py`) y los tokens de marca (`src/design_tokens.py`) ya existen y están
probados.

---

## 0. Resumen de qué se construye y por qué ahora

La Fase 1 dejó la orquestación fuera de la interfaz **a propósito** (supuesto S10 del anexo):
`src/service.py` no importa Streamlit y no guarda estado entre llamadas. Esa decisión es lo
que hace que esta fase escriba **presentación y transporte**, no lógica de negocio. Si esta
fase tuviera que volver a implementar el pipeline, sería la señal de que S10 falló — y no
falló: `tabular()`, `construir_indice()`, `comparar()`, `comparar_dual()` y `exportar()` son
llamables tal cual desde un manejador HTTP.

Lo que se añade:

| Capa | Qué se añade | Por qué no existe hoy |
|---|---|---|
| Transporte | `api/` — FastAPI sobre `src/service.py`, con SSE para progreso | Streamlit era el único consumidor; el estado vivía en `st.session_state` (por pestaña) |
| Presentación | `frontend/` — Vue 3 + Vite + TypeScript + Tailwind, SPA servida por el mismo proceso | Streamlit no permite un visor PDF con capa de resaltado ni un layout responsive real |
| Evidencia | Visor PDF (PDF.js) + inspector de chunks | Hoy la evidencia es una celda de Excel: no se puede verificar contra el documento fuente |
| Procedencia | Página y *bounding box* en el modelo de datos del parser | **No existe** — es el bloqueante principal de esta fase, ver §2.1 |
| Identidad | Tokens de marca servidos como variables CSS al navegador | `src/design_tokens.py` los sirve a Python (Streamlit y Excel), no a un cliente HTTP |

### 0.1 Divergencia declarada respecto del anexo: Vue 3, no React

`PLAN_MEJORAS_ANEXO.md` §4 fija en el supuesto **S11** que el frontend de la Fase 2 sería
«Vite + React + TypeScript». **Este documento lo enmienda a Vue 3 + Vite + TypeScript +
Tailwind CSS por decisión explícita del usuario.**

Se registra como enmienda y no como corrección silenciosa porque S11 es un supuesto publicado
y otras decisiones se apoyaron en él. Lo que **no** cambia con la enmienda:

- El contrato sigue siendo el OpenAPI de FastAPI, y los tipos de TypeScript se siguen
  generando desde él (`openapi-typescript`). Los modelos Pydantic **son** los tipos del
  frontend, con Vue igual que con React. Esta es la parte de S11 que importaba.
- El backend, el pipeline y el Dockerfile multi-stage no se ven afectados: Node sigue
  apareciendo solo en la etapa de *build*.

Lo que sí cambia, y hay que decidir explícitamente:

- **TanStack Table + TanStack Virtual** tienen adaptador oficial para Vue (`@tanstack/vue-table`, `@tanstack/vue-virtual`).
- **TanStack Query** pasa a `@tanstack/vue-query`, oficial.
- El estado de cliente pasa a **Pinia**, estándar reactivo de Vue 3.

---

## 1. Arquitectura General del Sistema

### 1.1 Backend: FastAPI Modular (`api/`)
FastAPI expone endpoints tipados con Pydantic v2, reutilizando directamente `src/service.py`:
- `GET /api/health` — Chequeo de salud del servicio y de modelos conectados.
- `GET /api/config/providers` — Estado y catálogo de proveedores (DMR, Ollama, Vertex AI, Azure AI Foundry).
- `GET /api/documents` — Lista de normativas y manuales disponibles y subidos.
- `POST /api/documents/tabular` — Tabulación de documentos (Docling) con reporte de progreso.
- `GET /api/documents/{tipo}/{doc_id}/pdf` — Entrega segura del binario PDF para el visor.
- `GET /api/documents/{tipo}/{doc_id}/pages/{page}/text` — Texto y bboxes extraídos por página.
- `POST /api/index/build` — Construcción de índice semántico FAISS.
- `POST /api/compare/start` — Inicialización de corrida de comparación con `RunScope`.
- `GET /api/compare/stream/{run_id}` — Stream SSE (Server-Sent Events) de progreso en tiempo real.
- `GET /api/compare/runs/{run_id}` — Estado y resultados (bundle dual, LinkTable, cobertura).
- `GET /api/compare/runs/{run_id}/export/{formato}` — Descarga de Papel de Trabajo Excel (6 hojas) o JSON.
- `GET /api/theme/tokens` — Exportación de tokens de marca a variables CSS JSON.
- Servidor estático SPA: `StaticFiles(directory="frontend/dist", html=True)` montado en `/`.

### 1.2 Frontend: Vue 3 + Vite + Tailwind (`frontend/`)
Estructura modular en `frontend/src/`:
- `components/layout/`: Header, Navigation Stepper, Responsive Drawer para móvil/iPad.
- `components/viewer/`: `PdfViewer.vue` (PDF.js con zoom, pan, recuadros bbox, salto a página) y `ChunkInspector.vue` (visualizador de fragmento con hovers y comparativa).
- `components/steps/`:
  - `Step1Documents.vue`: Carga, previsualización y tabulación.
  - `Step2Index.vue`: Estado del índice FAISS, búsqueda semántica interactiva.
  - `Step3Scope.vue`: Selector de alcance interactivo (presets normativos, búsqueda, conteo dinámico).
  - `Step4Results.vue`: Cobertura global KPI, alertas, sub-pestañas Vía 1 / Vía 2, filtro de revisión manual y exportación de Papel de Trabajo.
- `stores/`: Pinia stores (`useAppStore`, `useDocumentStore`, `useRunStore`).
- `services/api.ts`: Cliente HTTP con fetch tipado y EventSource para SSE.

---

## 2. Design System Paramétrico (Azul y Blanco)

El sistema visual se gobierna mediante CSS Custom Properties definidas en `:root` y configuradas en `tailwind.config.js`:

```css
:root {
  /* Cromo principal — Paramétrico genérico azul y blanco */
  --color-primary: #1e40af;       /* Azul corporativo base (blue-800) */
  --color-primary-hover: #1d4ed8; /* Azul interactivo hover (blue-700) */
  --color-primary-light: #eff6ff; /* Azul muy suave para fondos activos (blue-50) */
  --color-accent: #3b82f6;        /* Azul de acento (blue-500) */
  --color-surface: #ffffff;       /* Blanco puro */
  --color-background: #f8fafc;    /* Fondo pizarra claro (slate-50) */
  --color-border: #e2e8f0;        /* Borde neutro (slate-200) */
  
  /* Textos neutros accesibles (WCAG >= 4.5:1) */
  --color-text-main: #0f172a;     /* Pizarra oscura (slate-900) */
  --color-text-muted: #64748b;    /* Gris secundario (slate-500) */

  /* Estados de cumplimiento (alineados con src/design_tokens.py) */
  --color-state-cumple-bg: #dcf0e0;
  --color-state-cumple-fg: #15803d;
  --color-state-parcial-bg: #fff2cc;
  --color-state-parcial-fg: #b45309;
  --color-state-omision-bg: #fce8e6;
  --color-state-omision-fg: #b91c1c;
  --color-state-no-aplica-bg: #f3f4f6;
  --color-state-no-aplica-fg: #737373;
}
```

Para personalizar en el futuro, solo se requiere cambiar los valores de las variables en un archivo de configuración (`theme.json` o CSS) sin alterar la lógica de los componentes.

---

## 3. Visores de Evidencia e Inspector de Chunks

### 3.1 Visor de PDF (`PdfViewer.vue`)
- Basado en `pdfjs-dist` cargando dinámicamente el worker.
- Renderiza páginas en canvas HTML5 con capa superpuesta de anotaciones SVG/Canvas:
  - Soporte de recuadros (*bounding box* [x1, y1, x2, y2] normalizados a viewport).
  - Salto programático de página al hacer clic en un hallazgo o artículo.
  - Controles táctiles (*pinch-to-zoom*, deslizamiento en iPad / tablets y móviles).
  - Indicador de página actual y selector de zoom (50%, 100%, 150%, ajuste a ancho).

### 3.2 Inspector de Chunks y Evidencia (`ChunkInspector.vue`)
- Panel deslizante (*Drawer*) en móvil/iPad o split-pane en escritorio.
- Al pasar el cursor (*hover*) o tocar un artículo o sección:
  - Muestra el texto exacto del sub-chunk (`chunk_text`), resaltando coincidencias léxicas.
  - Despliega metadatos del artículo padre: número, epígrafe, norma de origen, jerarquía.
  - Muestra badges con los scores: similitud semántica, reranker y veredicto del grading.
  - En caso de revisión manual (Ítem 10), muestra tarjeta de alerta con los motivos específicos de duda o brecha.

---

## 4. Multiplataforma y Proveedores de Modelos

El backend funciona homogéneamente en **macOS y Linux**:
- **DMR (Docker Model Runner):** Endpoint OpenAI-compat para embeddings y LLM local.
- **Ollama:** Aceleración por GPU local (NVIDIA CUDA en Linux, Apple Silicon MPS en macOS) para embeddings (`bge-m3`, `nomic-embed-text`) y modelos de inferencia (`qwen2.5`, `granite3-dense`).
- **GCP Vertex AI:** Integrado para LLMs de grado productivo (`gemini-2.5-flash`, etc.) mediante Google Cloud SDK y credenciales de entorno.
- **Azure AI Foundry:** Soporte nativo de endpoints Azure OpenAI / Model Catalog mediante cliente OpenAI estándar parametrizado por `AZURE_OPENAI_ENDPOINT` y `AZURE_OPENAI_API_KEY`.
- Detección automática de dispositivo (`cuda` en Linux con GPU NVIDIA, `mps` en Mac, fallback automático a `cpu`).

---

## 5. Fases de Implementación Secuenciales

### Ola 0 · Andamiaje y Servidor Base FastAPI
- Creación de `api/`: configuración, modelos Pydantic, dependencias, rutas base y tests con `pytest` y `httpx`.
- Configuración de `src/providers.py` con soporte explícito para Azure AI Foundry además de Vertex, Ollama y DMR.
- Servidor estático integrado en FastAPI listo para servir el build de Vue.

### Ola 1 · Frontend Scaffolding (Vue 3 + Vite + Tailwind + Pinia)
- Inicialización en `frontend/` con Vue 3, TypeScript, Tailwind CSS, Lucide Icons y Pinia.
- Implementación de tokens de diseño paramétricos azul/blanco y reset responsive (Mobile-first, iPad, Desktop).
- Componentes base: Button, Badge, Modal, Drawer, MetricCard, Stepper.

### Ola 2 · Visor de PDF y Componentes de Evidencia
- Integración de `pdfjs-dist` en `PdfViewer.vue` con capa de resaltado y navegación.
- Implementación de `ChunkInspector.vue` con tooltips, hovers reactivos y drawer contextual.
- Endpoint `/api/documents/{tipo}/{doc_id}/pdf` para servir los binarios con caché y byte-ranges.

### Ola 3 · Flujo Completo en 4 Pasos (UX Guiada)
- Paso 1: Carga y tabulación con barra de progreso.
- Paso 2: Índice semántico con búsqueda de prueba en vivo.
- Paso 3: Selector de alcance (Ítem 7) con conteo dinámico en tiempo real y toggle de doble vía.
- Paso 4: Resultados con Cobertura Global, sub-pestañas Vía 1 / Vía 2, filtro de revisión manual (Ítem 10) y visor split-screen (PDF a la izquierda, hallazgos a la derecha).

### Ola 4 · Compilación, Verificación y Pruebas
- Build del frontend (`npm run build` genera `frontend/dist`).
- Pruebas automatizadas de endpoints FastAPI (`tests/test_api_*.py`).
- Pruebas de integración E2E del servicio completo.

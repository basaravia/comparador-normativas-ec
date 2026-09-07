# 📖 Guía de Uso y Contratos Swagger de la API

Esta carpeta contiene los contratos de especificación formal y colecciones para consumir, probar y automatizar la API REST y Server-Sent Events (SSE) del **Comparador Automatizado de Normativas vs Manuales Internos**.

---

## 🎯 Acceso Rápido a la Documentación Interactiva

Cuando el servidor FastAPI esté en ejecución (por ejemplo en `http://localhost:8000`):

1. **Swagger UI Interactivo:**
   👉 Visita en tu navegador: **[`http://localhost:8000/docs`](http://localhost:8000/docs)**
   Permite explorar y probar interactivamente cada endpoint con botones "Try it out" y visualizar esquemas de solicitud y respuesta.

2. **ReDoc (Documentación Estructurada):**
   👉 Visita en tu navegador: **[`http://localhost:8000/redoc`](http://localhost:8000/redoc)**
   Vista de especificación limpia para lectura técnica y consulta de modelos de datos.

3. **Contrato OpenAPI 3.1 en JSON:**
   👉 URL: **[`http://localhost:8000/openapi.json`](http://localhost:8000/openapi.json)**
   Archivo estático local: [`openapi.json`](./openapi.json)

---

## 📮 Cómo Importar y Usar en Postman

Tienes dos formas directas de cargar la colección en Postman:

### Método 1: Importar archivo local
1. Abre **Postman**.
2. Haz clic en el botón superior **Import** (o `Ctrl + O` / `Cmd + O`).
3. Arrastra o selecciona el archivo:
   `docs/api/postman_collection.json`
4. Postman creará la colección con todos los endpoints organizados por carpetas (`Sistema y Proveedores`, `Documentos`, `Índice Semántico`, `Comparación`, `Diseño y Tokens`).
5. La variable de entorno `{{base_url}}` viene preconfigurada en `http://localhost:8000`.

### Método 2: Importar desde URL en vivo
1. Con la API levantada, abre Postman -> **Import**.
2. En la barra de URL escribe:
   `http://localhost:8000/api/postman.json`
3. Haz clic en **Import**.

---

## 🌐 Cómo Importar en Swagger Editor o SwaggerHub (swagger.io)

1. Ingresa a **[Swagger Editor](https://editor.swagger.io/)** en tu navegador.
2. En el menú superior selecciona: **File -> Import file**.
3. Selecciona el archivo [`docs/api/openapi.json`](./openapi.json).
4. El editor cargará automáticamente el árbol de endpoints, esquemas Pydantic y documentación con capacidad de generar clientes en múltiples lenguajes (TypeScript, Python, cURL, Java, etc.).

---

## 🔄 Flujo de Trabajo y Ejemplos con `cURL`

### 1. Chequeo de Salud y Proveedores
```bash
# Verificar estado del servicio y aceleración de hardware
curl -X GET http://localhost:8000/api/health

# Consultar catálogo de modelos (DMR, Ollama, Vertex AI, Azure AI Foundry)
curl -X GET http://localhost:8000/api/config/providers
```

### 2. Gestión de Documentos
```bash
# Listar normativas y manuales disponibles
curl -X GET http://localhost:8000/api/documents

# Descargar PDF binario (con soporte de byte-ranges para el visor PDF.js)
curl -X GET http://localhost:8000/api/documents/normativa/LEY-A-2026.pdf/pdf --output norma.pdf

# Ejecutar tabulación Docling
curl -X POST http://localhost:8000/api/documents/tabular \
  -H "Content-Type: application/json" \
  -d '{
    "normativas": ["LEY-A-2026.pdf"],
    "manuales": ["MANUAL-INTERNO.pdf"],
    "do_ocr": false
  }'
```

### 3. Índice Semántico con Chunking Parent-Child
```bash
# Construir índice FAISS con chunking semántico
curl -X POST http://localhost:8000/api/index/build \
  -H "Content-Type: application/json" \
  -d '{
    "use_chunking": true,
    "max_tokens": 512,
    "solape": 50
  }'

# Probar búsqueda semántica y reranking
curl -X POST http://localhost:8000/api/index/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "política de crédito y análisis de capacidad de pago",
    "top_k": 3,
    "min_score": 0.30,
    "use_reranker": true
  }'
```

### 4. Comparación y Streaming de Progreso (SSE)
```bash
# Iniciar corrida de análisis en doble vía
curl -X POST http://localhost:8000/api/compare/start \
  -H "Content-Type: application/json" \
  -d '{
    "dual_mode": true,
    "min_score": 0.30,
    "top_k": 5
  }'
# Respuesta: {"run_id": "20260906_235000", "status": "iniciado", "stream_url": "/api/compare/stream/20260906_235000"}

# Escuchar stream de eventos SSE en tiempo real
curl -N -X GET http://localhost:8000/api/compare/stream/20260906_235000

# Consultar resultados, cobertura y revisión manual (Ítem 10)
curl -X GET http://localhost:8000/api/compare/runs/20260906_235000

# Descargar Papel de Trabajo de Auditoría en Excel (6 hojas)
curl -X GET http://localhost:8000/api/compare/runs/20260906_235000/export/excel \
  --output papel_trabajo.xlsx
```

### 5. Tokens de Diseño Paramétricos
```bash
# Obtener variables CSS y paleta activa (azul y blanco paramétrico)
curl -X GET http://localhost:8000/api/theme/tokens
```

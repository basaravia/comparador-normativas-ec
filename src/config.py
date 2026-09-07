"""Configuración central — rama Linux (comparador-v3-linux).

`feature/comparador-v2` calibraba estas constantes para Apple Silicon + Docker Model
Runner (DMR). Esta rama corre en Linux x86_64 sin DMR, así que los tres roles de modelo
se repartieron entre backends que sí existen en esta máquina:

LLM (análisis comparativo, "el router" en la conversación con el usuario):
  Vertex AI (Gemini), vía `Provider.VERTEX` en providers.py — mismo proyecto GCP
  (`hermes-vertex-86af98`) que ya usa Hermes Agent, con un modelo "flash" ligero para
  pruebas. Requiere `GOOGLE_APPLICATION_CREDENTIALS` apuntando a la service account
  (ver .env, gestionado aparte por no ser un valor no-sensible).

EMBEDDINGS:
  Ollama, servido localmente y corriendo 100% en la GPU (GTX 960M, 4GB VRAM). Ollama
  expone un endpoint OpenAI-compatible en /v1, así que se reutiliza el mismo
  `Provider.OPENAI_COMPAT` que usaba DMR en macOS — solo cambia el endpoint y el
  modelo.
    - qwen3-embedding:0.6b (1024 dim) → el mismo recomendado en el config original de
      macOS (`ai/qwen3-embedding:latest`, DMR), pero en el tamaño que cabe en esta GPU.
      El tag "latest"/"8b" de Ollama (4.7GB, el que da 2560 dim que citaba el config
      original) se probó primero y **revienta**: "CUDA error: out of memory" a mitad
      de la inferencia, confirmado en el log de `ollama serve` — el 55%/45% CPU/GPU
      split que Ollama intenta al no caber entero no evita el crash, solo lo retrasa
      hasta el forward pass real. 0.6b sí cabe entero (~2.4GB VRAM) y corre 100% GPU.
    - bge-m3 (1024 dim, ~930MB VRAM) queda descargado como alternativa si 0.6b da
      peor calidad semántica de la esperada en español legal — cambiar solo
      OLLAMA_EMBED_MODEL, no hace falta tocar el pipeline.

  Vertex AI también tiene embeddings multilingües compatibles con español —
  validado en vivo el 2026-09-02, ver VERTEX_EMBED_* más abajo — pero Ollama sigue
  siendo el default: es gratis, local y sin latencia de red, y ya corre bien en esta
  GPU. Vertex queda como opción vía `Provider.VERTEX` (embeddings=True en
  providers.py) para quien prefiera un solo proveedor de nube o necesite escalar más
  allá de lo que la GPU local aguanta.

RERANKER:
  Sin cambios de fondo: en macOS ya corría vía sentence-transformers/transformers
  (ver providers.py — DMR/vllm-metal no soporta reranking mode ahí tampoco). Lo único
  que faltaba para Linux era que la selección de device reconociera CUDA además de
  MPS/CPU (antes solo miraba MPS) — corregido en `providers._reranker_local`.
"""

# ── Vertex AI (LLM: análisis comparativo + grading) ────────────────────────
VERTEX_PROJECT_ID: str = "hermes-vertex-86af98"
# "global", no una región concreta (p. ej. us-central1): probado en vivo el
# 2026-09-02 — los modelos Gemini de este proyecto devuelven 404 "Publisher model...
# was not found" en us-central1 y sí responden en global. Si se cambia de proyecto GCP,
# volver a probarlo primero (ver el bloque de verificación en dependencies/README.md).
VERTEX_LOCATION: str = "global"
# "Lite" a propósito para pruebas, como pidió el usuario. Verificado en vivo contra
# este proyecto el 2026-09-02 (gemini-3.6-flash SÍ existe mismo pero costaba más caro;
# gemini-3.1-flash-lite es la alternativa aún más ligera si esto sigue resultando caro
# para pruebas). Subir a un modelo mayor cuesta cambiar solo esta constante (o
# VERTEX_LLM_MODEL por entorno), no tocar el pipeline.
VERTEX_LLM_MODEL: str = "gemini-3.5-flash-lite"

# ── Vertex AI (embeddings — opción validada, no es el default) ─────────────
# text-multilingual-embedding-002: modelo multilingüe dedicado de Google (documentado
# para ~100 idiomas, español incluido), 768 dim. Alternativa probada y descartada:
# text-embedding-005 (768d) está optimizado para inglés, no es el multilingüe
# dedicado. gemini-embedding-001 (3072d) también funciona y da mayor calidad, pero
# es más caro/pesado de indexar — cambiar VERTEX_EMBED_MODEL/DIM si hace falta.
#
# Gotcha validado en vivo el 2026-09-02, al revés que VERTEX_LOCATION (chat): los
# modelos de embedding de este proyecto solo responden en "us-central1" — "global"
# da 404 "Publisher Model not found" para estos.
#
# Fragilidad detectada al probarlo: langchain-google-vertexai==2.1.2 (pin obligado
# por el conflicto de langchain-core, ver dependencies/README.md) usa la ruta
# `vertexai._model_garden`, marcada por Google como "deprecated as of June 24, 2025
# and will be removed on June 24, 2026" — fecha ya pasada respecto a hoy y sigue
# funcionando, pero puede dejar de hacerlo sin aviso previo. Si esto empieza a fallar,
# es la primera sospecha antes de revisar credenciales o el modelo.
VERTEX_EMBED_MODEL: str = "text-multilingual-embedding-002"
VERTEX_EMBED_LOCATION: str = "us-central1"
VERTEX_EMBED_DIM: int = 768

# ── Ollama (embeddings, GPU local) ─────────────────────────────────────────
OLLAMA_BASE_URL: str = "http://localhost:11434/v1"
OLLAMA_EMBED_MODEL: str = "qwen3-embedding:0.6b"
OLLAMA_EMBED_DIM: int = 1024

# ── Alias DMR_* ─────────────────────────────────────────────────────────────
# `embeddings.py`, `llm_grader.py`, `service.py`, `streamlit_app.py` y `master.ipynb`
# importan estos nombres. Se conservan (en vez de renombrarlos en cada sitio) para que
# esta rama no tenga que tocar más módulos de los necesarios; lo que cambia es el
# *valor*, no el símbolo. En esta rama solo los usa el backend de embeddings — el LLM
# ya no pasa por Provider.DMR, ver Provider.VERTEX en providers.py.
DMR_BASE_URL: str = OLLAMA_BASE_URL
DMR_EMBED_MODEL: str = OLLAMA_EMBED_MODEL
DMR_EMBED_DIM: int = OLLAMA_EMBED_DIM
DMR_LLM_MODEL: str = VERTEX_LLM_MODEL
DMR_LLM_FALLBACK: str = "qwen3:4b"  # modelo Ollama local ya presente, solo para pruebas

# Reranker local — CrossEncoder vía sentence-transformers; multilingüe, ~1.2GB.
# Corre en CUDA en esta máquina (GTX 960M) o CPU si no hay GPU disponible.
RERANKER_MODEL: str = "Qwen/Qwen3-Reranker-0.6B"

# ── Parámetros de búsqueda ─────────────────────────────────────────────────
FAISS_TOP_K: int = 5          # candidatos iniciales del índice FAISS
RERANKER_TOP_N: int = 3       # candidatos tras reranking
MIN_SEMANTIC_SCORE: float = 0.30  # umbral mínimo de similitud coseno

# ── Revisión manual (ítem 10) ─────────────────────────────────────────────
# Semi-ancho de la "banda de indecisión" alrededor de MIN_SEMANTIC_SCORE: un candidato
# con score en [0.25, 0.35] pasó o no pasó el corte por centésimas, y esa distinción no
# la sostiene ningún embedding. En vez de fingir que el umbral es una frontera nítida, se
# marca la franja para que la mire una persona (Bloque A: la herramienta marca y explica,
# no resuelve). Subirlo marca más aristas y cuesta horas de revisión; bajarlo a 0 apaga
# el disparador salvo el empate exacto con el umbral.
DELTA_INDECISION: float = 0.05

# ── Parámetros Docling (parseo de manuales) ───────────────────────────────
DOCLING_MAX_TOKENS: int = 512  # max tokens por chunk HybridChunker

# ── Parámetros LLM ────────────────────────────────────────────────────────
LLM_TEMPERATURE: float = 0.0
LLM_MAX_TOKENS: int = 4096
LLM_GRADER_MAX_TOKENS: int = 2048

# ── Concurrencia ──────────────────────────────────────────────────────────
# Vertex es un backend de nube: a diferencia de DMR (secuencial, un proceso local),
# soporta varias llamadas simultáneas sin degradar cada una. 2 es conservador para no
# gastar cuota de golpe durante las pruebas; subirlo no requiere tocar el pipeline.
MAX_WORKERS: int = 2
EMBED_BATCH_SIZE: int = 32    # textos por lote en encode()

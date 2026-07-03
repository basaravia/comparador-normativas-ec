"""Configuración central: endpoints DMR, modelos y parámetros globales.

Análisis de modelos disponibles (Docker Model Runner):

EMBEDDINGS:
  - ai/qwen3-embedding:latest       → 2560 dim | Recomendado: mejor calidad semántica en español
  - ai/granite-embedding-multilingual:latest → 768 dim | Alternativa: más rápido, menor huella de RAM
  - docker.io/ai/embeddinggemma-vllm:latest → uso verificar dim antes de cambiar

LLM (análisis comparativo):
  - docker.io/ai/gemma4:latest      → Recomendado: mejor capacidad de razonamiento y español
  - ai/qwen3-vl:4B-UD-Q4_K_XL      → Alternativa: 4B params cuantizado (menor RAM)
  - docker.io/ai/smollm2-vllm:1.7B  → Solo pruebas (muy pequeño para análisis legal)

RERANKER:
  - docker.io/ai/qwen3-reranker-vllm:0.6B → Reranking semántico post-FAISS (Phase 2b)
"""

# ── Docker Model Runner ────────────────────────────────────────────────────
DMR_BASE_URL: str = "http://localhost:12434/engines/v1"

# Modelo de embedding por defecto (mejor calidad para textos legales en español)
DMR_EMBED_MODEL: str = "ai/qwen3-embedding:latest"
DMR_EMBED_DIM: int = 2560  # cambiar si se usa granite (768)

# Modelo LLM para análisis comparativo (grading + análisis semántico)
# gemma4 tiene razonamiento interno (thinking) — requiere max_tokens >= 4096
# smollm2-vllm:1.7B funciona pero es demasiado pequeño para análisis legal complejo
DMR_LLM_MODEL: str = "docker.io/ai/gemma4:latest"
DMR_LLM_FALLBACK: str = "docker.io/ai/smollm2-vllm:1.7B"  # solo para pruebas

# Reranker para filtrado post-FAISS (Phase 2b)
DMR_RERANKER_MODEL: str = "docker.io/ai/qwen3-reranker-vllm:0.6B"

# ── Parámetros de búsqueda ─────────────────────────────────────────────────
FAISS_TOP_K: int = 5          # candidatos iniciales del índice FAISS
RERANKER_TOP_N: int = 3       # candidatos tras reranking
MIN_SEMANTIC_SCORE: float = 0.30  # umbral mínimo de similitud coseno

# ── Parámetros Docling (parseo de manuales) ───────────────────────────────
DOCLING_MAX_TOKENS: int = 512  # max tokens por chunk HybridChunker

# ── Parámetros LLM ────────────────────────────────────────────────────────
LLM_TEMPERATURE: float = 0.0
# gemma4 genera reasoning interno antes de la respuesta → necesita tokens extra
LLM_MAX_TOKENS: int = 4096   # M1 16GB: limita cadena CoT de gemma4 (antes 8192)
LLM_GRADER_MAX_TOKENS: int = 2048  # grading simple: suficiente con 2k tokens

# ── Concurrencia ──────────────────────────────────────────────────────────
# M1 16GB: DMR procesa gemma4 secuencialmente; max_workers>1 no aporta speedup
# y añade presión de memoria con múltiples requests en cola simultáneos
MAX_WORKERS: int = 1          # hilos simultáneos para llamadas LLM
EMBED_BATCH_SIZE: int = 32    # textos por lote en encode()

# dependencies/

Entorno reproducible para el Comparador de Normativas en **Apple Silicon (M1/M2/M3/M4) con 16GB de RAM**.

## Instalación rápida

```bash
bash dependencies/setup_apple_silicon.sh
conda activate normas_comparador
jupyter lab master.ipynb
```

El script instala Homebrew + Miniconda (arm64) si faltan, crea el entorno desde
`environment.yml`, registra el kernel de Jupyter, verifica Docker Desktop +
Docker Model Runner (DMR), y descarga los 3 modelos usados por el pipeline
(`granite-embedding-multilingual`, `gemma4`, `qwen3-reranker-vllm`).

Archivos:
- `environment.yml` — spec conda (fuente de verdad para replicar el entorno)
- `requirements.txt` — misma lista en formato pip plano (por si no usas conda)
- `setup_apple_silicon.sh` — instalador automatizado end-to-end

## Por qué la Fase 2.2 (índice FAISS) crasheaba el kernel

En una Mac de 16GB, `faiss` y el runtime OpenMP que trae `torch`/Docling pueden
coexistir en el mismo proceso del kernel de Jupyter y producir un **segfault
nativo** (el kernel muere sin traceback, justo después de "Successfully loaded
faiss" en los logs). `src/search_engine.py` ya mitiga esto con imports
diferidos de `faiss` dentro de `build/save/load` en vez de al nivel de módulo,
y `master.ipynb` fija `KMP_DUPLICATE_LIB_OK=TRUE` como resguardo adicional.

Si el crash vuelve a aparecer en esta Mac, revisa en orden:

1. **Python nativo arm64, no Rosetta:**
   ```bash
   python -c "import platform; print(platform.machine())"   # debe imprimir "arm64"
   ```
2. **Memoria de Docker Desktop:** Settings → Resources → Memory. Con DMR
   cargando `granite-embedding` + `gemma4` + `qwen3-reranker` simultáneos
   (~6.5GB), deja a Docker un límite de 6-8GB como máximo para no competir con
   el resto del sistema.
3. **Reinicia el kernel entre Fase 1 y Fase 2.** Docling deja modelos de
   layout/TableFormer residentes en memoria; un kernel restart libera esa
   huella antes de construir el índice FAISS.
4. **Usa el embedding `granite-embedding-multilingual` (768d)**, no
   `qwen3-embedding` (2560d) — ya es el default en `master.ipynb`, pero
   confírmalo si editaste la celda 2.1.

## Presupuesto de memoria (16GB)

| Componente | RAM aprox. |
| --- | --- |
| granite-embedding-multilingual | ~530 MB |
| gemma4 | ~4.74 GB |
| qwen3-reranker-vllm | ~1.19 GB |
| **Total DMR** | **~6.5 GB** |
| OS + Jupyter + Docling (Fase 1) | ~4.5 GB |
| Margen libre | ~5 GB de 16 GB |

`src/config.py` ya refleja este presupuesto: `MAX_WORKERS=1`,
`LLM_MAX_TOKENS=4096`, `LLM_GRADER_MAX_TOKENS=2048`.

## Rama Linux (`comparador-v3-linux`)

Todo lo anterior es de `feature/comparador-v2` (macOS + DMR) y sigue intacto ahí. Esta
rama corre en Linux x86_64 sin Docker Model Runner: los tres roles de modelo van a
backends que sí existen en esta máquina, ver el docstring de `src/config.py` para el
razonamiento completo. Resumen:

| Rol        | Backend                          | Modelo                              |
| ---------- | --------------------------------- | ------------------------------------ |
| LLM        | Vertex AI (`Provider.VERTEX`)     | `gemini-3.5-flash-lite`             |
| Embeddings | Ollama, OpenAI-compat (`/v1`)     | `qwen3-embedding:0.6b` (1024d, GPU) |
| Reranker   | sentence-transformers (CPU)       | `Qwen/Qwen3-Reranker-0.6B`          |

### Instalación

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r dependencies/requirements-linux.txt
ollama pull qwen3-embedding:0.6b   # ~640MB descarga, ~2.4GB VRAM en GPU
```

`.env` (gitignored) necesita `GOOGLE_APPLICATION_CREDENTIALS` apuntando a la service
account de Vertex y `VERTEX_PROJECT_ID`. No hay `.env.example` de esta rama con estas
claves porque el valor de la primera es sensible por definición — pedir la ruta real al
equipo/usuario en vez de generarla.

### Gotchas verificados en vivo (2026-09-02)

- **`location="global"`, no una región concreta.** Los modelos Gemini de este proyecto
  devuelven `404 Publisher model ... was not found` contra `us-central1`; sí responden
  en `global`. Si se cambia de proyecto GCP, volver a probar esto primero — no asumir
  que se mantiene.
- **El `qwen3-embedding` "recomendado" del config original de macOS (2560 dim) no cabe
  en esta GPU.** El tag de Ollama que le corresponde es `qwen3-embedding:latest`/`:8b`
  (4.7GB) — probado primero y confirmado que revienta: `CUDA error: out of memory` a
  mitad de la inferencia (visto en el log de `ollama serve`, no solo al cargar). El
  tag `:0.6b` (639MB, 1024 dim) sí cabe entero y corre 100% GPU (~2.4GB VRAM) — mismo
  modelo, tamaño que sí corresponde al hardware.
- **GPU sin soporte CUDA en el wheel de PyTorch ≠ CPU automático, antes de este fix.**
  Con una GPU vieja (aquí: GTX 960M, Maxwell/sm_50), `torch.cuda.is_available()`
  devuelve `True` aunque el wheel de PyTorch no traiga kernels para esa compute
  capability — el fallo real solo aparecía a mitad de un forward pass
  (`CUDA error: no kernel image is available for execution on the device`).
  `providers.resolve_device()` ahora comprueba `torch.cuda.get_arch_list()` antes de
  devolver `"cuda"`, y cae a CPU si el wheel no cubre la GPU presente. Esto afecta al
  reranker y a `Provider.LOCAL_ST` (embeddings locales, no usado por defecto en esta
  rama) — **no** a Ollama, que trae su propio runtime con kernels para arquitecturas
  más antiguas y sí corre `bge-m3` en GPU sin problema.
- Ambos, `langchain-google-vertexai` y `langchain==0.3.27`/`langchain-openai==0.3.35`,
  exigen versiones distintas de `langchain-core` (`>=1.0` vs `<1.0`). Se fijó
  `langchain-google-vertexai==2.1.2` (última de la serie 2.x) para no romper esa
  restricción — no subir a la serie 3.x sin volver a resolver el conflicto.

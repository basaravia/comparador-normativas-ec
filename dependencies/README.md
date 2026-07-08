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

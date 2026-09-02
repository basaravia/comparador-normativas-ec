# Evaluación de modelos de embedding — sandbox

**No es parte del pipeline.** Vive en la rama `sandbox/embedding-eval`, pensada para
descartarse (ver "Qué hacer con esto" al final). El objetivo era responder con
evidencia, no con intuición: de los modelos de embedding disponibles para este
proyecto (locales vía Ollama, Vertex AI, u otros locales descargables), ¿cuál discierne
mejor la similitud semántica entre una sección de manual de control interno y el
artículo normativo que debería cubrirla?

## Por qué esto y no un benchmark genérico

Los benchmarks públicos de embeddings (MTEB y similares) miden calidad general, no lo
que este proyecto necesita: distinguir, dentro de un conjunto de artículos normativos
temáticamente parecidos, cuál es el que corresponde a una sección de manual redactada
con vocabulario propio de la entidad (no una cita literal de la norma). Es una prueba de
recuperación semántica adversarial a propósito, con FAISS igual que en producción
(`src/search_engine.py`: coseno vía índice `IndexFlatIP`/`MAX_INNER_PRODUCT` sobre
vectores L2-normalizados, no la distancia euclidiana por defecto de LangChain).

## Corpus

- **Normativa (texto real, 14 artículos):** Ley 10/2010 de prevención de blanqueo de
  capitales y Ley 10/2014 de ordenación, supervisión y solvencia de entidades de
  crédito (España, BOE). Descargadas en vivo, texto de dominio público. Dos dominios
  temáticos deliberadamente distintos (PBC/diligencia debida vs. solvencia/gobierno
  corporativo) para que el corpus tenga decoys reales, no solo ruido aleatorio.
- **Manual (sintético, 14 secciones):** redactadas para esta prueba — no existe un
  manual de control interno real y público para descargar (es información confidencial
  de cada entidad). Cada sección parafrasea deliberadamente el artículo que debería
  recuperar, con vocabulario distinto: es la situación real que el proyecto resuelve,
  no una prueba fácil de coincidencia léxica.
- Ver `corpus.py` para el texto completo y las fuentes citadas.

**Limitación reconocida:** el corpus normativo es de España (no Ecuador/SBS/BCE/SEPS,
el dominio real del proyecto) — fue lo que se pudo descargar con certificado TLS válido
en la sesión. El país es indistinto para lo que se midió (discriminación semántica en
español bancario/regulatorio), pero no valida terminología específica ecuatoriana.

## Resultados (2026-09-02)

| Modelo | dim | top-1 | top-3 | MRR | margen prom. | indexado | consultas | costo |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| `vertex/gemini-embedding-001` | 3072 | **14/14** | 14/14 | **1.000** | +0.063 | 1.5s | 5.4s | pago (API) |
| `ollama/qwen3-embedding:0.6b` | 1024 | 13/14 | 14/14 | 0.964 | **+0.154** | 8.3s | 3.8s | gratis (GPU local) |
| `local/multilingual-e5-large` | 1024 | 13/14 | 14/14 | 0.964 | +0.021 | 19.2s | 8.1s | gratis (CPU local) |
| `ollama/bge-m3` | 1024 | 12/14 | 14/14 | 0.917 | +0.080 | 6.0s | 4.7s | gratis (GPU local) |
| `vertex/text-multilingual-embedding-002` | 768 | 12/14 | 14/14 | 0.917 | +0.041 | 1.3s | 5.9s | pago (API) |

Los 5 modelos acertaron top-3 en las 14 consultas — ninguno está "roto". Donde
difieren es en precisión fina (top-1/MRR) y en cuán clara es la separación (margen).

**Falla consistente en casi todos los modelos:** `Solvencia_art42` (Liquidez) vs.
`Solvencia_art44` (Colchón de conservación del capital) — ambos artículos cortos y
temáticamente cercanos (requisitos de capital/liquidez), y mi paráfrasis de manual para
art42 usó la palabra "colchón" (igual que el título real de art44), lo cual añadió
ambigüedad léxica genuina encima de la semántica. Es un caso límite realista — un
analista humano también dudaría entre esos dos — más que una debilidad clara de un
modelo sobre otro. `gemini-embedding-001` fue el único que lo resolvió sin error.

## Conclusión y recomendación

1. **`gemini-embedding-001` (Vertex) es el más preciso** (perfecto en esta prueba),
   pero tiene el mayor costo por llamada, el mayor tamaño de índice (3072d vs 768-1024d
   de los demás) y depende de red/cuota.
2. **`qwen3-embedding:0.6b` (Ollama, ya el default de `src/config.py`) queda
   validado con evidencia**, no solo por ser el "recomendado" del config original de
   macOS: 13/14 top-1, MRR 0.964, y el **mayor margen de separación de los modelos
   gratuitos** — sugiere que cuando acierta, acierta con confianza, no por poco. Gratis,
   local, rápido de indexar en GPU.
3. **`bge-m3` y `text-multilingual-embedding-002` rinden algo por debajo** de
   `qwen3-embedding:0.6b` en esta prueba — no serían la primera opción con esta
   evidencia, aunque la diferencia es de 1-2 aciertos sobre 14 consultas, no
   concluyente por sí sola con un corpus de este tamaño.

**Recomendación:** mantener `qwen3-embedding:0.6b` vía Ollama como default (ya lo es).
Si en producción con el corpus normativo real (SBS/BCE/SEPS/UAF, volumen mayor) la
tasa de error resulta costosa para el caso de uso — recordar que el proyecto ya
compensa esto con un reranker (`src/providers.py`, `Qwen/Qwen3-Reranker-0.6B`) y un
umbral de similitud mínimo (`MIN_SEMANTIC_SCORE`) antes de que el LLM analice cada
candidato — considerar `gemini-embedding-001` como *fallback* configurable vía
`Provider.VERTEX` (ya implementado, ver `src/providers.py`) para los casos que el
reranker marque como ambiguos, no como reemplazo general del default gratuito.

## Cómo reproducir

```bash
source .venv/bin/activate
pip install -r sandbox/embedding_eval/requirements.txt
python sandbox/embedding_eval/run_eval.py
```

Requiere: Ollama corriendo con `qwen3-embedding:0.6b` y `bge-m3` descargados, y
`GOOGLE_APPLICATION_CREDENTIALS`/`VERTEX_PROJECT_ID` en `.env` para los dos modelos de
Vertex (ver `dependencies/README.md`, sección "Rama Linux").

## Qué hacer con esto

Es un experimento desechable por diseño (rama `sandbox/`). La conclusión de esta
sección ya está en este README; el código y el corpus no necesitan vivir en la rama
principal del proyecto. Opciones, de más a menos conservadora:

- Copiar solo la sección "Conclusión y recomendación" a `dependencies/README.md` o
  `PLAN_MEJORAS_ANEXO.md` en `comparador-v3-linux`, y borrar esta rama.
- Dejar esta rama como referencia (sin mergear) y no borrarla todavía.
- Borrar la rama sin más — la conclusión queda solo en el historial de esta conversación.

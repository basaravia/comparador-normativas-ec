# Deploy en Databricks Apps

El deploy se hace a mano, en la instancia de Databricks que corresponda (no necesariamente la
del CLI logueado en esta máquina). Hay dos formas; la recomendada es la rama `deploy/databricks`.

## Recomendado: desde Git, con la rama `deploy/databricks`

Esa rama contiene **solo la app** (sin notebooks, tests, PDFs ni `output/`) y se genera desde la
rama de trabajo:

```bash
bash scripts/rama_deploy.sh          # compila el front, arma dist-app/ y actualiza la rama LOCAL
# revisar con el guardián y publicar:
git push origin deploy/databricks
```

En Databricks: *Create app* → fuente **Git** → repo `comparador-normativas-ec`, rama
`deploy/databricks`. Cada vez que cambies la app, regenera la rama, haz push y pulsa *Deploy*.

### Por qué esa forma (lo que hizo caer el primer intento)

Databricks instala **`requirements.txt` desde la raíz** de lo que despliega y sirve el front ya
compilado. Desplegando la rama de trabajo, la raíz no tenía `requirements.txt` (vive en
`backend/`) ni el front compilado: «Packages installed» no instalaba nada útil y la app caía
al arrancar por módulos que no existían. La rama `deploy/databricks` lo trae todo en su raíz.

## Antes de desplegar

- **`app.yaml`**: sustituir los `REEMPLAZAR-*` de Foundry (`FOUNDRY_AI_ENDPOINT`,
  `FOUNDRY_AI_API_VERSION`, `FOUNDRY_AI_DEPLOYMENT`, `FOUNDRY_AI_EMBED_DEPLOYMENT`). La clave va
  como secreto: crear `foundry_ai_token` y asociarlo en *App resources* con ese mismo nombre. Es el
  **único** secreto que pide el `app.yaml`; Vertex, Groq, OpenRouter y el login están comentados
  porque cada `valueFrom` exige que su secreto exista.
- **`MODEL_PROFILE`** (en `app.yaml`) elige el backend: `foundry` ahí. Los perfiles están en
  `backend/config/perfiles.yaml`.
- **`AUTH_ENABLED`** está en `"false"` porque la interfaz mínima no tiene login. Databricks Apps
  ya pone su acceso por workspace delante, pero confírmalo antes de exponerla. Cuando vuelva el
  login: `"true"` + secreto `AUTH_SECRET_KEY`.
- Los documentos (normativas y manuales) hay que subirlos aparte; no viajan en la rama.

## Qué incluye y qué no el `requirements.txt` de la raíz

Es lo **mínimo para arrancar** la API y usar el LLM y los embeddings de Foundry (la misma lista
que la suite rápida del CI). **No incluye `docling`, `torch` ni `sentence-transformers`** (varios
GB): la app arranca y responde, pero **tabular PDFs (Paso 1) y el reranker local fallan al
usarse**. Para el pipeline completo hay que instalar `backend/requirements.txt` (copiarlo sobre el
de la raíz en la rama de deploy). Ojo con el tamaño y el tiempo de instalación, y con los límites
del plan de Databricks (la *Free Edition* tiene poca memoria).

## Si la app sigue cayendo: dónde mirar

Pestaña **Logs** de la app: ahí está el traceback del arranque. Las causas típicas son un módulo
que falta (`ModuleNotFoundError`), un puerto distinto de 8000, o un `valueFrom` cuyo secreto no
está asociado en *App resources*. Además, la *Free Edition* puede restringir la salida a internet:
si bloquea `*.openai.azure.com`, la app arranca pero Foundry no responde (a verificar en tu
instancia).

## Alternativa: subir la carpeta a mano

`bash scripts/empaquetar_databricks.sh` deja lo mismo en `dist-app/` (ignorado por git) para
sincronizarlo al workspace sin pasar por Git. No incluye `.env`, `Normativa2026/`, los manuales
reales de `document_test/` (solo los mock están en git) ni `assets/brand/brand.json`.

## Deuda conocida

`backend/app/logging_utils.py` hace `import streamlit` a nivel de módulo y `api/main.py` lo
importa; por eso `streamlit` sigue en los `requirements`. Desacoplarlo permitiría quitarlo.

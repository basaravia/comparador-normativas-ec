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

### Lo que exige Databricks Apps (documentación oficial) y cómo lo cumple la rama

| Requisito | Cómo se cumple |
|---|---|
| Instala `requirements.txt` con pip **desde la raíz**, Python 3.11 | `requirements.txt` en la raíz, versiones fijadas desde un entorno 3.11 donde el E2E pasó |
| El puerto lo asigna la plataforma y el `command` **no pasa por shell** (nada se sustituye en él) | `app.yaml` no pasa `--host`/`--port`: uvicorn lee `UVICORN_HOST`/`UVICORN_PORT`, que Databricks define. Un `--port DATABRICKS_APP_PORT` llegó literal y tumbó la app |
| Por defecto 2 vCPU y **6 GB** de memoria | Pico medido en el E2E: **4,2 GB** (Docling + reranker + FAISS). Cabe, con poco margen |
| El front no se compila en la app si no hay `package.json` | `frontend/dist` ya compilado en la rama |
| Solo existe lo que está en la rama | Van los PDF **versionados** (normativas públicas + manuales MOCK) y la caché de Docling: sin ellos la app lista 0 documentos y la UI mínima no puede subirlos |

### Prueba end-to-end hecha antes de publicar

Sobre el mismo contenido de la rama, en un entorno limpio de Python 3.11 con `pip install -r
requirements.txt`, arrancando con el `command` de `app.yaml` tal cual (sin sustituir nada) y las
variables que Databricks define (`UVICORN_HOST`, `UVICORN_PORT`, `DATABRICKS_APP_PORT`…):
SPA → listar documentos → tabular (Docling) → índice FAISS → búsqueda + reranker → comparación
doble vía → Excel del papel de trabajo. Todo OK. El LLM fue Groq (perfil `local_groq`); Foundry
no se pudo probar sin credenciales. Detalle: la corrida de muestra (2 secciones de MOCK-DEMO-01
contra el cap. V) dio cobertura 0 %: el flujo funciona, el resultado de negocio no se evaluó.

### Red: el punto que más probablemente rompe la instalación en la Free Edition

La Free Edition limita la salida a internet a una lista de dominios que no está publicada. La app
necesita salir a:

- `pypi.org` / `files.pythonhosted.org` — instalar dependencias (según la comunidad, permitido).
- `download.pytorch.org` — torch CPU (`--extra-index-url` en `requirements.txt`). **Sin confirmar.**
- `huggingface.co` — Docling y el reranker descargan sus modelos **al primer uso** (~1,5 GB).
  **Sin confirmar.**
- `<recurso>.openai.azure.com` — Foundry. **Sin confirmar.**

Si la instalación o el primer uso fallan por red (`Temporary failure in name resolution`,
`Connection refused`, timeouts), la Free Edition desbloquea la salida a internet al **verificar
la identidad** (botón *Verify identity* del encabezado del workspace). En un workspace de pago se
configura en *networking* / *egress*.

Si `download.pytorch.org` estuviera bloqueado, quitar la línea `--extra-index-url` y el sufijo
`+cpu` de `torch`/`torchvision`: pip bajará el torch de PyPI, que funciona pero arrastra ~3 GB de
CUDA (instalación mucho más lenta y pesada).

### Regenerar las versiones fijadas

```bash
conda create -n dbx311 python=3.11 -y && conda activate dbx311
pip install --extra-index-url https://download.pytorch.org/whl/cpu -r backend/requirements.txt
# y copiar el `pip freeze` bajo la cabecera de requirements.txt (ver cómo está hecho hoy)
```

## Antes de desplegar

- **Configuración, como recomienda Databricks:** todo en `app.yaml`. Los parámetros no
  sensibles como `value` y los secretos como **recurso de la app + `valueFrom`**; nunca el valor
  en el archivo. El `.env` es solo para desarrollo local. Pasos:
  1. Crear dos secretos en un scope: `foundry_ai_token` (la clave) y `foundry_ai_endpoint`
     (la URL; va como secreto porque nombra tu recurso de Azure y el repo es público).
  2. En la app: *App resources* → *Add resource* → **Secret** para cada uno, con esos mismos
     *resource names*, permiso de lectura.
  3. En `app.yaml`, sustituir los `REEMPLAZAR-*` de `FOUNDRY_AI_API_VERSION`,
     `FOUNDRY_AI_DEPLOYMENT` y `FOUNDRY_AI_EMBED_DEPLOYMENT`.

  Leer secretos con `dbutils`/`databricks-sdk` (`DATABRICKS_SECRET_SCOPE_<NOMBRE>` /
  `DATABRICKS_SECRET_KEY_<NOMBRE>`) sigue soportado para notebooks, jobs u otros entornos, pero en
  una App Databricks documenta solo `valueFrom`.
- **`MODEL_PROFILE`** (en `app.yaml`) elige el backend: `foundry` ahí. Los perfiles están en
  `backend/config/perfiles.yaml`.
- **`AUTH_ENABLED`** está en `"false"` porque la interfaz mínima no tiene login. Databricks Apps
  ya pone su acceso por workspace delante, pero confírmalo antes de exponerla. Cuando vuelva el
  login: `"true"` + secreto `AUTH_SECRET_KEY`.
- Documentos: la rama trae los PDF de prueba versionados. Los manuales reales NO: se suben
  aparte (la API tiene `POST /api/documents/upload`; la UI mínima aún no).

## Si la app sigue cayendo: dónde mirar

Pestaña **Logs** de la app: ahí está el traceback del arranque. Las causas típicas son la red (sección anterior), un
`valueFrom` cuyo secreto no está asociado en *App resources*, o memoria insuficiente
(`Killed` / OOM) si el cómputo de la app es menor que los 6 GB por defecto.

## Alternativa: subir la carpeta a mano

`bash scripts/empaquetar_databricks.sh` deja lo mismo en `dist-app/` (ignorado por git) para
sincronizarlo al workspace sin pasar por Git. Incluye solo los PDF versionados; nunca `.env`, los
manuales reales de `document_test/` ni `assets/brand/brand.json`.

## Deuda conocida

`backend/app/logging_utils.py` hace `import streamlit` a nivel de módulo y `api/main.py` lo
importa; por eso `streamlit` sigue en los `requirements`. Desacoplarlo permitiría quitarlo.

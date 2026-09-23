# Deploy manual en Databricks Apps

El repo queda **listo pero sin desplegar**. El deploy se hace a mano, en la instancia de
Databricks que corresponda (no necesariamente la del CLI logueado en esta máquina).

## 1 · Empaquetar

```bash
bash scripts/empaquetar_databricks.sh     # compila el front y arma dist-app/ (ignorado por git)
```

`dist-app/` contiene `app.yaml`, `requirements.txt`, `backend/`, `frontend/dist/` y el placeholder
de marca. **No** incluye `.env`, `Normativa2026/`, los manuales reales de `document_test/` (solo los mock están en git) ni `assets/brand/brand.json`.

## 2 · Antes de subir

- `app.yaml`: sustituir los `REEMPLAZAR-*` de Azure AI Foundry (`FOUNDRY_AI_ENDPOINT`,
  `FOUNDRY_AI_API_VERSION`, `FOUNDRY_AI_DEPLOYMENT`, `FOUNDRY_AI_EMBED_DEPLOYMENT`). La clave
  va como secreto: crear `foundry_ai_token` y asociarlo en *App resources* con ese mismo nombre.
  Es el **único** secreto que pide el `app.yaml` tal como está; Vertex, Groq, OpenRouter y el
  login están comentados porque cada `valueFrom` exige que su secreto exista.
- **`MODEL_PROFILE`** (en `app.yaml`) elige el backend: `foundry` por defecto ahí. Los perfiles están
  en `backend/config/perfiles.yaml`, que viaja dentro de `backend/`.
- **`AUTH_ENABLED`** está en `"false"` porque la interfaz mínima no tiene login. Databricks Apps
  ya pone su propio acceso por workspace delante, pero confírmalo antes de exponerla. Cuando
  vuelva el login: `"true"` + secreto `AUTH_SECRET_KEY`.
- Los documentos (normativas y manuales) hay que subirlos aparte; no viajan en git.

## 3 · Subir

Sincronizar `dist-app/` al workspace de la instancia elegida y crear/actualizar la app
apuntando a esa carpeta. El comando de arranque ya está en `app.yaml`:
`uvicorn api.main:app --app-dir backend --host 0.0.0.0 --port 8000`.

## Deuda conocida

`backend/app/logging_utils.py` hace `import streamlit` a nivel de módulo y `api/main.py` lo importa,
por eso `streamlit` sigue en `backend/requirements.txt` aunque la UI ya no se use. Desacoplarlo
permitiría quitar Streamlit del despliegue.

#!/usr/bin/env bash
# Arma dist-app/ con lo que se sube a Databricks Apps. NO despliega nada ni usa el CLI:
# el deploy es manual, en la instancia que corresponda (ver docs/DEPLOY-DATABRICKS.md).
set -euo pipefail
cd "$(dirname "$0")/.."

echo "▶ Compilando el frontend…"
(cd frontend && npm ci --no-audit --no-fund && npm run build)

OUT=dist-app
rm -rf "$OUT" && mkdir -p "$OUT/frontend" "$OUT/assets/brand"

# Databricks Apps instala `requirements.txt` desde la raíz de la app.
cp app.yaml "$OUT/app.yaml"
cp backend/requirements.txt "$OUT/requirements.txt"

# El backend conserva su árbol: las rutas del código cuentan con backend/ bajo la raíz.
rsync -a --exclude '__pycache__' --exclude 'tests' --exclude '*.egg-info' backend/ "$OUT/backend/"
cp -r frontend/dist "$OUT/frontend/dist"
# Solo el placeholder de marca; la identidad real (assets/brand/brand.json) no viaja en git.
cp -r assets/brand/_placeholder "$OUT/assets/brand/_placeholder"

echo "✔ $OUT listo ($(du -sh "$OUT" | cut -f1)). Contenido:"
(cd "$OUT" && find . -maxdepth 2 -not -path './backend/*/*' | sort | head -30)
echo
echo "Ojo: no incluye el archivo de entorno ni las normativas/manuales reales (los PDF mock de document_test/ sí están en git; el resto no). Ver docs/DEPLOY-DATABRICKS.md"

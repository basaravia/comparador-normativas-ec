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
# Plantilla de variables (sin valores): referencia para quien configure la app o un .env.
cp .env.example "$OUT/.env.example"
# requirements.txt de la RAÍZ (mínimo para arrancar). El completo con docling/torch es backend/requirements.txt.
cp requirements.txt "$OUT/requirements.txt"

# El backend conserva su árbol: las rutas del código cuentan con backend/ bajo la raíz.
rsync -a --exclude '__pycache__' --exclude 'tests' --exclude '*.egg-info' backend/ "$OUT/backend/"
cp -r frontend/dist "$OUT/frontend/dist"
# Solo el placeholder de marca; la identidad real (assets/brand/brand.json) no viaja en git.
cp -r assets/brand/_placeholder "$OUT/assets/brand/_placeholder"

# Documentos de prueba: SOLO los versionados en git y de ≤ 1 MB (normativas cortas y manuales MOCK).
# Databricks Apps rechaza apps de más de 10 MB: los PDF grandes y cualquier documento real van en
# un volumen de Unity Catalog, no en la app (ver docs/DEPLOY-DATABRICKS.md). `git ls-files` evita
# copiar manuales reales que existan en disco sin versionar.
MAX_BYTES=$((1024 * 1024))
git ls-files -z Normativa2026 'document_test/*.pdf' | while IFS= read -r -d '' f; do
  if [ "$(stat -c %s "$f")" -le "$MAX_BYTES" ]; then install -D -m 0644 "$f" "$OUT/$f"; fi
done

echo "✔ $OUT listo ($(du -sh "$OUT" | cut -f1)). Contenido:"
(cd "$OUT" && find . -maxdepth 2 -not -path './backend/*/*' | sort | head -30)
echo
echo "Incluye solo los PDF versionados (normativas públicas y manuales MOCK); nunca el archivo de entorno ni manuales reales. Ver docs/DEPLOY-DATABRICKS.md"

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

# Documentos de prueba: SOLO los versionados en git (normativas públicas, manuales MOCK y la caché
# de Docling de las normativas). `git ls-files` evita copiar manuales reales que existan en disco
# sin versionar. Sin ellos la app desplegada lista 0 documentos y la UI mínima no puede subirlos.
git ls-files -z Normativa2026 'document_test/*.pdf' output/docling/'*.md' \
  | xargs -0 -I{} install -D -m 0644 {} "$OUT/{}"

echo "✔ $OUT listo ($(du -sh "$OUT" | cut -f1)). Contenido:"
(cd "$OUT" && find . -maxdepth 2 -not -path './backend/*/*' | sort | head -30)
echo
echo "Incluye solo los PDF versionados (normativas públicas y manuales MOCK); nunca el archivo de entorno ni manuales reales. Ver docs/DEPLOY-DATABRICKS.md"

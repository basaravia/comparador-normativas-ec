#!/usr/bin/env bash
# Crea o actualiza la rama LOCAL `deploy/databricks` solo con la app (el contenido de dist-app/).
# Databricks Apps la despliega desde Git: así no baja notebooks, tests, PDFs ni output/.
#
# No hace push ni cambia de rama ni toca el árbol de trabajo (usa un índice temporal).
# Para publicarla: revisar con el guardián y `git push origin deploy/databricks`.
set -euo pipefail
cd "$(dirname "$0")/.."

# Rama destino: argumento opcional. Cada rama de trabajo tiene la suya, para no pisar otra.
RAMA="${1:-deploy/databricks-volumen}"
bash scripts/empaquetar_databricks.sh >/dev/null
ORIGEN=$(git rev-parse --short HEAD)

IDX=$(mktemp -u)
trap 'rm -f "$IDX"' EXIT
(cd dist-app && GIT_INDEX_FILE="$IDX" git --git-dir=../.git --work-tree=. add -A -f .)
TREE=$(GIT_INDEX_FILE="$IDX" git write-tree)

PADRE=()
if git rev-parse -q --verify "refs/heads/$RAMA" >/dev/null; then
  if [ "$(git rev-parse "$RAMA^{tree}")" = "$TREE" ]; then
    echo "✔ $RAMA ya está al día (sin cambios respecto de la app actual)."; exit 0
  fi
  PADRE=(-p "$RAMA")
fi

COMMIT=$(git commit-tree "$TREE" "${PADRE[@]}" -F - <<MSG
deploy: app lista para Databricks Apps (desde $ORIGEN)

Solo la app: app.yaml, requirements.txt (mínimo para arrancar), backend/, frontend/dist y el
placeholder de marca. Generada con scripts/rama_deploy.sh; no editar a mano.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012YEpRMsav8GqXRmuqUYsvH
MSG
)
git update-ref "refs/heads/$RAMA" "$COMMIT"
echo "✔ $RAMA → $(git rev-parse --short "$COMMIT") ($(git ls-tree -r --name-only "$COMMIT" | wc -l) archivos). Sin push."

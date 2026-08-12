#!/usr/bin/env bash
# Instala las guardas locales de confidencialidad de este repositorio PÚBLICO.
#
# Se instalan en .git/ y en la config local de git — nada de esto se versiona ni se
# comparte al clonar. Reejecutable sin efectos secundarios.
#
#   bash scripts/guardas/instalar_guardas.sh
#   bash scripts/guardas/instalar_guardas.sh --desinstalar
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
HOOKS="$(git rev-parse --git-path hooks)"
# Raiz del repositorio PRINCIPAL: en un worktree, --git-common-dir apunta al
# .git de arriba. Los hooks se comparten entre worktrees, asi que deben
# invocar siempre las guardas del principal y no una copia congelada.
PRINCIPAL="$(cd "$(dirname "$(git rev-parse --git-common-dir)")" && pwd)"
PY="${GUARDAS_PYTHON:-python3}"

if [[ "${1:-}" == "--desinstalar" ]]; then
  rm -f "$HOOKS/pre-commit" "$HOOKS/commit-msg" "$HOOKS/pre-push"
  git config --unset filter.nbstrip.clean  2>/dev/null || true
  git config --unset filter.nbstrip.smudge 2>/dev/null || true
  git config --unset filter.nbstrip.required 2>/dev/null || true
  echo "Guardas desinstaladas. El repositorio queda sin compuerta local."
  exit 0
fi

command -v "$PY" >/dev/null || { echo "ERROR: '$PY' no está en PATH."; exit 1; }

# La denylist NO se versiona (contiene el nombre del cliente). Sin ella el escáner
# aborta con código 2, así que se avisa aquí en vez de dejar que falle en el primer commit.
if [[ ! -f "${PRINCIPAL}/.claude/denylist.json" ]]; then
  echo "FALTA .claude/denylist.json — las guardas no pueden validar nada."
  echo "  mkdir -p .claude && cp scripts/guardas/denylist.example.json .claude/denylist.json"
  echo "  (y rellenar los patrones de identidad y marca)"
  exit 1
fi
chmod +x scripts/guardas/*.py

# ── 1 · Filtro que quita salidas de notebook al entrar al índice ──────────────
git config filter.nbstrip.clean  "$PY scripts/guardas/strip_outputs.py"
git config filter.nbstrip.smudge cat
git config filter.nbstrip.required true
if ! grep -qs 'filter=nbstrip' .gitattributes 2>/dev/null; then
  echo '*.ipynb filter=nbstrip' >> .gitattributes
  echo "  + .gitattributes: *.ipynb filter=nbstrip"
fi

# ── 2 · pre-commit: escanea lo que está a punto de commitearse ────────────────
# Resolutor de la ruta del escáner, compartido por los tres hooks.
#
# Los hooks viven en .git/ y se comparten entre TODAS las ramas y worktrees, pero el
# escáner es un archivo del árbol: en una rama donde scripts/guardas/ aún no existe
# —main, por ejemplo— la ruta fija falla y bloquea el push. Se prueban las dos
# ubicaciones y solo se aborta si no hay ninguna, que es cuando de verdad no se puede
# validar nada.
read -r -d '' RESOLVER <<'RES' || true
_scan() {
  local raiz="$1"
  for cand in "$raiz/scripts/guardas/scan_confidencial.py" "$raiz/.claude/scripts/scan_confidencial.py"; do
    [[ -f "$cand" ]] && { echo "$cand"; return 0; }
  done
  echo "ERROR: no se encuentra scan_confidencial.py; las guardas no pueden validar nada." >&2
  return 1
}
RES

cat > "$HOOKS/pre-commit" <<HOOK
#!/usr/bin/env bash
${RESOLVER}
S="\$(_scan "${PRINCIPAL}")" || exit 1
exec ${PY} "\$S" --staged
HOOK

# ── 3 · commit-msg: el vector que ya falló una vez (c48b85f) ─────────────────
# El mensaje de commit es público en cuanto hay push, y ningún escáner de
# archivos lo mira: `git log -S` busca en contenidos, no en mensajes.
cat > "$HOOKS/commit-msg" <<HOOK
#!/usr/bin/env bash
${RESOLVER}
S="\$(_scan "${PRINCIPAL}")" || exit 1
exec ${PY} "\$S" "\$1"
HOOK

# ── 4 · pre-push: última compuerta antes de lo público ───────────────────────
cat > "$HOOKS/pre-push" <<HOOK
#!/usr/bin/env bash
${RESOLVER}
S="\$(_scan "${PRINCIPAL}")" || exit 1
exec ${PY} "\$S" --push
HOOK

chmod +x "$HOOKS/pre-commit" "$HOOKS/commit-msg" "$HOOKS/pre-push"

echo "Guardas instaladas:"
echo "  · filtro nbstrip      salidas de notebook fuera del índice (copia local intacta)"
echo "  · hook pre-commit     escanea archivos staged, todo tipo incluido binario"
echo "  · hook commit-msg     escanea el mensaje del commit"
echo "  · hook pre-push       escanea el rango que se va a subir"
echo
echo "Saltarlas puntualmente: git commit --no-verify   (bajo tu responsabilidad)"
echo "Desinstalar:            bash scripts/guardas/instalar_guardas.sh --desinstalar"

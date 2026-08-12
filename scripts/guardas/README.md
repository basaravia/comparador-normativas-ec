# Guardas locales de confidencialidad

Este repositorio es **público**. Estas guardas son la única compuerta que impide que
material del cliente llegue a él: no hay red de seguridad detrás, porque se decidió no
reescribir la historia ya publicada y defender solo hacia adelante.

## Instalación en un clon nuevo

```bash
# 1 · la denylist NO viaja en git: contiene el nombre del cliente y su huella de marca
mkdir -p .claude
cp scripts/guardas/denylist.example.json .claude/denylist.json
#    …y rellenar los patrones de identidad y de marca

# 2 · instalar hooks y el filtro de notebooks
bash scripts/guardas/instalar_guardas.sh
```

Sin el paso 1, el instalador se niega a continuar y el escáner aborta con código 2.
Es deliberado: **un escáner que no puede validar nada no debe dejar pasar nada.**

## Qué queda instalado

| Pieza | Qué corta |
|---|---|
| filtro `nbstrip` | Salidas de notebook al entrar al índice. La copia local conserva las suyas |
| hook `pre-commit` | Escanea lo staged: texto, notebooks (fuente **y** salidas), xlsx/docx, PDF |
| hook `commit-msg` | El mensaje del commit — vector que ya filtró una vez en este repo |
| hook `pre-push` | Última compuerta antes de lo público |

## Herramientas bajo demanda

```bash
python3 scripts/guardas/capacidades.py            # qué extractores y OCR hay en esta máquina
python3 scripts/guardas/scan_confidencial.py --all
python3 scripts/guardas/inspeccionar_pdf.py doc.pdf --ocr    # PDFs escaneados
python3 scripts/guardas/detectar_entidades.py --all          # filiales no catalogadas
```

## Por qué los scripts se versionan y la denylist no

Los scripts son genéricos: sirven para cualquier proyecto con un cliente que proteger.
La denylist es lo único específico, y es justo lo que no puede hacerse público — el nombre
de la entidad, sus filiales y los hex de su paleta, que juntos la identifican tanto como
su nombre.

Antes ambos vivían fuera de git y las guardas no llegaban a un clon nuevo: se commiteaba
sin compuerta alguna sin que nadie lo notara.

## Archivos sin inspeccionar

Los que no se pueden leer como texto (imágenes, binarios, >5 MB) se listan y el escáner
**pregunta** si continuar, con `NO` por defecto. En contextos sin terminal aborta; si ya
los revisaste, `GUARDAS_ASUMIR_REVISADO=1` es el acuse explícito.

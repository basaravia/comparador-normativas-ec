#!/usr/bin/env python3
"""Escáner de confidencialidad — compuerta local para un repositorio PÚBLICO.

Extrae texto de cualquier tipo de archivo (no solo notebooks) y lo contrasta contra
``.claude/denylist.json``. Pensado para correr en hooks de git, así que solo usa la
librería estándar; ``pypdf`` se importa de forma perezosa y solo si hay PDFs.

Uso:
    scan_confidencial.py --staged        # lo que está a punto de commitearse (pre-commit)
    scan_confidencial.py --push <remote> # lo que está a punto de subirse   (pre-push)
    scan_confidencial.py --all           # todo el árbol rastreado          (auditoría)
    scan_confidencial.py f1 f2 …         # archivos concretos

Salida: 0 = sin bloqueantes · 1 = bloqueantes · 2 = error de configuración.
Las advertencias NO cambian el código de salida: avisan, no bloquean.

FAIL-CLOSED: si falta la denylist o no se puede leer, sale con 2 y el hook debe abortar.
Un escáner que falla en silencio es peor que no tenerlo.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import zipfile
from fnmatch import fnmatch
from pathlib import Path

def _raiz_de_trabajo() -> Path:
    """Raíz del árbol que se está escaneando. En un worktree, la del worktree."""
    r = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                       capture_output=True, text=True)
    if r.returncode == 0 and r.stdout.strip():
        return Path(r.stdout.strip())
    return Path(__file__).resolve().parents[2]


# Dos raíces distintas, y confundirlas fue un problema real:
#
#   REPO      dónde viven los archivos que se escanean. En un worktree, el worktree.
#   GUARDAS   dónde vive la denylist. SIEMPRE el repositorio principal.
#
# Un worktree de agente no tiene `.claude/` —está sin rastrear— así que antes había que
# copiarlo a mano. La copia se quedaba congelada: al corregir la denylist a mitad de
# sesión, el worktree seguía escaneando con la versión vieja y llegaba a conclusiones
# distintas sobre los mismos archivos. Resolviendo la denylist contra el repositorio
# principal, cualquier worktree usa siempre la vigente y no hay nada que copiar.
REPO = _raiz_de_trabajo()
GUARDAS = Path(__file__).resolve().parents[2]
DENYLIST = GUARDAS / ".claude" / "denylist.json"

TEXTO = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".md", ".txt", ".yaml", ".yml", ".json",
    ".html", ".css", ".scss", ".sh", ".sql", ".toml", ".cfg", ".ini", ".env",
    ".example", ".gitignore", ".r", ".rmd",
}
ZIP_XML = {".xlsx", ".docx", ".pptx", ".odt", ".ods"}


# ── extracción de texto ───────────────────────────────────────────────────────

def _texto_plano(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="ignore")


def _texto_notebook(p: Path) -> str:
    """Fuente Y salidas. Las salidas son el vector de mayor volumen en este repo."""
    try:
        nb = json.loads(p.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return _texto_plano(p)
    partes = []
    for celda in nb.get("cells", []):
        partes.append("".join(celda.get("source", [])))
        for out in celda.get("outputs", []):
            partes.append(json.dumps(out, ensure_ascii=False))
    return "\n".join(partes)


def _texto_zip_xml(p: Path) -> str:
    """xlsx/docx/pptx son ZIP con XML dentro. Sin dependencias externas."""
    partes = []
    with zipfile.ZipFile(p) as z:
        for n in z.namelist():
            if n.endswith(".xml") or n.endswith(".rels"):
                partes.append(re.sub(r"<[^>]+>", " ", z.read(n).decode("utf-8", "ignore")))
    return re.sub(r"\s+", " ", " ".join(partes))


def _texto_pdf(p: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        raise RuntimeError("pypdf no disponible; PDF no escaneable")
    return "\n".join((pg.extract_text() or "") for pg in PdfReader(str(p)).pages)


def extraer(p: Path, limite_mb: float = 5.0) -> tuple[str | None, str | None]:
    """Devuelve (texto, motivo_no_escaneable)."""
    ext = p.suffix.lower()
    mb = p.stat().st_size / (1024 * 1024)
    if mb > limite_mb:
        # Un hook tiene que ser rápido; por encima del límite no se intenta.
        return None, f"demasiado grande ({mb:.1f} MB > {limite_mb} MB)"
    try:
        if ext == ".ipynb":
            return _texto_notebook(p), None
        if ext in ZIP_XML:
            return _texto_zip_xml(p), None
        if ext == ".pdf":
            return _texto_pdf(p), None
        if ext in TEXTO or not ext:
            return _texto_plano(p), None
        # Desconocida: intenta como texto; si es binario real, no insistas.
        datos = p.read_bytes()
        if b"\x00" in datos[:4096]:
            return None, f"binario ({ext or 'sin extensión'})"
        return datos.decode("utf-8", "ignore"), None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


# ── denylist ──────────────────────────────────────────────────────────────────

def cargar_denylist() -> dict:
    if not DENYLIST.exists():
        print(f"ERROR: falta {DENYLIST.relative_to(REPO)}.", file=sys.stderr)
        print("El escáner no puede validar nada. Se aborta (fail-closed).", file=sys.stderr)
        sys.exit(2)
    try:
        return json.loads(DENYLIST.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"ERROR: {DENYLIST.name} ilegible: {e}", file=sys.stderr)
        sys.exit(2)


def _grupos(seccion: dict):
    for nombre, cfg in seccion.items():
        if nombre.startswith("_") or not isinstance(cfg, dict):
            continue
        yield nombre, cfg


def _linea_de(texto: str, pos: int) -> int:
    return texto.count("\n", 0, pos) + 1


def revisar(ruta: str, texto: str, dl: dict) -> tuple[list, list]:
    bloq, adv = [], []
    ext = Path(ruta).suffix.lower()

    for grupo, cfg in _grupos(dl["bloquea"]):
        if any(ruta.startswith(x) for x in cfg.get("_excepcion_rutas", [])):
            continue
        for pat in cfg.get("patrones", []):
            for m in re.finditer(pat, texto, re.I):
                frag = texto[max(0, m.start() - 40):m.start() + 60].replace("\n", " ")
                bloq.append((ruta, _linea_de(texto, m.start()), grupo, frag.strip()))
                break  # una coincidencia por patrón basta para bloquear

    for grupo, cfg in _grupos(dl["advierte"]):
        # Algunas heurísticas solo tienen sentido en archivos que transportan datos:
        # un .py que define el esquema no contiene resultados del cliente.
        solo = cfg.get("_solo_extensiones")
        if solo and ext not in solo:
            continue
        # Algunas heurísticas dependen de las mayúsculas para tener precisión
        # (ver _nota_case en la denylist); ignorarlas las vuelve inservibles.
        flags = 0 if cfg.get("_case_sensitive") else re.I
        for pat in cfg.get("patrones", []):
            m = re.search(pat, texto, flags)
            if m:
                adv.append((ruta, _linea_de(texto, m.start()), grupo, m.group(0)[:60]))
    return bloq, adv


def revisar_rutas(rutas: list[str], dl: dict) -> list:
    """Archivos que no deberían estar en git por su UBICACIÓN, sin mirar su contenido."""
    hallazgos = []
    for grupo, cfg in _grupos(dl["advierte"]):
        for glob in cfg.get("rutas_prohibidas", []):
            for ruta in rutas:
                if fnmatch(ruta, glob):
                    hallazgos.append((ruta, 0, grupo, f"situado en {glob}"))
    return hallazgos


# ── selección de archivos ─────────────────────────────────────────────────────

def _git(*args) -> list[str]:
    r = subprocess.run(["git", *args], capture_output=True, text=True, cwd=REPO)
    return [linea for linea in r.stdout.splitlines() if linea.strip()]


def archivos(argv: list[str]) -> tuple[list[str], str, bool]:
    """Devuelve (rutas, descripción, aplicar_exclusiones).

    Las exclusiones son para barridos masivos. Si alguien —o un hook— señala un archivo
    concreto, se escanea sin excepciones: el hook `commit-msg` pasa `.git/COMMIT_EDITMSG`,
    que cae bajo el glob `.git/**` y quedaría fuera justo en el vector que ya filtró una
    vez (c48b85f). Un escáner que salta lo que le piden mirar no sirve de nada.
    """
    if "--staged" in argv:
        return _git("diff", "--cached", "--name-only", "--diff-filter=ACMR"), "staged", True
    if "--all" in argv:
        return _git("ls-files"), "árbol rastreado", True
    if "--push" in argv:
        base = _git("rev-parse", "--abbrev-ref", "@{u}") or ["origin/main"]
        rango = f"{base[0]}...HEAD"
        return _git("diff", "--name-only", "--diff-filter=ACMR", rango), f"por subir ({rango})", True
    return [a for a in argv if not a.startswith("-")], "archivos indicados", False


def ignorado(ruta: str, dl: dict) -> bool:
    globs = dl["rutas_ignoradas_por_el_escaner"]["globs"]
    excluido = any(fnmatch(ruta, g) for g in globs if not g.startswith("!"))
    reincluido = any(fnmatch(ruta, g[1:]) for g in globs if g.startswith("!"))
    return excluido and not reincluido


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    dl = cargar_denylist()
    rutas, modo, aplicar_exclusiones = archivos(sys.argv[1:])
    no_escan = set(dl["no_escaneables"]["extensiones"])

    bloq, adv, sin_escanear, n = [], [], [], 0
    adv += revisar_rutas(rutas, dl)

    for ruta in rutas:
        if aplicar_exclusiones and ignorado(ruta, dl):
            continue
        p = REPO / ruta
        if not p.is_file():
            continue
        if p.suffix.lower() in no_escan:
            sin_escanear.append((ruta, "tipo no inspeccionable como texto"))
            continue
        texto, motivo = extraer(p, dl["no_escaneables"].get("limite_tamano_mb", 5))
        if texto is None:
            sin_escanear.append((ruta, motivo))
            continue
        n += 1
        b, a = revisar(ruta, texto, dl)
        bloq += b
        adv += a

    # Varios patrones del mismo grupo pueden matchear el mismo sitio (un nombre y su
    # variante con espacio): un hallazgo por (archivo, línea, grupo).
    def _dedupe(xs):
        vistos, out = set(), []
        for h in xs:
            k = (h[0], h[1], h[2])
            if k not in vistos:
                vistos.add(k)
                out.append(h)
        return out

    bloq, adv = _dedupe(bloq), _dedupe(adv)

    print(f"\nESCÁNER DE CONFIDENCIALIDAD — alcance: {modo} · {n} archivo(s) inspeccionado(s)")

    if bloq:
        print(f"\n  BLOQUEANTES ({len(bloq)})")
        for ruta, ln, grupo, frag in bloq:
            print(f"    {ruta}:{ln}  [{grupo}]  …{frag}…")

    if adv:
        print(f"\n  ADVERTENCIAS ({len(adv)}) — revisar, no bloquean")
        for ruta, ln, grupo, frag in adv:
            print(f"    {ruta}:{ln or '?'}  [{grupo}]  {frag}")

    if sin_escanear:
        print(f"\n  NO ESCANEADOS ({len(sin_escanear)}) — revisar a mano, NO se dan por limpios")
        for ruta, motivo in sin_escanear:
            print(f"    {ruta}  ({motivo})")

    if bloq:
        print("\n  → Commit/push abortado. Corrige o usa --no-verify bajo tu responsabilidad.\n")
        return 1

    if sin_escanear:
        return _decidir(len(sin_escanear))

    print("\n  Sin bloqueantes." + ("  (hay advertencias)\n" if adv else "\n"))
    return 0


def _decidir(n: int) -> int:
    """Go/no-go explícito cuando hay archivos que no se pudieron inspeccionar.

    No son bloqueantes —pueden ser perfectamente inocuos— pero tampoco se pueden dar por
    limpios. La decisión es de la persona, así que se pregunta en vez de dejar pasar un
    aviso que se pierde en el scroll de un commit exitoso.
    """
    if "--asumir-revisado" in sys.argv:
        print(f"\n  → {n} archivo(s) sin inspeccionar, aceptados por --asumir-revisado.\n")
        return 0

    # Los hooks de git no reciben argumentos, así que sin esta vía la única forma de
    # responder a la pregunta desde un hook sería saltarse la compuerta entera con
    # --no-verify — que es peor: desactiva también los bloqueantes.
    #
    # No debilita nada: el default sigue siendo abortar, la variable hay que ponerla a
    # propósito en esa invocación concreta, y queda en el historial del shell. Es un
    # acuse de recibo explícito, no un interruptor permanente.
    if os.environ.get("GUARDAS_ASUMIR_REVISADO") == "1":
        print(f"\n  → {n} archivo(s) sin inspeccionar, aceptados vía "
              "GUARDAS_ASUMIR_REVISADO=1.\n")
        return 0

    # Los hooks de git no reciben la terminal por stdin; hay que abrirla.
    try:
        with open("/dev/tty") as tty:
            print(f"\n  {n} archivo(s) no se pudieron inspeccionar (ver lista arriba).")
            resp = input_desde(tty, "  ¿Continuar de todas formas? [s/N]: ")
    except (OSError, EOFError):
        print(
            f"\n  → {n} archivo(s) sin inspeccionar y no hay terminal para preguntar.\n"
            "    Se aborta por defecto. Reejecuta de forma interactiva, o añade\n"
            "    --asumir-revisado si ya los revisaste.\n"
        )
        return 1

    if resp.strip().lower() in ("s", "si", "sí", "y", "yes"):
        print("  → Continuando por decisión explícita.\n")
        return 0
    print("  → Abortado.\n")
    return 1


def input_desde(tty, prompt: str) -> str:
    sys.stdout.write(prompt)
    sys.stdout.flush()
    return tty.readline()


if __name__ == "__main__":
    sys.exit(main())

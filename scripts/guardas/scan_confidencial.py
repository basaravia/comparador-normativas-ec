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

import io
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
#
# Todo aquí opera sobre `bytes` ya resueltos por `_leer_bytes()`, nunca sobre un
# `Path` que se lee directo del disco. La razón es TOCTOU: para --staged y --push
# lo que importa es el contenido que *va a quedar commiteado/subido* — el blob del
# índice o del commit — no el archivo del working tree, que puede haberse editado
# después de `git add` sin volver a stagearlo. Escanear el working tree ahí daba un
# "limpio" que no correspondía a lo que realmente se iba a commitear/pushear.

def _texto_plano(datos: bytes) -> str:
    return datos.decode("utf-8", errors="ignore")


def _texto_notebook(datos: bytes) -> str:
    """Fuente Y salidas. Las salidas son el vector de mayor volumen en este repo."""
    try:
        nb = json.loads(datos.decode("utf-8", errors="ignore"))
    except Exception:
        return _texto_plano(datos)
    partes = []
    for celda in nb.get("cells", []):
        partes.append("".join(celda.get("source", [])))
        for out in celda.get("outputs", []):
            partes.append(json.dumps(out, ensure_ascii=False))
    return "\n".join(partes)


def _texto_zip_xml(datos: bytes) -> str:
    """xlsx/docx/pptx son ZIP con XML dentro. Sin dependencias externas."""
    partes = []
    with zipfile.ZipFile(io.BytesIO(datos)) as z:
        for n in z.namelist():
            if n.endswith(".xml") or n.endswith(".rels"):
                partes.append(re.sub(r"<[^>]+>", " ", z.read(n).decode("utf-8", "ignore")))
    return re.sub(r"\s+", " ", " ".join(partes))


def _texto_pdf(datos: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        raise RuntimeError("pypdf no disponible; PDF no escaneable")
    return "\n".join((pg.extract_text() or "") for pg in PdfReader(io.BytesIO(datos)).pages)


# Un PDF escaneado (imagen sin capa de texto) da "" tras la extracción — no es lo
# mismo que "se extrajo y no hay coincidencias": es que no se pudo mirar el contenido
# en absoluto. Antes eso se contaba como escaneado y limpio; el caso donde más
# importa revisar a mano (un documento en imagen) pasaba sin ninguna advertencia.
_PDF_TEXTO_MINIMO = 20


def _leer_bytes(ruta: str, modo: str) -> bytes:
    """Contenido real a escanear según el modo — ver el docstring de arriba.

    - "staged": el blob en el índice (`git show :ruta`), lo que quedaría commiteado.
    - "push": el blob en HEAD (`git show HEAD:ruta`), lo que ya está commiteado y a
      punto de subirse — no el working tree, que puede ir por delante de HEAD.
    - cualquier otro modo ("árbol rastreado", "archivos indicados"): filesystem,
      donde no hay una distinción índice/commit que proteger.
    """
    if modo == "staged":
        r = subprocess.run(["git", "show", f":{ruta}"], capture_output=True, cwd=REPO)
    elif modo == "push":
        r = subprocess.run(["git", "show", f"HEAD:{ruta}"], capture_output=True, cwd=REPO)
    else:
        return (REPO / ruta).read_bytes()
    if r.returncode != 0:
        raise RuntimeError(f"git show falló para {ruta!r}: {r.stderr.decode('utf-8', 'ignore').strip()}")
    return r.stdout


def extraer(ruta: str, modo: str, limite_mb: float = 5.0) -> tuple[str | None, str | None]:
    """Devuelve (texto, motivo_no_escaneable)."""
    ext = Path(ruta).suffix.lower()
    try:
        datos = _leer_bytes(ruta, modo)
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"
    mb = len(datos) / (1024 * 1024)
    if mb > limite_mb:
        # Un hook tiene que ser rápido; por encima del límite no se intenta.
        return None, f"demasiado grande ({mb:.1f} MB > {limite_mb} MB)"
    try:
        if ext == ".ipynb":
            return _texto_notebook(datos), None
        if ext in ZIP_XML:
            return _texto_zip_xml(datos), None
        if ext == ".pdf":
            texto = _texto_pdf(datos)
            if len(texto.strip()) < _PDF_TEXTO_MINIMO:
                return None, "PDF sin texto extraíble (posible escaneo/imagen) — requiere revisión manual"
            return texto, None
        if ext in TEXTO or not ext:
            return _texto_plano(datos), None
        # Desconocida: intenta como texto; si es binario real, no insistas.
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

        # Co-ocurrencia: dispara solo si aparecen señales de TODAS las familias.
        #
        # Sirve para detectar un artefacto por su forma en vez de por su ruta: un
        # resultado de corrida lleva a la vez veredicto, trazabilidad y análisis, y esa
        # combinación no ocurre por casualidad. Aquí sí bloquea —a diferencia de la
        # versión que se quitó de `advierte`— porque los términos son literales del
        # esquema con comillas de JSON, no vocabulario suelto que aparezca en el código.
        co = cfg.get("co_ocurrencia")
        if co:
            presentes = {
                familia: next((p for p in pats if re.search(p, texto, re.I)), None)
                for familia, pats in co.items()
            }
            if all(presentes.values()):
                detalle = " + ".join(f"{k}:{v}" for k, v in presentes.items())
                bloq.append((ruta, 0, grupo, detalle[:110]))

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

def _git(*args, ignorar_error: bool = False) -> list[str]:
    """Ejecuta git y devuelve sus líneas de salida.

    Fail-closed por defecto: antes, un comando de git que fallara (rango sin fetchear,
    upstream inexistente, lo que sea) devolvía `[]` en silencio — `main()` interpretaba
    eso como "0 archivos a revisar" y el push/commit pasaba sin haberse escaneado nada,
    justo lo contrario de lo que dice el docstring del módulo. `ignorar_error=True` es
    solo para la búsqueda de upstream de abajo, que YA tiene un fallback explícito
    (`or ["origin/main"]`) para el caso en que fallar es esperado.
    """
    r = subprocess.run(["git", *args], capture_output=True, text=True, cwd=REPO)
    if r.returncode != 0 and not ignorar_error:
        print(f"ERROR: 'git {' '.join(args)}' falló: {r.stderr.strip()}", file=sys.stderr)
        print("No se puede determinar qué escanear. Se aborta (fail-closed).", file=sys.stderr)
        sys.exit(2)
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
        base = _git("rev-parse", "--abbrev-ref", "@{u}", ignorar_error=True) or ["origin/main"]
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

    # "staged"/"push" leen el blob de git (índice/HEAD), no el filesystem — ver
    # _leer_bytes(). El chequeo de existencia en disco (p.is_file()) solo aplica a
    # los otros modos; para esos dos, un blob ausente lo reporta extraer() como
    # excepción y cae en sin_escanear, no se filtra aquí antes de mirarlo.
    modo_lectura = "staged" if "--staged" in sys.argv else ("push" if "--push" in sys.argv else "fs")

    for ruta in rutas:
        if aplicar_exclusiones and ignorado(ruta, dl):
            continue
        if modo_lectura == "fs" and not (REPO / ruta).is_file():
            continue
        if Path(ruta).suffix.lower() in no_escan:
            sin_escanear.append((ruta, "tipo no inspeccionable como texto"))
            continue
        texto, motivo = extraer(ruta, modo_lectura, dl["no_escaneables"].get("limite_tamano_mb", 5))
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

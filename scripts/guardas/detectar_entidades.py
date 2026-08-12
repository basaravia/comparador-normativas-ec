#!/usr/bin/env python3
"""Detección de entidades nombradas — encuentra lo que la denylist NO sabe todavía.

La denylist tiene precisión perfecta sobre lo que ya conocemos y **recall cero sobre lo que
no**. Si aparece una filial, una marca de producto o un proveedor del cliente que nadie
anotó, el escáner rápido no la ve. Este script existe para cerrar ese hueco: extrae
organizaciones del texto y las contrasta contra la denylist, de modo que lo *desconocido*
sea lo que llame la atención.

Dos niveles, elegidos según lo disponible (ver capacidades.py):

  heuristico    sin dependencias ni descargas, instantáneo. Busca secuencias capitalizadas
                junto a marcadores societarios (Banco, Grupo, S.A., Cía., Seguros…) y RUCs
                ecuatorianos. Recall alto, precisión media: pensado para que un humano
                revise una lista corta.
  transformers  modelo NER en español. Mejor precisión, pero descarga ~500MB-1GB la primera
                vez. Solo con --modelo, nunca por defecto: no se descarga un modelo sin que
                alguien lo pida.

Uso:
    detectar_entidades.py archivo.md [archivo.pdf …]
    detectar_entidades.py --all              # todo el árbol rastreado
    detectar_entidades.py archivo.pdf --ocr  # escanea el PDF con OCR antes de analizar
    detectar_entidades.py archivo.md --modelo
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
from capacidades import hay  # noqa: E402
from scan_confidencial import REPO, cargar_denylist, extraer  # noqa: E402

# Marcadores societarios: una secuencia capitalizada junto a uno de estos es,
# casi siempre, el nombre de una organización.
MARCADORES = (
    r"Banco|Bco\.?|Grupo|Corporaci[óo]n|Corp\.?|Compa[ñn][íi]a|C[íi]a\.?|Holding|"
    r"Seguros|Aseguradora|Reaseguradora|Fondos|Administradora|Fiduciaria|Financiera|"
    r"Cooperativa|Mutualista|Casa de Valores|Bolsa de Valores|Titularizadora|"
    r"S\.?A\.?S?\b|Ltda\.?|C\.?L\.?|Inc\.?|LLC"
)
PALABRA = r"[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ&\.-]{1,}"

# [ \t]+ en vez de \s+: un nombre de organización no cruza saltos de línea, y con \s+
# "Grupo Ejemplo.\nTambien" se capturaria como una sola entidad.
_ESP = r"[ \t]+"

PATRONES = [
    # "Banco Ejemplo S.A.", "Grupo Financiero Ejemplo"
    re.compile(rf"\b(?:{MARCADORES})(?:{_ESP}(?:de|del|la|las|los|y|e)\b)?(?:{_ESP}{PALABRA}){{1,5}}"),
    # "NombrePropio S.A." — nombre propio SEGUIDO de marcador
    re.compile(rf"\b{PALABRA}(?:{_ESP}{PALABRA}){{0,3}}{_ESP}(?:{MARCADORES})\b"),
]

# RUC ecuatoriano: 13 dígitos terminados en 001. Identifica a una empresa sin ambigüedad.
RUC = re.compile(r"\b\d{10}001\b")

# Organismos públicos, reguladores y cuerpos internacionales. Aparecen constantemente en la
# normativa ecuatoriana y NUNCA son filiales del cliente: si no se filtran, entierran la señal.
# Medido sobre el árbol real: sin esta lista, 14 de 14 "no reconocidas" eran ruido.
RUIDO = {
    # Ecuador — Estado y reguladores
    "asamblea nacional", "banco central", "superintendencia", "corte constitucional",
    "presidencia de la republica", "presidencia de la república", "registro oficial",
    "ministerio", "servicio de rentas internas", "contraloria", "contraloría",
    "procuraduria", "procuraduría", "defensoria", "defensoría", "fiscalia", "fiscalía",
    "junta de politica", "junta de política", "corporacion de seguro", "corporación de seguro",
    "corporacion del seguro", "corporación del seguro",
    "seguro de depositos", "seguro de depósitos", "cosede", "unidad de analisis financiero",
    "unidad de análisis financiero", "consejo de participacion", "consejo de participación",
    # Internacionales. Se listan las raíces, no las frases completas: el patrón captura
    # fragmentos ("Acción Financiera") y variantes de género ("Financiero Internacional"),
    # así que filtrar por la frase entera deja pasar casi todo.
    "accion financiera", "acción financiera", "gafi", "gafilat",
    "banco mundial", "fondo monetario", "naciones unidas", "comite de basilea",
    "comité de basilea", "union europea", "unión europea", "banco interamericano",
    # Genéricos que el patrón captura pero no nombran a nadie
    "la corporacion", "la corporación", "la compania", "la compañia", "la compañía",
    "administracion financiera", "administración financiera", "seguros y valores",
    "casa de valores", "bolsa de valores", "sistema financiero",
}


def _es_ruido(norm: str) -> bool:
    return any(r in norm for r in RUIDO)


def _normalizar(s: str) -> str:
    # Los espacios dobles y las entidades HTML sobreviven a la extracción de PDFs y de
    # notebooks; sin limpiarlos, "Seguros y Valores" y "Seguros  y  Valores" cuentan aparte.
    s = re.sub(r"&[a-z]+;?|&#\d+;?", " ", s)
    return re.sub(r"\s+", " ", s).strip(" .,;:&").lower()


def _clave(bruto: str) -> str:
    return _normalizar(bruto).rstrip(".").replace(".", "")


def fusionar(acumulado: dict, nuevo: Counter) -> dict:
    """Une resultados de varios archivos por forma normalizada.

    El dedupe por archivo no basta: dos archivos pueden producir formas de superficie
    distintas de la misma organización y, al sumarlas, reaparece la duplicación.
    """
    for nombre, n in nuevo.items():
        k = _clave(nombre)
        mejor, total = acumulado.get(k, ("", 0))
        acumulado[k] = (nombre if len(nombre) > len(mejor) else mejor, total + n)
    return acumulado


def entidades_heuristico(texto: str) -> Counter:
    """Los dos patrones se solapan a propósito (uno ancla por la izquierda y otro por la
    derecha), así que la misma organización aparece con varias formas de superficie:
    'Seguros Equinoccial S.A.' y 'Seguros Equinoccial S.A'. Se agrupan por forma
    normalizada y se conserva la más larga como representante."""
    por_clave: dict[str, tuple[str, int]] = {}
    for pat in PATRONES:
        for m in pat.finditer(texto):
            bruto = m.group(0).strip()
            norm = _normalizar(bruto)
            # Fragmentos truncados por entidades HTML ("Grupo de Acci&") o por el final
            # del patrón: no son nombres, son restos de extracción.
            if len(norm) < 6 or _es_ruido(norm) or norm.split()[-1] in ("de", "del", "la", "y", "e"):
                continue
            clave = _clave(bruto)
            mejor, n = por_clave.get(clave, ("", 0))
            por_clave[clave] = (bruto if len(bruto) > len(mejor) else mejor, n + 1)
    return Counter({nombre: n for nombre, n in por_clave.values()})


def entidades_modelo(texto: str) -> Counter:
    """NER con transformers. Solo bajo petición explícita: descarga modelo."""
    from transformers import pipeline
    ner = pipeline(
        "ner",
        model="mrm8488/bert-spanish-cased-finetuned-ner",
        aggregation_strategy="simple",
    )
    out = Counter()
    # El modelo tiene límite de contexto; se trocea con holgura.
    for i in range(0, len(texto), 1500):
        for e in ner(texto[i:i + 1500]):
            if e.get("entity_group") in ("ORG", "PER"):
                out[e["word"].strip()] += 1
    return out


def conocidas(dl: dict) -> list[re.Pattern]:
    pats = dl["bloquea"]["identidad"]["patrones"]
    return [re.compile(p, re.I) for p in pats]


def clasificar(hallazgos: Counter, dl: dict) -> tuple[list, list]:
    pats = conocidas(dl)
    ya, nuevas = [], []
    for nombre, n in hallazgos.most_common():
        (ya if any(p.search(nombre) for p in pats) else nuevas).append((nombre, n))
    return ya, nuevas


def texto_de(ruta: Path, usar_ocr: bool) -> str:
    if ruta.suffix.lower() == ".pdf" and usar_ocr:
        from inspeccionar_pdf import inspeccionar
        return inspeccionar(ruta, forzar_ocr=True)["_texto"]
    t, _motivo = extraer(ruta, limite_mb=50)  # aquí no es un hook: se permite más grande
    return t or ""


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 2

    dl = cargar_denylist()
    usar_modelo = "--modelo" in args
    usar_ocr = "--ocr" in args

    if "--all" in args:
        rutas = subprocess.run(["git", "ls-files"], capture_output=True, text=True,
                               cwd=REPO).stdout.split()
    else:
        rutas = [a for a in args if not a.startswith("-")]

    if usar_modelo and not hay("transformers"):
        print("  transformers no disponible; se usa el heurístico.")
        usar_modelo = False

    acumulado: dict = {}
    rucs: Counter = Counter()
    ilegibles: list[tuple[str, str]] = []
    revisados = 0

    for r in rutas:
        p = REPO / r if not Path(r).is_absolute() else Path(r)
        if not p.is_file():
            continue
        try:
            t = texto_de(p, usar_ocr)
        except Exception as e:
            # Nunca en silencio: un archivo que no se pudo leer NO es un archivo limpio.
            ilegibles.append((r, f"{type(e).__name__}: {e}"))
            continue
        if not t.strip():
            ilegibles.append((r, "sin texto extraíble"
                              + ("" if usar_ocr else " — prueba --ocr si es un escaneo")))
            continue
        revisados += 1
        acumulado = fusionar(acumulado, entidades_modelo(t) if usar_modelo else entidades_heuristico(t))
        rucs += Counter(RUC.findall(t))

    total = Counter({nombre: n for nombre, n in acumulado.values()})
    ya, nuevas = clasificar(total, dl)

    print(f"\nENTIDADES NOMBRADAS — {revisados} archivo(s) · método: "
          f"{'transformers' if usar_modelo else 'heurístico'}"
          + ("  · con OCR" if usar_ocr else ""))

    if ya:
        print(f"\n  EN LA DENYLIST ({len(ya)}) — coincidencias confirmadas")
        for n, c in ya[:20]:
            print(f"    {c:4}×  {n}")

    if nuevas:
        print(f"\n  NO RECONOCIDAS ({len(nuevas)}) — ¿alguna es filial del cliente?")
        print("    Si lo es, añádela a bloquea.identidad.patrones en .claude/denylist.json")
        for n, c in nuevas[:40]:
            print(f"    {c:4}×  {n}")

    if rucs:
        print(f"\n  RUC ECUATORIANOS ({len(rucs)}) — identifican a una empresa sin ambigüedad")
        for n, c in rucs.most_common(20):
            print(f"    {c:4}×  {n}")

    if not (ya or nuevas or rucs):
        print("\n  Sin organizaciones detectadas.")

    if ilegibles:
        print(f"\n  NO ANALIZADOS ({len(ilegibles)}) — no se dan por limpios")
        for r, motivo in ilegibles[:20]:
            print(f"    {r}  ({motivo})")

    print()
    # Nunca bloquea: es una herramienta de revisión, no una compuerta.
    return 0


if __name__ == "__main__":
    sys.exit(main())

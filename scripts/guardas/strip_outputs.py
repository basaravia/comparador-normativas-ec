#!/usr/bin/env python3
"""Filtro `clean` de git: quita las salidas de los notebooks antes de que entren al índice.

Equivalente funcional a nbstripout, pero con **stdlib pura**: un filtro de git corre en
el shell de git, que no conoce entornos conda. Depender de un paquete instalado en un env
concreto lo haría frágil justo donde no puede fallar.

Lee el notebook por stdin y lo escribe limpio por stdout. La copia de trabajo NO se toca:
sigues viendo tus salidas en local; simplemente no viajan a un repositorio público.

Instalación (ver .claude/scripts/instalar_guardas.sh):
    git config filter.nbstrip.clean .claude/scripts/strip_outputs.py
    git config filter.nbstrip.smudge cat
    echo '*.ipynb filter=nbstrip' >> .gitattributes
"""
from __future__ import annotations

import json
import sys


def limpiar(nb: dict) -> dict:
    for celda in nb.get("cells", []):
        if celda.get("cell_type") == "code":
            celda["outputs"] = []
            celda["execution_count"] = None
        # Metadatos de ejecución que también filtran rutas y tiempos locales.
        celda.get("metadata", {}).pop("execution", None)

    # signature/widgets pueden acarrear estado serializado del kernel.
    meta = nb.get("metadata", {})
    meta.pop("widgets", None)
    if "signature" in meta:
        meta.pop("signature")
    return nb


def main() -> int:
    crudo = sys.stdin.read()
    if not crudo.strip():
        return 0
    try:
        nb = json.loads(crudo)
    except json.JSONDecodeError:
        # No es un notebook válido: pasa el contenido intacto en vez de destruirlo.
        # Un filtro clean que corrompe archivos es mucho peor que uno que no filtra.
        sys.stdout.write(crudo)
        return 0

    json.dump(limpiar(nb), sys.stdout, indent=1, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

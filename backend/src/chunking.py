"""Chunking semántico de artículos normativos (ítem 8) — modelo parent-child.

Hoy un artículo entero es un solo vector. Para el artículo de tres líneas eso es
exactamente lo correcto; para el artículo de cuatro páginas con veinte numerales —el
formato habitual de las resoluciones de la Junta y de la Superintendencia— el vector
resultante es el promedio de veinte obligaciones distintas, y ese promedio no se parece
mucho a ninguna de ellas. La consulta que busca *"custodia de expedientes"* no recupera
el artículo que la contiene porque el numeral 14 pesa una vigésima parte del vector.

Este módulo subdivide **solo lo que no entra en el presupuesto**, respetando las fronteras
que el propio documento marca:

  · **Numerales** — ``1.``  ``1.1.``  ``1.-``  ``1)``
  · **Literales** — ``a)``  ``(a)``  ``a.-``  ``a.``
  · **Párrafos / incisos** — saltos de línea del texto reflowed por Docling.

Cortar por esas marcas y no cada N caracteres importa: un corte a la mitad de un numeral
produce dos fragmentos que no dicen ninguno lo que decía el numeral, y el sistema los
indexa como si fueran dos obligaciones.

Modelo parent-child
-------------------
**Se indexa el sub-chunk; se devuelve el artículo.** El Bloque A fija el artículo como
unidad de resultado —un papel de trabajo cita artículos, no fragmentos— así que la
subdivisión tiene que ser invisible aguas abajo. Cada sub-chunk viaja con el artículo
padre entero a cuestas:

  · ``chunk_id``          — ``{element_id}_c{i}``, i desde 0. Clave única de la fila.
  · ``parent_element_id`` — ``element_id`` del artículo original.
  · ``embed_text``        — lo que se indexa: contexto (sección + "Artículo N: epígrafe")
                            seguido del texto del sub-chunk. El contexto se repite en
                            cada sub-chunk a propósito: sin él, el numeral 14 aislado no
                            dice de qué artículo ni de qué norma habla, y el embedding
                            pierde justo la información que lo hace recuperable.
  · ``embed_text_padre``  — el ``embed_text`` original, para restituirlo al devolver.
  · Todo lo demás — ``element_id``, ``doc_id``, ``numero``, ``encabezado``,
    ``contenido`` **íntegro**, ``seccion``, ``tipo_elemento``… — se hereda sin tocar.

Que ``contenido`` se conserve completo en cada sub-chunk (y no solo el fragmento) es lo
que permite a ``search_engine`` devolver el artículo padre sin consultar un segundo
DataFrame: la fila del sub-chunk *ya es* el artículo, más los campos de chunking.

Artículos cortos
----------------
Si el artículo entra en el presupuesto no se subdivide: se devuelve una sola fila con su
``embed_text`` **idéntico** al original y ``es_subchunk=False``. Un corpus de artículos
cortos produce así un índice bit a bit equivalente al de antes de este módulo. La
alternativa —fabricar un sub-chunk "0" con texto reconstruido— metería diferencias
silenciosas en el caso mayoritario a cambio de nada.

Presupuesto de tokens
---------------------
``estimar_tokens`` es una **estimación por palabras**, no un tokenizador. Cargar el
tokenizador del modelo de embeddings aquí ataría el chunking al backend (que es
configurable y a veces remoto) y metería un import pesado en un módulo puro. El factor
de `TOKENS_POR_PALABRA` está calibrado por lo alto para español legal —palabras largas,
poca abreviatura—, de modo que el error caiga del lado de chunks algo más cortos que el
presupuesto y no de truncados por el backend.
"""
from __future__ import annotations

import logging
import math
import re
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

MAX_TOKENS_POR_DEFECTO = 512
SOLAPE_POR_DEFECTO = 50

#: Tokens por palabra en español jurídico. Ver nota de "Presupuesto de tokens".
TOKENS_POR_PALABRA = 1.35

#: Piso del presupuesto de cuerpo cuando el contexto se come el máximo (artículos con
#: epígrafe kilométrico y `max_tokens` pequeño). Sin piso, el cuerpo se quedaría sin
#: espacio y el chunking degeneraría en una pieza por palabra.
PRESUPUESTO_MINIMO = 32

#: Columnas que añade el chunking. `search_engine` las retira al devolver el padre.
COLUMNAS_CHUNK: tuple[str, ...] = (
    "chunk_id",
    "parent_element_id",
    "chunk_index",
    "n_chunks",
    "chunk_text",
    "es_subchunk",
    "embed_text_padre",
)

#: Nombres aceptados para la columna que apunta al artículo padre. `articulo_element_id`
#: es el que usa el modelo N:N (`coverage.CoverageLink`); `parent_element_id` el que
#: emite este módulo. Se aceptan los dos para que un DataFrame venido de cualquiera de
#: los dos lados se indexe igual.
COLUMNAS_PADRE: tuple[str, ...] = ("articulo_element_id", "parent_element_id")

# ── Fronteras semánticas ──────────────────────────────────────────────────────

# Numerales: 1.  1.1.  1.1.1.  1.-  1)  1-
_NUMERAL = r"\d+(?:\.\d+)*\s*(?:\.\-|[.)\-])"
# Literales: a)  (a)  a.-  a.
_LITERAL = r"\(?[a-zA-ZñÑ](?:\.\-|[.)])"
# El marcador tiene que ir seguido de espacio: "1." en "USD 1.500" no es un numeral, y
# el filtro de posición (`_es_frontera`) descarta el resto de falsos positivos.
_PAT_MARCADOR = re.compile(rf"(?:{_NUMERAL}|{_LITERAL})(?=\s)")

# Cierres de enunciado tras los que un marcador sí abre un ítem de enumeración.
_CIERRES = (".", ";", ":")

_PAT_PARRAFO = re.compile(r"\n+")
_PAT_FRASE = re.compile(r"(?<=[.;:])\s+")


def estimar_tokens(texto: Any) -> int:
    """Tokens aproximados de un texto. Estimación por palabras, no tokenización real."""
    palabras = str(texto or "").split()
    return math.ceil(len(palabras) * TOKENS_POR_PALABRA) if palabras else 0


def _es_frontera(texto: str, inicio: int) -> bool:
    """¿El marcador que empieza en `inicio` abre de verdad un ítem?

    Tres reglas, todas nacidas de falsos positivos concretos del corpus normativo:

      · **Pegado a la palabra anterior → no.** En "USD 2.500.000" el regex ve un
        candidato "500." cuyo prefijo termina en ".", sin espacio: es parte de un número.
      · **Inicio de texto o de línea → sí.** Es la forma canónica de una enumeración.
      · **Tras `.`, `;` o `:` → sí; tras cualquier otra cosa → no.** Esto es lo que
        distingue "…lo previsto en el artículo 5. Las entidades…" (el "5." va tras una
        palabra: es una cita, no un ítem) de "…mantener el registro; 5. Reportar…".
    """
    anterior = texto[:inicio]
    if not anterior.strip():
        return True
    if not anterior[-1].isspace():
        return False
    if "\n" in anterior[len(anterior.rstrip()):]:
        return True
    return anterior.rstrip().endswith(_CIERRES)


def _partir_por_marcadores(parrafo: str) -> list[str]:
    """Corta un párrafo en los marcadores de numeral/literal que contenga."""
    cortes = [
        m.start() for m in _PAT_MARCADOR.finditer(parrafo)
        if m.start() > 0 and _es_frontera(parrafo, m.start())
    ]
    if not cortes:
        return [parrafo]

    limites = [0, *cortes, len(parrafo)]
    unidades = [parrafo[ini:fin].strip() for ini, fin in zip(limites, limites[1:])]
    return [u for u in unidades if u]


def _segmentar(texto: str) -> list[str]:
    """Texto → unidades semánticas mínimas (párrafo, numeral o literal)."""
    unidades: list[str] = []
    for parrafo in _PAT_PARRAFO.split(str(texto or "")):
        parrafo = parrafo.strip()
        if parrafo:
            unidades.extend(_partir_por_marcadores(parrafo))
    return unidades


def _partir_por_palabras(texto: str, presupuesto: int) -> list[str]:
    """Último recurso: una frase que no cabe entera se parte por palabras."""
    palabras = texto.split()
    por_pieza = max(1, int(presupuesto / TOKENS_POR_PALABRA))
    return [" ".join(palabras[i:i + por_pieza]) for i in range(0, len(palabras), por_pieza)]


def _partir_unidad_larga(unidad: str, presupuesto: int) -> list[str]:
    """Una unidad que no cabe en el presupuesto se parte por frases, luego por palabras.

    Ocurre con el numeral de media página. Es preferible cortar por punto y coma dentro
    del numeral que dejarlo entrar entero y desbordar el presupuesto del backend, que lo
    truncaría por el final sin avisar.
    """
    piezas: list[str] = []
    for frase in _PAT_FRASE.split(unidad):
        frase = frase.strip()
        if not frase:
            continue
        if estimar_tokens(frase) <= presupuesto:
            piezas.append(frase)
        else:
            piezas.extend(_partir_por_palabras(frase, presupuesto))
    return piezas or [unidad]


def _cola_solape(texto: str, solape: int) -> str:
    """Últimas palabras de un chunk, las que se repiten al inicio del siguiente."""
    if solape <= 0:
        return ""
    palabras = texto.split()
    if not palabras:
        return ""
    n = max(1, int(solape / TOKENS_POR_PALABRA))
    return " ".join(palabras[-n:])


def _empaquetar(unidades: list[str], presupuesto: int, solape: int) -> list[str]:
    """Agrupa unidades en chunks de hasta `presupuesto` tokens, con solape entre ellos.

    El solape existe porque una frontera, por bien elegida que esté, parte un contexto:
    el numeral que empieza "Para los efectos del literal anterior…" no se entiende sin la
    cola del chunk previo. Repetir las últimas palabras cuesta unos pocos tokens y evita
    que la unidad que abre un chunk quede huérfana.
    """
    chunks: list[str] = []
    actual: list[str] = []

    for unidad in unidades:
        piezas = (
            [unidad] if estimar_tokens(unidad) <= presupuesto
            else _partir_unidad_larga(unidad, presupuesto)
        )
        for pieza in piezas:
            if actual and estimar_tokens(" ".join([*actual, pieza])) > presupuesto:
                cerrado = " ".join(actual)
                chunks.append(cerrado)
                cola = _cola_solape(cerrado, solape)
                actual = [cola, pieza] if cola else [pieza]
            else:
                actual.append(pieza)

    if actual:
        chunks.append(" ".join(actual))
    return chunks


# ── Composición de la fila ────────────────────────────────────────────────────

def _como_dict(row: dict | pd.Series) -> dict:
    return row.to_dict() if hasattr(row, "to_dict") else dict(row)


def _texto_del_articulo(fila: dict) -> str:
    """El cuerpo a subdividir. `contenido` es lo que emite el parser; el resto, respaldo."""
    for campo in ("contenido", "texto", "embed_text"):
        valor = str(fila.get(campo) or "").strip()
        if valor:
            return valor
    return ""


def _prefijo_contexto(fila: dict) -> str:
    """Sección + etiqueta del artículo: el contexto que encabeza cada sub-chunk.

    Réplica deliberada de ``NormativaParser._build_embed_text`` **sin** su truncado a
    1200 caracteres: aquí el presupuesto lo pone `max_tokens`, no una constante ciega.
    """
    partes: list[str] = []
    seccion = str(fila.get("seccion") or "").strip()
    if seccion:
        partes.append(seccion)

    numero = str(fila.get("numero") or "").strip()
    if str(fila.get("tipo_elemento") or "").strip() == "articulo" and numero:
        etiqueta = f"Artículo {numero}"
    else:
        etiqueta = numero

    encabezado = str(fila.get("encabezado") or "").strip()
    if encabezado and encabezado != numero:
        etiqueta = f"{etiqueta}: {encabezado}" if etiqueta else encabezado
    if etiqueta:
        partes.append(etiqueta)

    return "\n".join(partes)


def _componer_embed(prefijo: str, cuerpo: str) -> str:
    return "\n".join(p for p in (prefijo, cuerpo) if p)


def _fila_chunk(
    fila: dict,
    indice: int,
    total: int,
    chunk_text: str,
    embed_text: str,
    embed_padre: str,
    parent_id: str,
) -> dict:
    return {
        **fila,
        "embed_text": embed_text,
        "chunk_id": f"{parent_id}_c{indice}",
        "parent_element_id": parent_id,
        "chunk_index": indice,
        "n_chunks": total,
        "chunk_text": chunk_text,
        "es_subchunk": total > 1,
        "embed_text_padre": embed_padre,
    }


# ── API pública ───────────────────────────────────────────────────────────────

def chunk_articulo(
    row: dict | pd.Series,
    max_tokens: int = MAX_TOKENS_POR_DEFECTO,
    solape: int = SOLAPE_POR_DEFECTO,
) -> list[dict]:
    """Subdivide un artículo en sub-chunks parent-child. Los cortos se devuelven tal cual.

    Devuelve **siempre al menos una fila**, con las mismas columnas de entrada más las de
    `COLUMNAS_CHUNK`. Un artículo que cabe en el presupuesto produce una única fila con su
    ``embed_text`` intacto y ``es_subchunk=False``.
    """
    if max_tokens <= 0:
        raise ValueError(f"max_tokens debe ser positivo, se recibió {max_tokens!r}")
    if solape < 0:
        raise ValueError(f"solape no puede ser negativo, se recibió {solape!r}")
    if solape >= max_tokens:
        raise ValueError(
            f"solape ({solape}) debe ser menor que max_tokens ({max_tokens}): un solape "
            "que iguala el presupuesto haría que cada chunk fuera la cola del anterior."
        )

    fila = _como_dict(row)
    parent_id = str(fila.get("element_id") or "")
    cuerpo = _texto_del_articulo(fila)
    prefijo = _prefijo_contexto(fila)
    embed_padre = str(fila.get("embed_text") or "").strip() or _componer_embed(prefijo, cuerpo)

    # Artículo corto: no se toca. El `embed_text` que se indexa es el mismo de antes.
    if estimar_tokens(embed_padre) <= max_tokens or not cuerpo:
        return [_fila_chunk(fila, 0, 1, cuerpo, embed_padre, embed_padre, parent_id)]

    # El contexto se repite en cada sub-chunk, así que el cuerpo dispone de lo que sobra.
    presupuesto = max(max_tokens - estimar_tokens(prefijo), PRESUPUESTO_MINIMO)
    solape_efectivo = min(solape, presupuesto // 2)

    piezas = _empaquetar(_segmentar(cuerpo), presupuesto, solape_efectivo)
    if len(piezas) <= 1:
        return [_fila_chunk(fila, 0, 1, cuerpo, embed_padre, embed_padre, parent_id)]

    total = len(piezas)
    return [
        _fila_chunk(
            fila, i, total, pieza, _componer_embed(prefijo, pieza), embed_padre, parent_id,
        )
        for i, pieza in enumerate(piezas)
    ]


def chunk_normativa_df(
    normativa_df: pd.DataFrame,
    max_tokens: int = MAX_TOKENS_POR_DEFECTO,
    solape: int = SOLAPE_POR_DEFECTO,
) -> pd.DataFrame:
    """Aplica `chunk_articulo` a cada fila y devuelve el DataFrame para indexar.

    El resultado tiene **una fila por sub-chunk**, no por artículo: es lo que se le pasa a
    ``NormativaIndex.build()``. Para iterar artículos (alcance, Vía 2, cobertura) hay que
    seguir usando el DataFrame original — si no, cada artículo largo se analizaría tantas
    veces como sub-chunks tenga.
    """
    if normativa_df is None or len(normativa_df) == 0:
        return normativa_df.copy() if normativa_df is not None else pd.DataFrame()

    filas: list[dict] = []
    for _, fila in normativa_df.iterrows():
        filas.extend(chunk_articulo(fila, max_tokens=max_tokens, solape=solape))

    df = pd.DataFrame(filas)
    subdivididos = int(df["es_subchunk"].sum())
    logger.info(
        "Chunking: %d elementos → %d sub-chunks (%d filas provienen de %d artículos "
        "subdivididos; max_tokens=%d, solape=%d)",
        len(normativa_df), len(df), subdivididos,
        df.loc[df["es_subchunk"], "parent_element_id"].nunique() if subdivididos else 0,
        max_tokens, solape,
    )
    return df


def detectar_columna_padre(df: pd.DataFrame) -> str | None:
    """Nombre de la columna que apunta al artículo padre, o None si no hay chunking.

    Es lo que permite a `NormativaIndex` decidir si tiene que agrupar sin que quien
    llama tenga que declararlo: un DataFrame sin chunking se indexa exactamente igual
    que antes de este módulo.
    """
    if df is None:
        return None
    for columna in COLUMNAS_PADRE:
        if columna in df.columns and df[columna].notna().any():
            return columna
    return None


def como_articulo_padre(fila: dict) -> dict:
    """Fila de sub-chunk → artículo padre: restituye `embed_text` y quita lo del chunking.

    **Por qué se retiran las columnas y no se dejan pasar.** ``chunk_id`` es, aguas abajo,
    el identificador de una *sección del manual* (`coverage.CoverageLink.seccion_chunk_id`,
    `dual._links_desde_via1`). Un artículo que viaje con un ``chunk_id`` propio se
    confundiría con una sección en cuanto alguien lo lea con `.get("chunk_id")`. La
    procedencia del sub-chunk no se pierde: `semantic_search` la devuelve bajo
    `chunk_id_match` / `chunk_text_match`, nombres que no colisionan con nada.
    """
    salida = dict(fila)
    padre = salida.pop("embed_text_padre", None)
    if padre:
        salida["embed_text"] = padre
    for columna in COLUMNAS_CHUNK:
        salida.pop(columna, None)
    for columna in COLUMNAS_PADRE:
        salida.pop(columna, None)
    return salida

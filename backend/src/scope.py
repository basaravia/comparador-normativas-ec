"""Selector de alcance por lista (ítem 7) — qué artículos y qué secciones entran.

Hasta ahora el alcance de una corrida se elegía **por cantidad**: "muestra rápida de N
secciones", tomadas además al azar (`manual_df.sample(...)` en `streamlit_app.py`). Eso
sirve para probar que el pipeline arranca, pero no para trabajar: el encargo real es
"Art. 35 y 36 de la Ley X contra el capítulo 5 del manual", y eso no se puede expresar con
un número.

Este módulo es la mitad pura de esa función: filtros sobre los DataFrames tabulados, sin
Streamlit ni estado global, de modo que la interfaz (pestaña 3), el checkpoint y el papel
de trabajo hablen del mismo alcance en vez de cada uno del suyo.

**Por qué `RunScope` y no un puñado de argumentos sueltos.** El alcance tiene que viajar:
al `manifest.json` del checkpoint —reanudar con otro alcance produce un papel de trabajo
que dice cubrir unos artículos y en realidad analizó otros (ver `checkpoint.Manifest`)— y a
la hoja de trazabilidad del Excel. Un objeto serializable y comparable es lo que hace
verificable esa continuidad; una lista de kwargs no se puede guardar ni comparar.

**Convenios de los filtros**, iguales en las dos funciones:

  · `None` o colección vacía en un eje = **sin restricción** en ese eje. Los ejes se
    combinan con AND: cada uno estrecha el resultado del anterior.
  · Los números de artículo se comparan normalizados ("Art. 35", "art 35.", "035" y "35"
    son el mismo artículo), porque quien escribe el alcance lo copia del documento.
  · Los textos (`secciones`, `jerarquias`) se comparan como **subcadena**, sin acentos ni
    mayúsculas: "titulo ii" encuentra "Título II > Obligaciones". Es un cuadro de
    búsqueda, no un identificador.
  · Si se pide filtrar por una columna que el DataFrame no tiene, se levanta `ValueError`
    en vez de devolver todo. Un alcance que se ignora en silencio analiza de más y lo
    registra como si fuera lo pedido, que es la falla que este módulo viene a cerrar.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Sequence

import pandas as pd

logger = logging.getLogger(__name__)

VERSION_ESQUEMA = 1

# Tipos de elemento que cuentan como articulado. Es el default de
# `filtrar_articulos`: las disposiciones, anexos y preámbulos entran solo si se piden
# explícitamente (ver `PRESET_SOLO_DISPOSICIONES`). Vocabulario de `document_parser`.
TIPO_ARTICULO = "articulo"
TIPO_DISPOSICION = "disposicion"
TIPO_ANEXO = "anexo"
TIPOS_ELEMENTO_POR_DEFECTO: tuple[str, ...] = (TIPO_ARTICULO,)

# Presets de la pestaña 3. Son kwargs de `filtrar_articulos`, no ramas de código: así el
# preset y la selección a mano no pueden divergir en su significado.
PRESET_TODO_EL_ARTICULADO = "todo_el_articulado"
PRESET_EXCLUIR_REFERENCIAS = "excluir_referencias"
PRESET_SOLO_DISPOSICIONES = "solo_disposiciones"

PRESETS_ARTICULOS: dict[str, dict[str, Any]] = {
    # Todo lo que es artículo, incluidas las remisiones a otras normas.
    PRESET_TODO_EL_ARTICULADO: {
        "tipos_elemento": (TIPO_ARTICULO,),
        "incluir_referencias": True,
    },
    # El default de trabajo: artículos sustantivos. `es_referencia` ya existía en el
    # parser; aquí solo se consume.
    PRESET_EXCLUIR_REFERENCIAS: {
        "tipos_elemento": (TIPO_ARTICULO,),
        "incluir_referencias": False,
    },
    # Disposiciones generales/transitorias/finales, que suelen ser remisiones y por eso
    # no se les aplica el filtro de referencias: excluirlas dejaría el preset vacío.
    PRESET_SOLO_DISPOSICIONES: {
        "tipos_elemento": (TIPO_DISPOSICION,),
        "incluir_referencias": True,
    },
}

_PREFIJO_ARTICULO = re.compile(r"^(?:art[íi]culos?|arts?)\.?\s*", re.IGNORECASE)
_CEROS_A_LA_IZQUIERDA = re.compile(r"^0+(?=\d)")


# ── normalización ─────────────────────────────────────────────────────────────

def _plegar(texto: Any) -> str:
    """Minúsculas sin acentos, para comparar texto escrito por una persona.

    "Título II" y "titulo ii" son la misma sección para quien escribe el alcance; que no
    lo sean para el filtro solo produce alcances vacíos inexplicables.
    """
    s = unicodedata.normalize("NFKD", str(texto))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.casefold().strip()


def normalizar_numero(valor: Any) -> str:
    """Número de artículo comparable: "Art. 35", "art 35.", "035" y "35" → "35".

    Se conserva lo que venga después del número ("5 bis" sigue siendo "5 bis"): son
    artículos distintos y colapsarlos metería en el alcance uno que nadie pidió.
    """
    s = _plegar(valor)
    s = _PREFIJO_ARTICULO.sub("", s)
    s = s.strip().rstrip(".").strip()
    return _CEROS_A_LA_IZQUIERDA.sub("", s)


def _lista(valores: Iterable[Any] | None) -> tuple[str, ...]:
    """Normaliza un eje de filtro a tupla de strings. `None` y vacío son lo mismo."""
    if valores is None:
        return ()
    if isinstance(valores, (str, bytes)):
        return (str(valores),)
    return tuple(str(v) for v in valores)


def _exigir_columna(df: pd.DataFrame, columna: str, filtro: str) -> None:
    """Un filtro pedido sobre una columna inexistente es un error, no un no-op."""
    if columna not in df.columns:
        raise ValueError(
            f"El DataFrame no tiene la columna {columna!r}, exigida por el filtro "
            f"{filtro!r}. Columnas disponibles: {sorted(df.columns)}"
        )


def _contiene_alguna(serie: pd.Series, patrones: Sequence[str]) -> pd.Series:
    plegados = [_plegar(p) for p in patrones if _plegar(p)]
    if not plegados:
        return pd.Series(True, index=serie.index)
    plegada = serie.map(_plegar)
    mascara = pd.Series(False, index=serie.index)
    for p in plegados:
        mascara |= plegada.str.contains(re.escape(p), regex=True, na=False)
    return mascara


# ── filtros ───────────────────────────────────────────────────────────────────

def filtrar_articulos(
    normativa_df: pd.DataFrame,
    doc_ids: Iterable[str] | None = None,
    numeros: Iterable[str] | None = None,
    secciones: Iterable[str] | None = None,
    incluir_referencias: bool = False,
    tipos_elemento: Iterable[str] | None = None,
) -> pd.DataFrame:
    """Artículos de la normativa que entran en el alcance.

    Ejes (AND entre ellos; `None`/vacío = sin restricción):

      · `doc_ids`   — normativas concretas, por `doc_id` exacto.
      · `numeros`   — números de artículo, normalizados (ver `normalizar_numero`).
      · `secciones` — subcadena sobre la columna `seccion` ("Título II", "Capítulo I").
      · `tipos_elemento` — `None` (defecto) = solo `articulo`; una colección vacía = sin
        filtro por tipo; una colección con valores = exactamente esos tipos. Los tres
        casos son distintos a propósito: "el defecto", "todo" y "esto".
      · `incluir_referencias` — `False` (defecto) descarta las filas `es_referencia`:
        son citas a otras normas dentro de un preámbulo o unas disposiciones finales, no
        obligaciones que el manual tenga que cumplir. Contarlas hunde la cobertura con
        artículos que nadie debe cumplir (mismo criterio que `coverage.vista_normativa`).

    Devuelve una copia con el índice reiniciado; nunca muta la entrada.
    """
    df = normativa_df.copy()
    if df.empty:
        return df.reset_index(drop=True)

    tipos_pedidos = tipos_elemento is not None
    tipos = _lista(tipos_elemento) if tipos_pedidos else TIPOS_ELEMENTO_POR_DEFECTO
    if tipos:
        if "tipo_elemento" in df.columns:
            df = df[df["tipo_elemento"].astype(str).isin(tipos)]
        elif tipos_pedidos:
            # El default se salta en silencio (no todo corpus trae la columna); un tipo
            # pedido a mano y no filtrable, no.
            _exigir_columna(df, "tipo_elemento", "tipos_elemento")

    docs = _lista(doc_ids)
    if docs:
        _exigir_columna(df, "doc_id", "doc_ids")
        df = df[df["doc_id"].astype(str).isin(docs)]

    nums = _lista(numeros)
    if nums:
        _exigir_columna(df, "numero", "numeros")
        buscados = {normalizar_numero(n) for n in nums}
        df = df[df["numero"].map(normalizar_numero).isin(buscados)]

    secs = _lista(secciones)
    if secs:
        _exigir_columna(df, "seccion", "secciones")
        df = df[_contiene_alguna(df["seccion"], secs)]

    if not incluir_referencias and "es_referencia" in df.columns:
        df = df[~df["es_referencia"].fillna(False).astype(bool)]

    return df.reset_index(drop=True)


def filtrar_secciones(
    manual_df: pd.DataFrame,
    doc_ids: Iterable[str] | None = None,
    jerarquias: Iterable[str] | None = None,
    chunk_ids: Iterable[str] | None = None,
) -> pd.DataFrame:
    """Secciones del manual que entran en el alcance.

    Ejes (AND entre ellos; `None`/vacío = sin restricción):

      · `doc_ids`    — manuales concretos, por `doc_id` exacto.
      · `jerarquias` — subcadena sobre `jerarquia`: "4." toma el capítulo 4 entero,
        "4.1" solo esa sección. Es lo que hace posible "el capítulo 5 del manual" sin
        enumerar sus secciones una a una.
      · `chunk_ids`  — selección exacta, la que produce el multiselect de la interfaz.

    `chunk_ids` no reordena: el resultado conserva el orden del documento, porque el papel
    de trabajo se lee en ese orden y no en el de los clics.
    """
    df = manual_df.copy()
    if df.empty:
        return df.reset_index(drop=True)

    docs = _lista(doc_ids)
    if docs:
        _exigir_columna(df, "doc_id", "doc_ids")
        df = df[df["doc_id"].astype(str).isin(docs)]

    jer = _lista(jerarquias)
    if jer:
        _exigir_columna(df, "jerarquia", "jerarquias")
        df = df[_contiene_alguna(df["jerarquia"], jer)]

    chunks = _lista(chunk_ids)
    if chunks:
        _exigir_columna(df, "chunk_id", "chunk_ids")
        df = df[df["chunk_id"].astype(str).isin(set(chunks))]

    return df.reset_index(drop=True)


def aplicar_preset(
    normativa_df: pd.DataFrame,
    preset: str,
    **filtros_extra: Any,
) -> pd.DataFrame:
    """Aplica un preset de `PRESETS_ARTICULOS`, opcionalmente estrechado por más filtros.

    Los `filtros_extra` (p. ej. `doc_ids=[...]`) se combinan con el preset y pueden
    sobrescribir sus claves: "Solo disposiciones **de la Ley X**" es un preset más un eje,
    no un cuarto preset.
    """
    if preset not in PRESETS_ARTICULOS:
        raise ValueError(
            f"Preset desconocido: {preset!r}. Disponibles: {sorted(PRESETS_ARTICULOS)}"
        )
    kwargs = {**PRESETS_ARTICULOS[preset], **filtros_extra}
    return filtrar_articulos(normativa_df, **kwargs)


def muestra_rapida(
    df: pd.DataFrame,
    n: int,
    aleatoria: bool = False,
    semilla: int = 42,
) -> pd.DataFrame:
    """Preset "Muestra rápida (N)" sobre el alcance ya filtrado.

    Por defecto toma las **primeras N** en el orden del documento, no una muestra al azar
    como hacía `streamlit_app.py`: dos corridas de prueba con el mismo N deben analizar lo
    mismo, y "las primeras N" es además lo que alguien espera al revisar por encima.

    `aleatoria=True` sigue siendo posible —para estimar sin sesgo de posición— pero es
    explícito y reproducible (`semilla`), y el resultado se devuelve en orden de documento.
    """
    if n <= 0:
        return df.iloc[0:0].reset_index(drop=True)
    if n >= len(df):
        return df.reset_index(drop=True)
    if aleatoria:
        return df.sample(n=n, random_state=semilla).sort_index().reset_index(drop=True)
    return df.head(n).reset_index(drop=True)


# ── El alcance como dato ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class RunScope:
    """Qué se analizó en una corrida, en forma serializable y comparable.

    Guarda **las dos cosas**: los identificadores resueltos (`articulos`, `secciones`) y
    los criterios que los produjeron (los ejes y el preset). Los ids son lo que permite
    verificar que una reanudación cubre exactamente lo mismo; los criterios son lo que
    permite explicar en el papel de trabajo *por qué* ese es el alcance, y volver a
    aplicarlo sobre un corpus reprocesado.

    `frozen` por el mismo motivo que `CoverageLink`: el alcance de una corrida es un hecho
    registrado, no un objeto que se ajusta a mitad de camino.
    """

    articulos: tuple[str, ...] = ()          # element_id de la normativa
    secciones: tuple[str, ...] = ()          # chunk_id del manual

    doc_ids_normativa: tuple[str, ...] = ()
    doc_ids_manual: tuple[str, ...] = ()
    numeros: tuple[str, ...] = ()
    secciones_normativa: tuple[str, ...] = ()   # filtro textual sobre `seccion`
    jerarquias: tuple[str, ...] = ()
    tipos_elemento: tuple[str, ...] = ()

    incluir_referencias: bool = False
    preset_articulos: str | None = None

    muestra_n: int | None = None
    muestra_aleatoria: bool = False
    semilla: int | None = None

    workspace_id: str = "local"
    version_esquema: int = VERSION_ESQUEMA
    etiqueta: str = ""                       # descripción libre del encargo

    def __post_init__(self) -> None:
        # Listas, sets y generadores entran igual de bien que tuplas: quien construye
        # esto viene de un multiselect, no de un literal.
        for campo in (
            "articulos", "secciones", "doc_ids_normativa", "doc_ids_manual",
            "numeros", "secciones_normativa", "jerarquias", "tipos_elemento",
        ):
            object.__setattr__(self, campo, _lista(getattr(self, campo)))

    # ── construcción ──────────────────────────────────────────────────────

    @classmethod
    def desde_dataframes(
        cls,
        normativa_df: pd.DataFrame,
        manual_df: pd.DataFrame,
        **criterios: Any,
    ) -> RunScope:
        """Captura los ids ya filtrados junto con los criterios que los produjeron.

        Se le pasan los DataFrames **ya filtrados** (la salida de `filtrar_*`), no los
        completos: así el alcance registrado y el que se ejecuta son el mismo objeto y no
        pueden discrepar.
        """
        articulos = (
            normativa_df["element_id"].astype(str).tolist()
            if "element_id" in normativa_df.columns else []
        )
        secciones = (
            manual_df["chunk_id"].astype(str).tolist()
            if "chunk_id" in manual_df.columns else []
        )
        return cls(articulos=articulos, secciones=secciones, **criterios)

    # ── lectura ───────────────────────────────────────────────────────────

    @property
    def n_articulos(self) -> int:
        return len(self.articulos)

    @property
    def n_secciones(self) -> int:
        return len(self.secciones)

    @property
    def vacio(self) -> bool:
        return not self.articulos and not self.secciones

    @property
    def llamadas_llm_estimadas(self) -> int:
        """`|secciones| + |artículos|`, no el producto.

        Es la cuenta del ítem 6: cada vía recorre su lado una vez y la caché de grading
        comparte los veredictos entre ambas. El contador en vivo de la pestaña 3 muestra
        este número, así que tiene que ser el mismo que el DoD verifica.
        """
        return self.n_articulos + self.n_secciones

    def resumen(self) -> str:
        """Línea del contador en vivo de la interfaz y de la hoja de trazabilidad."""
        return (
            f"{self.n_articulos} artículos × {self.n_secciones} secciones · "
            f"~{self.llamadas_llm_estimadas} llamadas LLM"
        )

    def huella(self) -> str:
        """Hash corto y estable del alcance, para comparar dos corridas.

        Solo sobre lo que cambia *qué* se analiza: la etiqueta libre no entra, porque
        renombrar el encargo no invalida un checkpoint.
        """
        datos = self.to_dict()
        datos.pop("etiqueta", None)
        crudo = json.dumps(datos, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(crudo.encode("utf-8")).hexdigest()[:16]

    def aplicar_a(
        self,
        normativa_df: pd.DataFrame,
        manual_df: pd.DataFrame,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Reconstruye el alcance sobre los DataFrames completos.

        Si hay ids registrados manda la lista exacta —es lo que se analizó—; si no, se
        vuelven a aplicar los criterios. Ese orden importa al reanudar: un corpus
        reprocesado puede haber cambiado de tamaño, y en ese caso vale lo que se analizó,
        no lo que el filtro devolvería hoy.
        """
        if self.articulos:
            _exigir_columna(normativa_df, "element_id", "articulos")
            normativa = normativa_df[
                normativa_df["element_id"].astype(str).isin(set(self.articulos))
            ].reset_index(drop=True)
        else:
            normativa = filtrar_articulos(
                normativa_df,
                doc_ids=self.doc_ids_normativa,
                numeros=self.numeros,
                secciones=self.secciones_normativa,
                incluir_referencias=self.incluir_referencias,
                tipos_elemento=self.tipos_elemento or None,
            )

        if self.secciones:
            manual = filtrar_secciones(manual_df, chunk_ids=self.secciones)
        else:
            manual = filtrar_secciones(
                manual_df,
                doc_ids=self.doc_ids_manual,
                jerarquias=self.jerarquias,
            )
        return normativa, manual

    # ── serialización ─────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Dict JSON-serializable (las tuplas salen como listas).

        Es lo que entra en `manifest.json` del checkpoint y en la hoja de trazabilidad.
        `dataclasses.asdict(scope)` sigue funcionando y devuelve las tuplas tal cual; esta
        versión es la que se puede pasar por `json.dumps` sin sorpresas.
        """
        crudo = asdict(self)
        return {
            k: (list(v) if isinstance(v, tuple) else v)
            for k, v in crudo.items()
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_dict(cls, datos: dict[str, Any] | None) -> RunScope:
        """Reconstruye desde un dict, tolerando claves que sobran o faltan.

        Un checkpoint viejo no tiene los campos que se añadan después, y uno nuevo leído
        por una versión anterior traería campos desconocidos. Ninguno de los dos casos
        justifica reventar al reanudar: se avisa y se sigue con los defaults.
        """
        if not datos:
            return cls()
        conocidos = {f for f in cls.__dataclass_fields__}
        sobrantes = set(datos) - conocidos
        if sobrantes:
            logger.warning(
                "RunScope: se ignoran campos desconocidos del alcance guardado: %s",
                sorted(sobrantes),
            )
        return cls(**{k: v for k, v in datos.items() if k in conocidos})

    @classmethod
    def from_json(cls, crudo: str) -> RunScope:
        return cls.from_dict(json.loads(crudo))

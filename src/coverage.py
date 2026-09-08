"""Modelo de cobertura artículo ↔ sección, N:N (ítem 5).

Hasta ahora el resultado era un DataFrame con una fila por sección del manual y los
artículos aplanados a texto. Con eso no se puede responder *"¿qué secciones cubren el
Art. 35?"* sin volver a correr el pipeline entero — y esa pregunta es la mitad del
trabajo: el Bloque A exige verificar que el 100 % de la normativa quede cubierto por algún
control, lo que se recorre desde el artículo, no desde la sección.

El informe sube además el requisito de 1:N a **N:N**: una sección puede tener que
satisfacer artículos de varias normas a la vez, y un artículo puede estar cubierto por
varias secciones.

**Es el contrato de datos de la Fase 2** (S11): de aquí saldrán los tipos de TypeScript del
frontend, generados desde el OpenAPI. Estabilidad por encima de elegancia — un cambio aquí
se propaga a la API, al frontend y al papel de trabajo.

La arista es la unidad. Cada `CoverageLink` dice *este artículo y esta sección están
relacionados, por este motivo, con esta confianza*. Las dos vistas del ítem 6 y la
cobertura global son agregaciones sobre el mismo conjunto de aristas, no cálculos
independientes que puedan discrepar entre sí.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Iterable, Iterator

import pandas as pd

from .config import DELTA_INDECISION, MIN_SEMANTIC_SCORE

logger = logging.getLogger(__name__)

VERSION_ESQUEMA = 1

# Origen de una arista, de mayor a menor evidencia.
ORIGEN_LEXICO = "lexico"              # el manual cita el artículo por número, sin ambigüedad
ORIGEN_LEXICO_AMBIGUO = "lexico_ambiguo"   # cita un número que existe en varias normativas
ORIGEN_SEMANTICO_V1 = "semantico_v1"  # recuperado desde la sección (Vía 1)
ORIGEN_SEMANTICO_V2 = "semantico_v2"  # recuperado desde el artículo (Vía 2)
ORIGEN_MANUAL = "manual"              # añadido por una persona

# ── Vocabulario de motivos de revisión manual (ítem 10) ───────────────────────
# Constantes y no literales sueltos: los produce `coverage`, los escribe `llm_grader`,
# los agrega `dual` y los filtra la interfaz. Un motivo mal escrito en uno de esos cuatro
# sitios no rompe nada visiblemente — simplemente deja de aparecer en el filtro "Solo
# revisión manual", que es la peor forma de fallar para un flag cuya razón de ser es que
# nada quede sin mirar.
MOTIVO_BANDA_INDECISION = "score_en_banda_de_indecision"
MOTIVO_VEREDICTO_INDETERMINADO = "veredicto_indeterminado"
MOTIVO_CONFLICTO_LEXICO_SEMANTICO = "conflicto_lexico_semantico"
MOTIVO_ARTICULO_SIN_COBERTURA = "articulo_sin_cobertura"
MOTIVO_PARCIAL_CON_BRECHAS = "parcial_con_brechas"
# Producidos aguas arriba (`dual`, `llm_grader`), se listan aquí para que el vocabulario
# viva en un solo módulo.
MOTIVO_CITA_AMBIGUA = "cita_ambigua"
MOTIVO_GRADING_NO_PARSEABLE = "grading_no_parseable"
MOTIVO_CANDIDATO_AUSENTE = "candidato_ausente_del_grading"

# Qué tipo de evidencia aporta cada origen. El disparador de conflicto necesita
# distinguirlos: "el manual cita el artículo" y "el artículo se parece a la sección" son
# dos afirmaciones independientes, y que se contradigan es justamente la señal.
ORIGENES_LEXICOS = (ORIGEN_LEXICO, ORIGEN_LEXICO_AMBIGUO)
ORIGENES_SEMANTICOS = (ORIGEN_SEMANTICO_V1, ORIGEN_SEMANTICO_V2)

_PRECEDENCIA = {
    ORIGEN_LEXICO: 4,
    ORIGEN_SEMANTICO_V1: 3,
    ORIGEN_SEMANTICO_V2: 3,
    ORIGEN_LEXICO_AMBIGUO: 2,
    ORIGEN_MANUAL: 5,     # una decisión humana manda sobre cualquier heurística
}


@dataclass(frozen=True)
class CoverageLink:
    """Una arista entre un artículo de la normativa y una sección del manual.

    `frozen` a propósito: una arista es un hecho observado, no un objeto mutable. Fusionar
    dos observaciones de la misma pareja produce una arista **nueva** (ver
    `LinkTable.upsert`), lo que deja el historial de fusiones auditable en vez de
    sobrescribir en el sitio.
    """

    # §3.3.1 — nace con workspace_id aunque en Fase 1 siempre valga "local". Añadirlo
    # ahora es un campo; retro-fitearlo cuando ya haya resultados, Excel generados y un
    # esquema publicado en la API es de lo más caro que queda por delante.
    workspace_id: str = "local"

    articulo_element_id: str = ""
    articulo_doc_id: str = ""
    articulo_numero: str = ""

    seccion_chunk_id: str = ""
    seccion_doc_id: str = ""
    seccion_jerarquia: str = ""

    origen: str = ORIGEN_SEMANTICO_V1
    # Orígenes acumulados: una pareja puede aparecer por vía léxica Y semántica, y saber
    # que coinciden es evidencia más fuerte que cualquiera por separado.
    origenes: tuple[str, ...] = ()

    score_semantico: float | None = None
    score_reranker: float | None = None
    score_grade: float | None = None

    # None = el grading no pudo determinarlo (ítem 4). NO es lo mismo que False, y
    # confundirlos es exactamente lo que colaba falsos positivos de cumplimiento.
    relevante: bool | None = None
    razon: str = ""

    # Veredicto de cumplimiento de la pareja, cuando el análisis comparativo lo produjo
    # (`llm_grader.ComparisonResult`). Vive en la arista y no solo en la fila del Excel
    # porque el disparador "parcial con brechas declaradas" del ítem 10 se evalúa aquí.
    nivel_cumplimiento: str | None = None
    analisis_general: str = ""
    brechas: tuple[str, ...] = ()

    # Veredicto de la Vía 2 (`llm_grader.AdopcionResult.nivel_adopcion`): cubierto /
    # parcial / no_cubierto / no_aplica. Vocabulario distinto de `nivel_cumplimiento`
    # (que es de la Vía 1, cumple/parcial/omision/no_aplica) — no son el mismo campo
    # con otro nombre, son dos preguntas distintas (§ docstring de dual.py), así que
    # cada una necesita su propio campo en vez de forzarlas al mismo.
    nivel_adopcion: str | None = None

    # Ítem 10. `requiere_revision_manual` no es "el análisis falló": es "el análisis no
    # alcanza para cerrar el veredicto y tiene que mirarlo una persona". La herramienta
    # marca y explica; no intenta resolverlo sola (Bloque A).
    #
    # Dos campos para un solo hecho, a propósito: el nombre corto es el que escriben los
    # productores anteriores al ítem 10 (`dual`, `llm_grader`, checkpoints en parquet) y
    # el largo el que dice qué significa. Renombrar de golpe rompería los checkpoints ya
    # pagados en horas de LLM, así que conviven y `__post_init__` los mantiene idénticos:
    # marcar cualquiera de los dos marca la arista.
    requiere_revision: bool = False
    requiere_revision_manual: bool = False
    motivos_revision: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        # `object.__setattr__` porque la dataclass es `frozen`; sincronizar aquí es lo que
        # permite que ninguna vista tenga que preguntarse cuál de los dos nombres miró.
        marcada = bool(self.requiere_revision) or bool(self.requiere_revision_manual)
        object.__setattr__(self, "requiere_revision", marcada)
        object.__setattr__(self, "requiere_revision_manual", marcada)

    @property
    def clave(self) -> tuple[str, str, str]:
        """Identidad de la arista. Incluye `workspace_id`: dos espacios de trabajo pueden
        analizar los mismos documentos sin que sus aristas se mezclen."""
        return (self.workspace_id, self.articulo_element_id, self.seccion_chunk_id)

    @property
    def confianza(self) -> float:
        """Score único para ordenar. El reranker manda sobre el semántico crudo."""
        for s in (self.score_grade, self.score_reranker, self.score_semantico):
            if s is not None:
                return float(s)
        return 0.0

    # ── Disparadores de revisión manual (ítem 10) ─────────────────────────

    @property
    def evidencia_lexica(self) -> bool:
        """¿Alguna observación de esta pareja vino de una cita explícita?

        Mira `origen` **y** `origenes`: una arista recién construida por `dual` todavía no
        pasó por `LinkTable.upsert`, que es quien puebla la tupla acumulada.
        """
        return bool(self._origenes_todos & set(ORIGENES_LEXICOS))

    @property
    def evidencia_semantica(self) -> bool:
        return bool(self._origenes_todos & set(ORIGENES_SEMANTICOS))

    @property
    def _origenes_todos(self) -> set[str]:
        return set(self.origenes) | {self.origen}

    def motivos_de_revision(
        self,
        delta_indecision: float = DELTA_INDECISION,
        min_score: float | None = None,
    ) -> tuple[str, ...]:
        """Los motivos que **el estado de esta arista** dispara, sin mirar los ya escritos.

        Puro y sin efectos: devuelve lo que se deduce de los campos. Quien quiera la arista
        marcada usa `evaluar_revision_manual`, que une esto con los motivos que ya venían
        de aguas arriba (`cita_ambigua`, `grading_no_parseable`, …).

        `MOTIVO_ARTICULO_SIN_COBERTURA` no aparece aquí a propósito: no es una propiedad de
        ninguna arista, sino la ausencia de todas ellas para un artículo. Lo evalúa
        `vista_normativa`, que es quien ve el artículo entero.
        """
        umbral = MIN_SEMANTIC_SCORE if min_score is None else float(min_score)
        motivos: list[str] = []

        # 1 · Banda de indecisión. El umbral no es una frontera real: dos candidatos a
        # 0.299 y 0.301 no se distinguen en nada salvo en de qué lado del corte cayeron.
        if self.score_semantico is not None:
            delta = abs(float(delta_indecision))
            if umbral - delta <= float(self.score_semantico) <= umbral + delta:
                motivos.append(MOTIVO_BANDA_INDECISION)

        # 2 · Veredicto indeterminado (ítem 4). `is None`, nunca falsy: False es un juicio
        # y None es la ausencia de juicio, y tratarlos igual es lo que colaba falsos
        # positivos de cumplimiento.
        if self.relevante is None:
            motivos.append(MOTIVO_VEREDICTO_INDETERMINADO)

        # 3 · Conflicto entre las dos evidencias.
        #   · El manual cita el artículo y el grading dice que no le aplica: una de las dos
        #     lecturas está mal y ninguna heurística puede decir cuál.
        #   · El recíproco literal —relevancia semántica sin cita léxica— es el caso normal
        #     y marcarlo entero dejaría el flag inservible. Se acota a cuando la evidencia
        #     que debería sostener esa relevancia tampoco la sostiene: el score quedó por
        #     debajo del umbral y aun así el veredicto afirma que sí aplica.
        if self.evidencia_lexica and self.relevante is False:
            motivos.append(MOTIVO_CONFLICTO_LEXICO_SEMANTICO)
        elif (
            self.evidencia_semantica
            and not self.evidencia_lexica
            and self.relevante is True
            and self.score_semantico is not None
            and float(self.score_semantico) < umbral
        ):
            motivos.append(MOTIVO_CONFLICTO_LEXICO_SEMANTICO)

        # 4 · Cumplimiento parcial con brechas declaradas. "Parcial" sin brechas es un
        # veredicto cerrado; con brechas, el modelo ya dijo qué le falta y quién decide si
        # eso basta es el auditor, no la herramienta.
        if self.nivel_cumplimiento == "parcial" and len(self.brechas) > 0:
            motivos.append(MOTIVO_PARCIAL_CON_BRECHAS)

        return tuple(motivos)

    def evaluada(
        self,
        delta_indecision: float = DELTA_INDECISION,
        min_score: float | None = None,
    ) -> CoverageLink:
        """Copia de esta arista con los disparadores del ítem 10 aplicados.

        Idempotente y aditiva: los motivos previos se conservan (los produjeron `dual` y
        `llm_grader`, que ven cosas que la arista ya no recuerda) y una arista marcada a
        mano no se desmarca porque ningún disparador automático la reconozca.
        """
        motivos = set(self.motivos_revision) | set(
            self.motivos_de_revision(delta_indecision, min_score)
        )
        marcada = bool(motivos) or self.requiere_revision_manual
        return replace(
            self,
            requiere_revision=marcada,
            requiere_revision_manual=marcada,
            motivos_revision=tuple(sorted(motivos)),
        )


class LinkTable:
    """Conjunto de aristas, con deduplicación por pareja.

    Las dos vías del ítem 6 recorren el mismo grafo en sentidos opuestos y llegan a las
    mismas parejas por caminos distintos. Sin dedupe, un artículo cubierto por una sección
    aparecería dos veces y la cobertura saldría inflada.
    """

    def __init__(self, links: Iterable[CoverageLink] = ()) -> None:
        self._por_clave: dict[tuple[str, str, str], CoverageLink] = {}
        for enlace in links:
            self.upsert(enlace)

    def __len__(self) -> int:
        return len(self._por_clave)

    def __iter__(self) -> Iterator[CoverageLink]:
        return iter(self._por_clave.values())

    def upsert(self, nuevo: CoverageLink) -> CoverageLink:
        """Añade o fusiona una arista.

        Al fusionar se conserva **lo mejor de cada observación**, no la última: el score
        más alto de cada tipo, la unión de orígenes, y el veredicto de mayor precedencia.
        Quedarse con la última haría que el resultado dependiera del orden en que se
        ejecutaron las vías, que es exactamente la clase de no-determinismo que un papel
        de trabajo no puede tener.
        """
        actual = self._por_clave.get(nuevo.clave)
        if actual is None:
            fusionado = replace(
                nuevo,
                origenes=tuple(sorted(set(nuevo.origenes) | {nuevo.origen})),
            )
            self._por_clave[nuevo.clave] = fusionado
            return fusionado

        origenes = tuple(sorted(
            set(actual.origenes) | set(nuevo.origenes) | {actual.origen, nuevo.origen}
        ))
        gana_nuevo = _PRECEDENCIA.get(nuevo.origen, 0) > _PRECEDENCIA.get(actual.origen, 0)

        fusionado = replace(
            actual,
            origen=nuevo.origen if gana_nuevo else actual.origen,
            origenes=origenes,
            score_semantico=_mejor(actual.score_semantico, nuevo.score_semantico),
            score_reranker=_mejor(actual.score_reranker, nuevo.score_reranker),
            score_grade=_mejor(actual.score_grade, nuevo.score_grade),
            # Un veredicto determinado gana a uno indeterminado, venga de donde venga:
            # que una vía no pudiera decidir no borra que la otra sí pudo.
            relevante=actual.relevante if actual.relevante is not None else nuevo.relevante,
            razon=nuevo.razon if gana_nuevo and nuevo.razon else actual.razon,
            nivel_cumplimiento=(
                nuevo.nivel_cumplimiento if gana_nuevo and nuevo.nivel_cumplimiento
                else actual.nivel_cumplimiento or nuevo.nivel_cumplimiento
            ),
            analisis_general=(
                nuevo.analisis_general if gana_nuevo and nuevo.analisis_general
                else actual.analisis_general or nuevo.analisis_general
            ),
            nivel_adopcion=(
                nuevo.nivel_adopcion if gana_nuevo and nuevo.nivel_adopcion
                else actual.nivel_adopcion or nuevo.nivel_adopcion
            ),
            brechas=tuple(sorted(set(actual.brechas) | set(nuevo.brechas))),
            # La marca de revisión se une, no se sobrescribe: que una vía no viera motivo
            # para revisar no borra el que sí encontró la otra. Basta con unir un alias
            # —`__post_init__` propaga al otro—, pero se pasan los dos para que un
            # `replace` no arrastre el valor viejo del que se omitiera.
            requiere_revision=(
                actual.requiere_revision or nuevo.requiere_revision
            ),
            requiere_revision_manual=(
                actual.requiere_revision_manual or nuevo.requiere_revision_manual
            ),
            motivos_revision=tuple(sorted(
                set(actual.motivos_revision) | set(nuevo.motivos_revision)
            )),
        )
        self._por_clave[nuevo.clave] = fusionado
        return fusionado

    def extend(self, links: Iterable[CoverageLink]) -> LinkTable:
        for enlace in links:
            self.upsert(enlace)
        return self

    # ── consulta ──────────────────────────────────────────────────────────

    def por_articulo(self, element_id: str) -> list[CoverageLink]:
        """Secciones que cubren un artículo. Es la consulta que antes exigía re-correr todo."""
        return [x for x in self if x.articulo_element_id == element_id]

    def por_seccion(self, chunk_id: str) -> list[CoverageLink]:
        return [x for x in self if x.seccion_chunk_id == chunk_id]

    def relevantes(self) -> list[CoverageLink]:
        """Solo las confirmadas. `is True`, no truthiness: `None` es indeterminado."""
        return [x for x in self if x.relevante is True]

    def para_revision(self) -> list[CoverageLink]:
        """Las aristas marcadas — lo que alimenta el filtro "Solo revisión manual" y la
        hoja dedicada del papel de trabajo (ítem 9)."""
        return [x for x in self if x.requiere_revision_manual]

    def evaluar_revision_manual(
        self,
        delta_indecision: float = DELTA_INDECISION,
        min_score: float | None = None,
    ) -> LinkTable:
        """Aplica los disparadores del ítem 10 a todas las aristas. Devuelve `self`.

        Se corre una vez, al final del pipeline y no dentro de `upsert`: los disparadores
        miran el estado *consolidado* de la pareja (orígenes de las dos vías, veredicto,
        brechas), y evaluarlos a mitad de la fusión marcaría aristas por evidencia que la
        otra vía todavía no había aportado.
        """
        for clave, enlace in list(self._por_clave.items()):
            self._por_clave[clave] = enlace.evaluada(delta_indecision, min_score)
        return self

    # ── persistencia ──────────────────────────────────────────────────────

    def to_dataframe(self) -> pd.DataFrame:
        if not self._por_clave:
            return pd.DataFrame(columns=[f.name for f in CoverageLink.__dataclass_fields__.values()])
        filas = []
        for x in self:
            d = asdict(x)
            # Las tuplas no sobreviven a parquet de forma legible; se aplanan a texto y
            # se reconstruyen al cargar.
            d["origenes"] = "|".join(x.origenes)
            d["motivos_revision"] = "|".join(x.motivos_revision)
            d["brechas"] = "|".join(x.brechas)
            filas.append(d)
        return pd.DataFrame(filas)

    def save(self, path: Path | str) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.to_dataframe().to_parquet(path)
        return path

    @classmethod
    def load(cls, path: Path | str) -> LinkTable:
        df = pd.read_parquet(Path(path))
        tabla = cls()
        for d in df.to_dict("records"):
            for campo in ("origenes", "motivos_revision", "brechas"):
                d[campo] = tuple(x for x in str(d.get(campo, "")).split("|") if x)
            # Compatibilidad hacia atrás: los checkpoints anteriores al ítem 10 traen solo
            # la columna con el nombre corto, y los intermedios solo la larga. Un parquet
            # viejo tiene que seguir cargando — es trabajo ya pagado en horas de LLM.
            marcada = any(
                bool(d[campo])
                for campo in ("requiere_revision", "requiere_revision_manual")
                if d.get(campo) is not None and not pd.isna(d[campo])
            )
            d["requiere_revision"] = marcada
            d["requiere_revision_manual"] = marcada
            d = {k: v for k, v in d.items() if k in CoverageLink.__dataclass_fields__}
            for campo in ("score_semantico", "score_reranker", "score_grade"):
                if d.get(campo) is not None and pd.isna(d[campo]):
                    d[campo] = None
            if d.get("relevante") is not None and pd.isna(d["relevante"]):
                d["relevante"] = None
            tabla._por_clave[
                (d["workspace_id"], d["articulo_element_id"], d["seccion_chunk_id"])
            ] = CoverageLink(**d)
        return tabla


def _mejor(a: float | None, b: float | None) -> float | None:
    if a is None:
        return b
    if b is None:
        return a
    return max(a, b)


def evaluar_revision_manual(
    link: CoverageLink | Iterable[CoverageLink],
    delta_indecision: float = DELTA_INDECISION,
    min_score: float | None = None,
) -> CoverageLink | list[CoverageLink]:
    """Marca una arista —o una lista de ellas— con los disparadores del ítem 10.

    Punto de entrada público del ítem: acepta lo uno o lo otro porque los tres sitios que
    lo llaman traen formas distintas (una arista suelta al editarla desde la interfaz, la
    lista que devuelve una vía, la tabla entera al cerrar la corrida) y no tiene sentido
    que cada uno recuerde qué envoltorio le toca. Para la tabla completa está
    `LinkTable.evaluar_revision_manual`, que además reindexa por clave.

    Devuelve objetos nuevos: `CoverageLink` es `frozen` y las aristas de entrada quedan
    intactas.
    """
    if isinstance(link, CoverageLink):
        return link.evaluada(delta_indecision, min_score)
    return [x.evaluada(delta_indecision, min_score) for x in link]


# ── Agregaciones ──────────────────────────────────────────────────────────────

def vista_manual(
    tabla: LinkTable,
    manual_df: pd.DataFrame,
    analisis_por_seccion: dict[str, dict] | None = None,
) -> pd.DataFrame:
    """Una fila por sección del manual — la Vía 1 del ítem 6.

    Incluye las secciones **sin ninguna arista**: son las que no encontraron norma
    aplicable, y omitirlas las volvería invisibles justo cuando hay que decidir si es una
    omisión del manual o una sección que genuinamente no tiene norma que le aplique.

    `analisis_por_seccion` (opcional, `{chunk_id: {"nivel_cumplimiento", "analisis_general",
    "brechas"}}`) es el respaldo para exactamente ese caso: una sección sin aristas no
    tiene de dónde leer `nivel_cumplimiento`/`analisis_general` (viven en `CoverageLink`,
    y sin aristas no hay ningún link del que leerlos), pero `analyze_comparison()` sí
    corrió para ella —incluida la ["ninguna" → "no hay normas relacionadas, ¿es
    omisión?"](../src/llm_grader.py) que es precisamente el caso que este parámetro
    cubre. Con aristas, se usa la primera (todas cargan el mismo veredicto de sección,
    ver `dual._links_desde_via1`).
    """
    analisis_por_seccion = analisis_por_seccion or {}
    filas = []
    for _, seccion in manual_df.iterrows():
        chunk_id = seccion.get("chunk_id", "")
        enlaces = tabla.por_seccion(chunk_id)
        confirmados = [e for e in enlaces if e.relevante is True]
        revisar = any(e.requiere_revision_manual for e in enlaces)

        if enlaces:
            nivel_cumplimiento = enlaces[0].nivel_cumplimiento
            analisis_general = enlaces[0].analisis_general
            brechas = sorted({b for e in enlaces for b in e.brechas})
        else:
            respaldo = analisis_por_seccion.get(chunk_id, {})
            nivel_cumplimiento = respaldo.get("nivel_cumplimiento")
            analisis_general = respaldo.get("analisis_general", "")
            brechas = list(respaldo.get("brechas", ()))

        filas.append({
            "chunk_id": chunk_id,
            "seccion_doc_id": seccion.get("doc_id", ""),
            "jerarquia": seccion.get("jerarquia", ""),
            "titulo_seccion": seccion.get("titulo_seccion", ""),
            "n_articulos_relacionados": len(enlaces),
            "n_articulos_confirmados": len(confirmados),
            "articulos": [e.articulo_numero for e in confirmados],
            "normativas": sorted({e.articulo_doc_id for e in confirmados}),
            "origenes": sorted({o for e in enlaces for o in e.origenes}),
            "nivel_cumplimiento": nivel_cumplimiento,
            "analisis_general": analisis_general,
            "brechas": brechas,
            # Las dos columnas dicen lo mismo: el consumidor (Excel, API, interfaz) puede
            # haberse escrito contra cualquiera de los dos nombres.
            "requiere_revision": revisar,
            "requiere_revision_manual": revisar,
            "motivos_revision": sorted({m for e in enlaces for m in e.motivos_revision}),
        })
    return pd.DataFrame(filas)


def vista_normativa(tabla: LinkTable, normativa_df: pd.DataFrame,
                    incluir_referencias: bool = False) -> pd.DataFrame:
    """Una fila por artículo — la Vía 2 del ítem 6.

    Por defecto excluye los artículos marcados `es_referencia`: son citas a otras normas
    dentro del preámbulo, no obligaciones sustantivas. Contarlos como "sin cobertura"
    inflaría la brecha con artículos que nadie tiene que cumplir.
    """
    df = normativa_df
    if "tipo_elemento" in df.columns:
        df = df[df["tipo_elemento"] == "articulo"]
    if not incluir_referencias and "es_referencia" in df.columns:
        df = df[~df["es_referencia"].astype(bool)]

    filas = []
    for _, art in df.iterrows():
        element_id = art.get("element_id", "")
        enlaces = tabla.por_articulo(element_id)
        confirmados = [e for e in enlaces if e.relevante is True]
        # Un artículo sin cobertura confirmada se revisa siempre: no tener candidatos
        # —o tenerlos y que ninguno resultara relevante— no es haber comprobado que no le
        # aplica nada. Es el disparador `articulo_sin_cobertura` del ítem 10, y la
        # condición tiene que ser la misma que la del motivo de abajo: un artículo que
        # listara el motivo sin quedar marcado no aparecería en el filtro "Solo revisión
        # manual", que es donde alguien iría a buscarlo.
        revisar = any(e.requiere_revision_manual for e in enlaces) or not confirmados
        # `nivel_adopcion` (cubierto/parcial/no_cubierto/no_aplica, de
        # `AdopcionResult`) es el veredicto real del ítem 6; antes esta vista solo
        # exponía el booleano `cubierto`, que colapsaba "parcial" en uno de los dos
        # extremos sin que el papel de trabajo (ítem 9) pudiera distinguirlo. Se toma
        # de la primera arista que lo traiga: todas las de un mismo artículo cargan el
        # mismo veredicto (`dual._links_desde_via2`). Un artículo sin ninguna sección
        # candidata no genera aristas (`_links_desde_via2` itera sobre `secciones`,
        # vacía en ese caso) pero `analizar_adopcion()` sí devuelve "no_cubierto" sin
        # consultar al modelo — el default de abajo reproduce esa misma conclusión en
        # vez de dejarlo en blanco.
        nivel_adopcion = next(
            (e.nivel_adopcion for e in enlaces if e.nivel_adopcion),
            None if confirmados else "no_cubierto",
        )
        filas.append({
            "element_id": element_id,
            "articulo_doc_id": art.get("doc_id", ""),
            "numero": art.get("numero", ""),
            "encabezado": art.get("encabezado", ""),
            "n_secciones_relacionadas": len(enlaces),
            "n_secciones_confirmadas": len(confirmados),
            "secciones_que_lo_cubren": [e.seccion_jerarquia for e in confirmados],
            "cubierto": bool(confirmados),
            "nivel_adopcion": nivel_adopcion,
            "origenes": sorted({o for e in enlaces for o in e.origenes}),
            "requiere_revision": revisar,
            "requiere_revision_manual": revisar,
            "motivos_revision": sorted(
                {m for e in enlaces for m in e.motivos_revision}
                | ({MOTIVO_ARTICULO_SIN_COBERTURA} if not confirmados else set())
            ),
        })
    return pd.DataFrame(filas)


@dataclass(frozen=True)
class Cobertura:
    """Resultado del cálculo de cobertura — la premisa no negociable del Bloque A."""

    total_articulos: int
    cubiertos: int
    sin_cobertura: list[dict] = field(default_factory=list)

    @property
    def porcentaje(self) -> float:
        return self.cubiertos / self.total_articulos if self.total_articulos else 0.0

    @property
    def completa(self) -> bool:
        return self.total_articulos > 0 and self.cubiertos == self.total_articulos

    def como_dict(self) -> dict:
        return {
            "version_esquema": VERSION_ESQUEMA,
            "total_articulos": self.total_articulos,
            "cubiertos": self.cubiertos,
            "porcentaje": round(self.porcentaje, 4),
            "completa": self.completa,
            "sin_cobertura": self.sin_cobertura,
        }

    def guardar(self, path: Path | str) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.como_dict(), ensure_ascii=False, indent=2),
                        encoding="utf-8")
        return path


def cobertura_global(tabla: LinkTable, normativa_df: pd.DataFrame,
                     incluir_referencias: bool = False) -> Cobertura:
    """% de artículos cubiertos y cuáles no lo están.

    Se calcula sobre la misma `vista_normativa` que ve el auditor, no por separado: dos
    cálculos independientes podrían discrepar, y un porcentaje que no cuadre con la tabla
    de abajo destruye la confianza en el papel de trabajo entero.
    """
    vista = vista_normativa(tabla, normativa_df, incluir_referencias)
    if vista.empty:
        return Cobertura(total_articulos=0, cubiertos=0)

    sin = vista[~vista["cubierto"]]
    return Cobertura(
        total_articulos=len(vista),
        cubiertos=int(vista["cubierto"].sum()),
        sin_cobertura=[
            {"element_id": r["element_id"], "doc_id": r["articulo_doc_id"],
             "numero": r["numero"], "encabezado": r["encabezado"]}
            for _, r in sin.iterrows()
        ],
    )

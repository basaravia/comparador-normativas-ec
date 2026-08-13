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

logger = logging.getLogger(__name__)

VERSION_ESQUEMA = 1

# Origen de una arista, de mayor a menor evidencia.
ORIGEN_LEXICO = "lexico"              # el manual cita el artículo por número, sin ambigüedad
ORIGEN_LEXICO_AMBIGUO = "lexico_ambiguo"   # cita un número que existe en varias normativas
ORIGEN_SEMANTICO_V1 = "semantico_v1"  # recuperado desde la sección (Vía 1)
ORIGEN_SEMANTICO_V2 = "semantico_v2"  # recuperado desde el artículo (Vía 2)
ORIGEN_MANUAL = "manual"              # añadido por una persona

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

    requiere_revision: bool = False
    motivos_revision: tuple[str, ...] = ()

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
            requiere_revision=actual.requiere_revision or nuevo.requiere_revision,
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
            d["origenes"] = tuple(x for x in str(d.get("origenes", "")).split("|") if x)
            d["motivos_revision"] = tuple(
                x for x in str(d.get("motivos_revision", "")).split("|") if x
            )
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


# ── Agregaciones ──────────────────────────────────────────────────────────────

def vista_manual(tabla: LinkTable, manual_df: pd.DataFrame) -> pd.DataFrame:
    """Una fila por sección del manual — la Vía 1 del ítem 6.

    Incluye las secciones **sin ninguna arista**: son las que no encontraron norma
    aplicable, y omitirlas las volvería invisibles justo cuando hay que decidir si es una
    omisión del manual o una sección que genuinamente no tiene norma que le aplique.
    """
    filas = []
    for _, seccion in manual_df.iterrows():
        chunk_id = seccion.get("chunk_id", "")
        enlaces = tabla.por_seccion(chunk_id)
        confirmados = [e for e in enlaces if e.relevante is True]
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
            "requiere_revision": any(e.requiere_revision for e in enlaces),
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
        filas.append({
            "element_id": element_id,
            "articulo_doc_id": art.get("doc_id", ""),
            "numero": art.get("numero", ""),
            "encabezado": art.get("encabezado", ""),
            "n_secciones_relacionadas": len(enlaces),
            "n_secciones_confirmadas": len(confirmados),
            "secciones_que_lo_cubren": [e.seccion_jerarquia for e in confirmados],
            "cubierto": bool(confirmados),
            "origenes": sorted({o for e in enlaces for o in e.origenes}),
            "requiere_revision": any(e.requiere_revision for e in enlaces) or not enlaces,
            "motivos_revision": sorted(
                {m for e in enlaces for m in e.motivos_revision}
                | ({"articulo_sin_cobertura"} if not confirmados else set())
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

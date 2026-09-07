"""Análisis en doble vía (ítem 6) — el corazón del informe.

Dos recorridos del mismo grafo, en sentidos opuestos:

  **Vía 1 · manual → normativa.** Por cada sección en alcance, ¿qué artículos le aplican y
  los cumple? Unidad de resultado: la sección. Es la evolución de lo que ya existía.

  **Vía 2 · normativa → manual.** Por cada artículo en alcance, ¿lo cubre alguna sección?
  Unidad de resultado: el artículo. Es nueva, y es la que verifica la premisa no negociable
  del Bloque A: el 100 % de la normativa debe quedar cubierto por algún control.

**Por qué las dos y no una.** La Vía 1 sola no puede detectar un artículo huérfano: si
ninguna sección lo recupera, simplemente no aparece — y un artículo que nadie analizó es
indistinguible de uno que no existe. La brecha se ve desde el otro lado.

**Caché de grading compartida (supuesto S3).** Las dos vías evalúan las mismas parejas
(artículo, sección) por caminos distintos. Sin caché, el coste sería
`|secciones| × candidatos + |artículos| × candidatos`; con ella, cada pareja se gradúa una
sola vez. En un corpus real eso es la diferencia entre una corrida y dos.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Optional

import pandas as pd

from .coverage import (
    ORIGEN_LEXICO,
    ORIGEN_LEXICO_AMBIGUO,
    ORIGEN_SEMANTICO_V1,
    ORIGEN_SEMANTICO_V2,
    MOTIVO_CITA_AMBIGUA,
    Cobertura,
    CoverageLink,
    LinkTable,
    cobertura_global,
    vista_manual,
    vista_normativa,
)

logger = logging.getLogger(__name__)


@dataclass
class CacheGrading:
    """Veredictos por pareja (artículo, sección), compartidos entre vías.

    Lleva contadores porque el DoD del ítem exige verificar que el número de llamadas al
    LLM sea `|secciones| + |artículos|` y no el producto — una afirmación que sin medirla
    es solo una intención.
    """

    _veredictos: dict[tuple[str, str], dict] = field(default_factory=dict)
    aciertos: int = 0
    fallos: int = 0

    def obtener(self, articulo_id: str, seccion_id: str) -> dict | None:
        v = self._veredictos.get((articulo_id, seccion_id))
        if v is None:
            self.fallos += 1
        else:
            self.aciertos += 1
        return v

    def guardar(self, articulo_id: str, seccion_id: str, veredicto: dict) -> None:
        self._veredictos.setdefault((articulo_id, seccion_id), veredicto)

    @property
    def tamano(self) -> int:
        return len(self._veredictos)


@dataclass
class ComparisonBundle:
    """Resultado completo de una corrida en doble vía."""

    links: LinkTable
    vista_manual: pd.DataFrame
    vista_normativa: pd.DataFrame
    cobertura: Cobertura
    metadatos: dict = field(default_factory=dict)

    @property
    def alerta_cobertura(self) -> str | None:
        """Mensaje si la cobertura es incompleta. `None` si está al 100 %.

        Es la premisa del Bloque A hecha texto: si algún artículo queda sin cubrir, el
        papel de trabajo tiene que decirlo de forma que no se pueda pasar por alto.
        """
        if self.cobertura.completa or self.cobertura.total_articulos == 0:
            return None
        faltan = len(self.cobertura.sin_cobertura)
        return (
            f"{faltan} de {self.cobertura.total_articulos} artículos no están cubiertos "
            f"por ninguna sección del manual ({self.cobertura.porcentaje:.1%} de cobertura)."
        )


def _links_desde_via1(
    seccion: dict,
    lexicos: list[dict],
    graduados: list[dict],
    workspace_id: str,
) -> list[CoverageLink]:
    """Aristas que produce analizar una sección."""
    enlaces = []
    chunk_id = str(seccion.get("chunk_id", ""))
    jerarquia = str(seccion.get("jerarquia", ""))
    doc_seccion = str(seccion.get("doc_id", ""))

    for m in lexicos:
        ambiguo = m.get("match_type") == "ambiguo"
        enlaces.append(CoverageLink(
            workspace_id=workspace_id,
            articulo_element_id=str(m.get("element_id", "")),
            articulo_doc_id=str(m.get("doc_id", "")),
            articulo_numero=str(m.get("numero", "")),
            seccion_chunk_id=chunk_id,
            seccion_doc_id=doc_seccion,
            seccion_jerarquia=jerarquia,
            origen=ORIGEN_LEXICO_AMBIGUO if ambiguo else ORIGEN_LEXICO,
            score_semantico=m.get("similarity"),
            # Una cita ambigua no afirma relevancia: la deja indeterminada y la marca.
            relevante=None if ambiguo else True,
            razon=m.get("razon_match", "") or "cita explícita del artículo",
            requiere_revision=ambiguo,
            motivos_revision=(MOTIVO_CITA_AMBIGUA,) if ambiguo else (),
        ))

    for c in graduados:
        enlaces.append(CoverageLink(
            workspace_id=workspace_id,
            articulo_element_id=str(c.get("element_id", "")),
            articulo_doc_id=str(c.get("doc_id", "")),
            articulo_numero=str(c.get("numero", "")),
            seccion_chunk_id=chunk_id,
            seccion_doc_id=doc_seccion,
            seccion_jerarquia=jerarquia,
            origen=ORIGEN_SEMANTICO_V1,
            score_semantico=c.get("similarity"),
            score_reranker=c.get("reranker_score"),
            score_grade=c.get("score_grade"),
            relevante=c.get("relevante"),
            razon=c.get("razon_grade", ""),
            requiere_revision=bool(c.get("requiere_revision")),
            motivos_revision=(
                (c.get("motivo_revision"),) if c.get("motivo_revision") else ()
            ),
        ))
    return enlaces


def _links_desde_via2(
    articulo: dict,
    secciones: list[dict],
    veredicto,
    workspace_id: str,
) -> list[CoverageLink]:
    """Aristas que produce analizar un artículo."""
    relevantes = set(getattr(veredicto, "secciones_relevantes", []) or [])
    cubierto = getattr(veredicto, "nivel_adopcion", "") in ("cubierto", "parcial")

    return [
        CoverageLink(
            workspace_id=workspace_id,
            articulo_element_id=str(articulo.get("element_id", "")),
            articulo_doc_id=str(articulo.get("doc_id", "")),
            articulo_numero=str(articulo.get("numero", "")),
            seccion_chunk_id=str(s.get("chunk_id", "")),
            seccion_doc_id=str(s.get("doc_id", "")),
            seccion_jerarquia=str(s.get("jerarquia", "")),
            origen=ORIGEN_SEMANTICO_V2,
            score_semantico=s.get("similarity"),
            # Solo se afirma la arista si el modelo nombró esa sección, o si el veredicto
            # global es de cobertura. Marcar todas las candidatas como relevantes
            # convertiría la recuperación en un veredicto, que es el error del ítem 4.
            relevante=True if (str(s.get("jerarquia", "")) in relevantes or cubierto) else None,
            razon=getattr(veredicto, "analisis_adopcion", "")[:200],
        )
        for s in secciones
    ]


def run_dual(
    *,
    comparador,
    manual_index,
    manual_df: pd.DataFrame,
    normativa_df: pd.DataFrame,
    workspace_id: str = "local",
    top_k: int = 5,
    min_score: float = 0.30,
    incluir_referencias: bool = False,
    progress_callback: Optional[Callable[[str, int, int], None]] = None,
) -> ComparisonBundle:
    """Ejecuta las dos vías y consolida sobre una única `LinkTable`.

    `progress_callback(via, hechas, total)` permite a la interfaz mostrar avance sin que
    este módulo sepa qué interfaz es.
    """
    tabla = LinkTable()
    cache = CacheGrading()
    grader = comparador.grader

    # ── Vía 1 · sección → artículos ───────────────────────────────────────
    secciones = manual_df.to_dict("records")
    for i, seccion in enumerate(secciones, 1):
        texto = seccion.get("texto", seccion.get("contenido", ""))
        embed_text = seccion.get("embed_text", texto)

        lexicos = comparador.index.lexical_scan(texto, normativa_df)
        candidatos = comparador.index.semantic_search(
            embed_text, top_k=top_k, min_score=min_score,
        )
        candidatos = comparador.index.rerank(embed_text, candidatos,
                                             top_n=comparador.top_n_rerank)

        graduados = grader.grade_candidates(texto, candidatos)
        for c in graduados:
            cache.guardar(str(c.get("element_id", "")), str(seccion.get("chunk_id", "")), c)

        tabla.extend(_links_desde_via1(seccion, lexicos, graduados, workspace_id))
        if progress_callback:
            progress_callback("via1", i, len(secciones))

    # ── Vía 2 · artículo → secciones ──────────────────────────────────────
    arts = normativa_df
    if "tipo_elemento" in arts.columns:
        arts = arts[arts["tipo_elemento"] == "articulo"]
    if not incluir_referencias and "es_referencia" in arts.columns:
        arts = arts[~arts["es_referencia"].astype(bool)]
    articulos = arts.to_dict("records")

    for i, articulo in enumerate(articulos, 1):
        embed_text = articulo.get("embed_text", articulo.get("contenido", ""))
        candidatas = manual_index.buscar_secciones(
            embed_text, top_k=top_k, min_score=min_score,
        )

        # La caché evita re-graduar parejas que la Vía 1 ya evaluó (S3). Lo que no se
        # cachea es el veredicto POR ARTÍCULO: es una pregunta distinta y solo la hace
        # esta vía, así que el coste total queda en |secciones| + |artículos|.
        for s in candidatas:
            cache.obtener(str(articulo.get("element_id", "")), str(s.get("chunk_id", "")))

        veredicto = grader.analizar_adopcion(articulo, candidatas)
        tabla.extend(_links_desde_via2(articulo, candidatas, veredicto, workspace_id))
        if progress_callback:
            progress_callback("via2", i, len(articulos))

    # Ítem 10 · una sola pasada, con la tabla ya consolidada: los disparadores miran el
    # estado final de cada pareja (orígenes de las dos vías, veredicto, brechas), no el
    # intermedio. `min_score` es el de esta corrida, no el default del módulo — la banda
    # de indecisión se define alrededor del umbral que realmente se usó.
    tabla.evaluar_revision_manual(min_score=min_score)

    cobertura = cobertura_global(tabla, normativa_df, incluir_referencias)
    bundle = ComparisonBundle(
        links=tabla,
        vista_manual=vista_manual(tabla, manual_df),
        vista_normativa=vista_normativa(tabla, normativa_df, incluir_referencias),
        cobertura=cobertura,
        metadatos={
            "workspace_id": workspace_id,
            "secciones_analizadas": len(secciones),
            "articulos_analizados": len(articulos),
            "aristas": len(tabla),
            "cache_aciertos": cache.aciertos,
            "cache_tamano": cache.tamano,
        },
    )
    logger.info(
        "Doble vía completa: %d secciones · %d artículos · %d aristas · cobertura %.1f%%",
        len(secciones), len(articulos), len(tabla), cobertura.porcentaje * 100,
    )
    return bundle

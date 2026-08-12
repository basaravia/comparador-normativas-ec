"""Dobles deterministas del pipeline: sin red, sin modelos, sin descargas.

El plan pide "un grader falso determinista" en cuatro ramas distintas (ítems 1, 4, 6 y 10).
Si cada una lo improvisa, las cuatro colisionan en `conftest.py` y ninguna puede afirmar
sobre el número de llamadas al LLM, que es justo el DoD del ítem 6.

Todos los dobles llevan **contador de invocaciones**: sin él no se puede verificar que la
caché de grading compartida entre vías funcione (supuesto S3), ni que el coste sea
`|secciones| + |artículos|` y no el producto.

Todos aceptan además un modo de **fallo programado**, porque la mitad de los ítems de la
Ola 1 tratan precisamente de qué ocurre cuando el modelo falla: no basta con un doble que
siempre responde bien.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

import numpy as np

from src.llm_grader import ComparisonResult


class FakeEmbeddingBackend:
    """Embeddings deterministas por hash del texto. Implementa `EmbeddingBackend`.

    No hereda de la clase abstracta a propósito: si la interfaz cambia, quiero que fallen
    las pruebas que *usan* el doble, no que el doble deje de instanciarse.
    """

    def __init__(self, dim: int = 32) -> None:
        self._dim = dim
        self.llamadas = 0
        self.textos_vistos: list[str] = []
        self.prefijos_vistos: list[str] = []

    def encode(self, texts: Sequence[str], prefix: str = "") -> np.ndarray:
        self.llamadas += 1
        self.textos_vistos.extend(texts)
        # El prefijo se registra porque el defecto 3 de §2.2 es justamente que se
        # anula: una prueba puede afirmar que llega "passage: " / "query: ".
        self.prefijos_vistos.append(prefix)

        vecs = []
        for t in texts:
            rng = np.random.default_rng(abs(hash(f"{prefix}{t}")) % (2**32))
            v = rng.standard_normal(self._dim).astype(np.float32)
            vecs.append(v / np.linalg.norm(v))
        return np.array(vecs, dtype=np.float32)

    @property
    def dim(self) -> int:
        return self._dim


@dataclass
class FakeIndex:
    """Índice falso: devuelve los candidatos que se le programen, sin FAISS.

    Se le pasa un `plan` que mapea el texto de una sección a los artículos que debe
    devolver, de modo que la prueba controle exactamente qué recupera el pipeline.
    """

    normativa_df: Any
    plan: dict[str, list[str]] = field(default_factory=dict)
    min_score_recibido: float | None = None
    llamadas_semantic: int = 0
    llamadas_rerank: int = 0
    llamadas_lexical: int = 0

    def semantic_search(self, query: str, top_k: int = 5, min_score: float = 0.30,
                        source_filter: str | None = None) -> list[dict]:
        self.llamadas_semantic += 1
        # Se guarda para poder afirmar que el umbral del sidebar llega hasta aquí
        # (defecto 1 de §2.2: hoy `_process_row` no lo pasa).
        self.min_score_recibido = min_score

        ids = self.plan.get(query, [])
        filas = self.normativa_df[self.normativa_df["element_id"].isin(ids)]
        return [
            {**r, "similarity": round(0.9 - 0.1 * i, 4), "rank_faiss": i + 1}
            for i, r in enumerate(filas.to_dict("records"))
        ][:top_k]

    def rerank(self, query: str, candidates: list[dict], top_n: int = 3) -> list[dict]:
        self.llamadas_rerank += 1
        return [{**c, "reranker_score": 1.0 - 0.1 * i, "rank": i + 1}
                for i, c in enumerate(candidates[:top_n])]

    def lexical_scan(self, text: str, normativa_df=None) -> list[dict]:
        self.llamadas_lexical += 1
        from src.search_engine import NormativaIndex
        # Delega en la implementación real: es la que las pruebas de aislamiento
        # entre normativas (defecto 2 de §2.2) tienen que ejercitar de verdad.
        return NormativaIndex.lexical_scan(self, text, normativa_df)  # type: ignore[arg-type]


class FakeGrader:
    """Grader determinista con contador y fallos programables.

    Parámetros:
        veredictos  : chunk_id o jerarquía de la sección -> nivel_cumplimiento
        relevancia  : element_id -> bool. Lo ausente se considera relevante.
        fallar_en   : callable(row) -> Exception | None. Permite simular caída del
                      modelo en una fila concreta (ítem 1) o fallo de parseo (ítem 4).
    """

    def __init__(
        self,
        veredictos: dict[str, str] | None = None,
        relevancia: dict[str, bool] | None = None,
        fallar_en: Callable[[dict], BaseException | None] | None = None,
    ) -> None:
        self.veredictos = veredictos or {}
        self.relevancia = relevancia or {}
        self.fallar_en = fallar_en

        self.llamadas_grade = 0
        self.llamadas_analyze = 0
        self.pares_graduados: list[tuple[str, str]] = []

    def grade_candidates(self, manual_text: str, candidates: list[dict]) -> list[dict]:
        self.llamadas_grade += 1
        salida = []
        for c in candidates:
            eid = c.get("element_id", c.get("chunk_id", ""))
            self.pares_graduados.append((manual_text[:40], eid))
            rel = self.relevancia.get(eid, True)
            salida.append({**c, "relevante": rel,
                           "score_grade": 0.9 if rel else 0.1,
                           "razon_grade": "doble determinista"})
        return salida

    def analyze_comparison(self, manual_row: dict, lexical_matches: list[dict],
                           validated_candidates: list[dict]) -> ComparisonResult:
        self.llamadas_analyze += 1

        if self.fallar_en is not None:
            exc = self.fallar_en(manual_row)
            if exc is not None:
                raise exc

        clave = manual_row.get("jerarquia") or manual_row.get("chunk_id", "")
        nivel = self.veredictos.get(clave, "cumple")
        tipo = "lexica" if lexical_matches else ("semantica" if validated_candidates else "ninguna")

        return ComparisonResult(
            tipo_coincidencia=tipo,
            nivel_cumplimiento=nivel,
            analisis_general=f"Análisis determinista para {clave}",
            brechas=["brecha de ejemplo"] if nivel == "parcial" else [],
        )


class FakeChatModel:
    """Chat model inyectable para el ítem P-a, donde `LLMGrader` deja de construir el suyo.

    Devuelve las respuestas de `respuestas` en orden; agotadas, repite la última. Con
    `excepcion` lanza en su lugar, para ejercitar la clasificación de errores de `errors.py`.
    """

    def __init__(self, respuestas: list[str] | None = None,
                 excepcion: BaseException | None = None) -> None:
        self.respuestas = respuestas or ["{}"]
        self.excepcion = excepcion
        self.llamadas = 0
        self.prompts: list[Any] = []

    def invoke(self, entrada: Any, **_kw: Any) -> Any:
        self.llamadas += 1
        self.prompts.append(entrada)
        if self.excepcion is not None:
            raise self.excepcion
        i = min(self.llamadas - 1, len(self.respuestas) - 1)

        from langchain_core.messages import AIMessage
        return AIMessage(content=self.respuestas[i])

    # LCEL encadena con `|`; basta con que el doble se deje componer.
    def __or__(self, otro: Any) -> Any:
        return otro.__ror__(self) if hasattr(otro, "__ror__") else NotImplemented

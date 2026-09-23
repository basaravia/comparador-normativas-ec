"""Fixtures compartidas de la suite: corpus sintético y dobles deterministas.

Se exponen aquí para que las ramas de las olas siguientes importen de un solo sitio y no
vuelvan a inventar su propio grader falso — que es lo que el plan pide evitar en la Ola 0.
"""
from .corpus import (
    COBERTURA_ESPERADA,
    DOC_LEY,
    DOC_MANUAL,
    DOC_RES,
    manual_df,
    normativa_df,
    normativa_ley,
    normativa_resolucion,
)
from .dobles import (
    FakeChatModel,
    FakeEmbeddingBackend,
    FakeGrader,
    FakeGraderDual,
    FakeIndex,
    FakeManualIndex,
)

__all__ = [
    "COBERTURA_ESPERADA",
    "DOC_LEY",
    "DOC_MANUAL",
    "DOC_RES",
    "manual_df",
    "normativa_df",
    "normativa_ley",
    "normativa_resolucion",
    "FakeChatModel",
    "FakeEmbeddingBackend",
    "FakeGrader",
    "FakeGraderDual",
    "FakeIndex",
    "FakeManualIndex",
]

"""Pruebas de cableado de configuración (`fix/config-wiring`, §2.2 del plan).

Defecto 1 — el umbral de score mínimo no llegaba a la corrida
---------------------------------------------------------------
`DocumentComparator.__init__` ni siquiera aceptaba `min_semantic_score`, y
`_process_row()` llamaba a `semantic_search()` sin pasar `min_score`, así que
la corrida siempre usaba el default de `config.py` (0.30) sin importar lo que
mostrara el slider del sidebar. `TestUmbralLlegaALaCorrida` afirma la fuga
con `FakeIndex.min_score_recibido` (que existe justo para esto);
`TestUmbralAlteraElNumeroDeCandidatosReales` prueba el efecto de punta a
punta con un índice FAISS real, para no quedarse solo en "se pasó el
parámetro" sino comprobar que el parámetro hace lo que promete: cambia
cuántos candidatos vuelven.

Defecto 3 — los prefijos del backend local se anulaban
---------------------------------------------------------
`NormativaIndex.build()`/`semantic_search()` forzaban `prefix=""` sin mirar
qué backend estaba activo, así que el backend local
(`SentenceTransformersEmbeddings`, modelo e5) nunca recibía los prefijos
`"passage: "`/`"query: "` que ese modelo necesita para rendir. El backend de
DMR, en cambio, no los quiere. `TestPrefijosDependenDelBackend` afirma con
`FakeEmbeddingBackend.prefijos_vistos` que el prefijo que llega a `encode()`
es el que el backend activo declara — ni forzado a vacío (como antes) ni
forzado a e5 (rompería DMR).
"""
from __future__ import annotations

import pytest

from src import config as cfg
from src.comparator import DocumentComparator
from src.embeddings import LangChainDMREmbeddings, SentenceTransformersEmbeddings
from src.search_engine import NormativaIndex
from tests.fixtures import FakeEmbeddingBackend, FakeGrader, FakeIndex


# ── Defecto 1: el umbral de score mínimo llega a la corrida ────────────────


class TestUmbralLlegaALaCorrida:
    def test_sin_argumento_explicito_el_comparator_usa_el_default_de_config(self, normativa_df, manual_df):
        indice = FakeIndex(normativa_df=normativa_df, plan={})
        comparator = DocumentComparator(normativa_index=indice, llm_grader=FakeGrader())

        assert comparator.min_semantic_score == cfg.MIN_SEMANTIC_SCORE, (
            "sin argumento explícito, DocumentComparator debe seguir siendo "
            "compatible con las llamadas existentes (master.ipynb) y usar el "
            "default de config.py"
        )

        comparator.run(manual_df.head(1), normativa_df, max_workers=1)
        assert indice.min_score_recibido == cfg.MIN_SEMANTIC_SCORE

    def test_umbral_configurado_en_el_constructor_llega_a_semantic_search(self, normativa_df, manual_df):
        indice = FakeIndex(normativa_df=normativa_df, plan={})
        comparator = DocumentComparator(
            normativa_index=indice, llm_grader=FakeGrader(), min_semantic_score=0.75
        )

        comparator.run(manual_df.head(1), normativa_df, max_workers=1)

        assert indice.min_score_recibido == 0.75, (
            "el umbral pasado al constructor debe llegar hasta "
            "index.semantic_search(min_score=...); antes de la corrección "
            "_process_row() no lo pasaba y siempre corría con el default de "
            "config.py (0.30), sin importar el valor del sidebar"
        )

    def test_cambiar_el_umbral_entre_corridas_cambia_lo_que_recibe_el_indice(self, normativa_df, manual_df):
        """DoD del plan: "cambiar el umbral altera el número de candidatos de
        una corrida (verificable con FakeIndex.min_score_recibido)"."""
        indice = FakeIndex(normativa_df=normativa_df, plan={})
        fila = manual_df.head(1)

        comparator_laxo = DocumentComparator(
            normativa_index=indice, llm_grader=FakeGrader(), min_semantic_score=0.1
        )
        comparator_laxo.run(fila, normativa_df, max_workers=1)
        assert indice.min_score_recibido == 0.1

        comparator_estricto = DocumentComparator(
            normativa_index=indice, llm_grader=FakeGrader(), min_semantic_score=0.9
        )
        comparator_estricto.run(fila, normativa_df, max_workers=1)
        assert indice.min_score_recibido == 0.9


class TestUmbralAlteraElNumeroDeCandidatosReales:
    """`FakeIndex` no filtra por score (su búsqueda es un `plan` fijo): solo
    registra qué `min_score` recibió. Para probar que ese umbral realmente
    cambia cuántos candidatos vuelven —el efecto que le importa al auditor—
    se usa un `NormativaIndex` real con FAISS de verdad, alimentado por
    `FakeEmbeddingBackend` (determinista, sin red ni descargas de modelos).
    """

    @pytest.fixture
    def indice_real(self, normativa_df):
        backend = FakeEmbeddingBackend()
        indice = NormativaIndex(backend, use_reranker=False)
        indice.build(normativa_df)
        return indice

    def test_umbral_por_debajo_de_cualquier_score_devuelve_todos_los_candidatos(
        self, indice_real, normativa_df, manual_df
    ):
        comparator = DocumentComparator(
            normativa_index=indice_real,
            llm_grader=FakeGrader(),
            min_semantic_score=-1.0,  # por debajo de cualquier similitud coseno
            top_k_faiss=len(normativa_df),
        )

        out = comparator.run(manual_df.head(1), normativa_df, max_workers=1)

        assert len(out.iloc[0]["articulos_semanticos_raw"]) == len(normativa_df)

    def test_umbral_por_encima_de_cualquier_score_no_devuelve_candidatos(
        self, indice_real, normativa_df, manual_df
    ):
        comparator = DocumentComparator(
            normativa_index=indice_real,
            llm_grader=FakeGrader(),
            min_semantic_score=1.01,  # por encima de cualquier similitud coseno
            top_k_faiss=len(normativa_df),
        )

        out = comparator.run(manual_df.head(1), normativa_df, max_workers=1)

        assert len(out.iloc[0]["articulos_semanticos_raw"]) == 0

    def test_subir_el_umbral_reduce_o_iguala_el_numero_de_candidatos(
        self, indice_real, normativa_df, manual_df
    ):
        fila = manual_df.head(1)

        laxo = DocumentComparator(
            normativa_index=indice_real, llm_grader=FakeGrader(),
            min_semantic_score=-1.0, top_k_faiss=len(normativa_df),
        )
        estricto = DocumentComparator(
            normativa_index=indice_real, llm_grader=FakeGrader(),
            min_semantic_score=0.999, top_k_faiss=len(normativa_df),
        )

        n_laxo = len(laxo.run(fila, normativa_df, max_workers=1).iloc[0]["articulos_semanticos_raw"])
        n_estricto = len(estricto.run(fila, normativa_df, max_workers=1).iloc[0]["articulos_semanticos_raw"])

        assert n_estricto <= n_laxo
        assert n_estricto < n_laxo, (
            "con embeddings deterministas por hash, un umbral casi al máximo no "
            "debería dejar pasar los mismos candidatos que uno mínimo"
        )


# ── Defecto 3: el prefijo del backend local llega a encode() ───────────────


class TestPrefijosDependenDelBackend:
    def test_backend_sin_prefijos_declarados_no_recibe_ninguno(self, normativa_df):
        """Simula un backend estilo DMR: no declara passage_prefix/query_prefix
        (igual que LangChainDMREmbeddings). NormativaIndex no debe forzar nada."""
        backend = FakeEmbeddingBackend()
        indice = NormativaIndex(backend, use_reranker=False)

        indice.build(normativa_df)
        indice.semantic_search("una consulta cualquiera", top_k=3)

        assert backend.prefijos_vistos == ["", ""], (
            "un backend que no declara prefijos (como DMR) no debe recibir "
            "'passage: '/'query: ' de todas formas"
        )

    def test_backend_que_declara_prefijos_e5_los_recibe_en_build_y_en_search(self, normativa_df):
        """Simula el backend local (sentence-transformers / e5): si declara
        passage_prefix/query_prefix, NormativaIndex debe reenviarlos tal cual."""
        backend = FakeEmbeddingBackend()
        backend.passage_prefix = "passage: "
        backend.query_prefix = "query: "
        indice = NormativaIndex(backend, use_reranker=False)

        indice.build(normativa_df)
        assert backend.prefijos_vistos[-1] == "passage: ", (
            "build() indexa documentos: debe usar backend.passage_prefix"
        )

        indice.semantic_search("una consulta cualquiera", top_k=3)
        assert backend.prefijos_vistos[-1] == "query: ", (
            "semantic_search() indexa una consulta: debe usar backend.query_prefix"
        )

        assert backend.prefijos_vistos == ["passage: ", "query: "]

    def test_sentence_transformers_backend_declara_los_prefijos_e5(self):
        """Chequeo directo de clase, sin instanciar (evita cargar el modelo real)."""
        assert SentenceTransformersEmbeddings.passage_prefix == "passage: "
        assert SentenceTransformersEmbeddings.query_prefix == "query: "

    def test_dmr_backend_declara_prefijos_vacios(self):
        """DMR no usa la convención e5: NO debe declarar prefijos no vacíos."""
        assert LangChainDMREmbeddings.passage_prefix == ""
        assert LangChainDMREmbeddings.query_prefix == ""

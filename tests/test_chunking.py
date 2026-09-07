"""Pruebas unitarias de chunking semántico y modelo parent-child (ítem 8).

Cubre:
1. Artículos cortos que no se subdividen si caben en el presupuesto de tokens.
2. Fronteras semánticas: numerales, literales e incisos.
3. Solape configurable y validaciones de parámetros.
4. Preservación íntegra de metadatos padre-hijo (element_id, doc_id, número, etc.).
5. Integración con NormativaIndex: indexación de sub-chunks y agregación por artículo padre.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.chunking import (
    chunk_articulo,
    chunk_normativa_df,
    detectar_columna_padre,
)
from src.search_engine import NormativaIndex
from tests.fixtures import FakeEmbeddingBackend


class TestArticulosCortos:
    """Un artículo que entra en el presupuesto no debe subdividirse."""

    def test_articulo_corto_produce_un_solo_chunk_intacto(self):
        row = {
            "element_id": "ART_001",
            "doc_id": "LEY-2026.pdf",
            "numero": "1",
            "encabezado": "Objeto",
            "contenido": "Esta norma regula las operaciones de crédito bancario.",
            "seccion": "Capítulo I",
            "tipo_elemento": "articulo",
            "embed_text": "Capítulo I > Artículo 1: Objeto\nEsta norma regula las operaciones.",
        }
        chunks = chunk_articulo(row, max_tokens=100, solape=20)
        assert len(chunks) == 1
        c = chunks[0]
        assert c["parent_element_id"] == "ART_001"
        assert c["es_subchunk"] is False
        assert c["embed_text"] == row["embed_text"]
        assert c["contenido"] == row["contenido"]
        assert c["numero"] == "1"

    def test_articulo_vacio_devuelve_una_fila_sin_error(self):
        row = {
            "element_id": "ART_VACIO",
            "doc_id": "LEY.pdf",
            "numero": "0",
            "contenido": "",
        }
        chunks = chunk_articulo(row, max_tokens=100, solape=20)
        assert len(chunks) == 1
        assert chunks[0]["es_subchunk"] is False


class TestFronterasSemanticas:
    """Subdivisión respetando numerales, literales y párrafos."""

    def test_subdivision_por_numerales(self):
        numerales = [
            f"{i}. Numeral {i}: Obligación financiera con suficiente extensión para superar el presupuesto establecido."
            for i in range(1, 15)
        ]
        row = {
            "element_id": "ART_NUM",
            "doc_id": "RESOLUCION.pdf",
            "numero": "10",
            "encabezado": "Obligaciones",
            "contenido": "\n".join(numerales),
            "seccion": "Título II",
            "tipo_elemento": "articulo",
        }
        chunks = chunk_articulo(row, max_tokens=60, solape=10)
        assert len(chunks) > 1
        for i, c in enumerate(chunks):
            assert c["parent_element_id"] == "ART_NUM"
            assert c["chunk_id"] == f"ART_NUM_c{i}"
            assert c["es_subchunk"] is True
            assert c["n_chunks"] == len(chunks)
            assert c["chunk_index"] == i
            # Cada sub-chunk preserva el encabezado de contexto
            assert "Título II" in c["embed_text"]

    def test_subdivision_por_literales(self):
        literales = [
            f"{chr(97 + i)}) Literal {chr(97 + i)}: Requisito operativo y de control interno detallado con contenido legal suficiente."
            for i in range(10)
        ]
        row = {
            "element_id": "ART_LIT",
            "doc_id": "NORMA.pdf",
            "numero": "5",
            "encabezado": "Requisitos",
            "contenido": "\n".join(literales),
            "seccion": "Capítulo Único",
            "tipo_elemento": "articulo",
        }
        chunks = chunk_articulo(row, max_tokens=50, solape=10)
        assert len(chunks) > 1
        for c in chunks:
            assert c["parent_element_id"] == "ART_LIT"


class TestValidacionParametros:

    def test_max_tokens_no_positivo_levanta_error(self):
        with pytest.raises(ValueError, match="max_tokens debe ser positivo"):
            chunk_articulo({"element_id": "A1"}, max_tokens=0)

    def test_solape_negativo_levanta_error(self):
        with pytest.raises(ValueError, match="solape no puede ser negativo"):
            chunk_articulo({"element_id": "A1"}, solape=-1)

    def test_solape_mayor_o_igual_a_max_tokens_levanta_error(self):
        with pytest.raises(ValueError, match="solape .* debe ser menor"):
            chunk_articulo({"element_id": "A1"}, max_tokens=50, solape=50)


class TestChunkNormativaDf:

    def test_procesa_dataframe_mixto_correctamente(self):
        df = pd.DataFrame([
            {
                "element_id": "ART_1",
                "doc_id": "DOC1.pdf",
                "numero": "1",
                "encabezado": "Corto",
                "contenido": "Artículo breve.",
                "seccion": "Secc 1",
                "tipo_elemento": "articulo",
            },
            {
                "element_id": "ART_2",
                "doc_id": "DOC1.pdf",
                "numero": "2",
                "encabezado": "Extenso con numerales",
                "contenido": "\n".join([f"{i}. Numeral extenso {i} detallando obligaciones legales y operativas." for i in range(1, 20)]),
                "seccion": "Secc 1",
                "tipo_elemento": "articulo",
            },
        ])
        chunked = chunk_normativa_df(df, max_tokens=60, solape=10)
        assert len(chunked) > 2
        assert "parent_element_id" in chunked.columns
        assert detectar_columna_padre(chunked) == "parent_element_id"

        # ART_1 tiene 1 chunk; ART_2 tiene varios
        assert len(chunked[chunked["parent_element_id"] == "ART_1"]) == 1
        assert len(chunked[chunked["parent_element_id"] == "ART_2"]) > 1


class TestNormativaIndexIntegracion:

    def test_index_agrupa_subchunks_y_devuelve_articulo_padre(self):
        # Crear artículo largo subdividido
        contenido_largo = "\n".join([
            f"{i}. Numeral {i}: Política de originación crediticia y análisis exhaustivo de capacidad de pago y mitigación de riesgo para el sistema financiero."
            for i in range(1, 15)
        ])
        art_largo = {
            "element_id": "ART_EXTENSO",
            "doc_id": "DOC.pdf",
            "numero": "35",
            "encabezado": "Gestión de Riesgo de Crédito",
            "contenido": contenido_largo,
            "seccion": "Riesgo",
            "tipo_elemento": "articulo",
        }
        art_corto = {
            "element_id": "ART_BREVE",
            "doc_id": "DOC.pdf",
            "numero": "36",
            "encabezado": "Auditoría Interna",
            "contenido": "La auditoría interna verificará el cumplimiento anual de políticas.",
            "seccion": "Riesgo",
            "tipo_elemento": "articulo",
        }
        df_original = pd.DataFrame([art_largo, art_corto])
        df_chunks = chunk_normativa_df(df_original, max_tokens=50, solape=10)

        backend = FakeEmbeddingBackend(dim=16)
        index = NormativaIndex(embedding_backend=backend, use_reranker=False)
        index.build(df_chunks)

        assert index._col_padre == "parent_element_id"
        assert index._max_chunks_por_padre >= 2

        # Búsqueda semántica
        candidatos = index.semantic_search("política de originación", top_k=2, min_score=0.0)
        assert len(candidatos) <= 2
        # Los resultados devueltos deben ser artículos padres (no sub-chunks)
        element_ids = [c["element_id"] for c in candidatos]
        assert "ART_EXTENSO" in element_ids
        for c in candidatos:
            assert "_c" not in c["element_id"]

    def test_index_sin_chunks_sigue_funcionando_normalmente(self):
        df = pd.DataFrame([
            {"element_id": "A1", "numero": "1", "embed_text": "Texto A1", "contenido": "Contenido A1"},
            {"element_id": "A2", "numero": "2", "embed_text": "Texto A2", "contenido": "Contenido A2"},
        ])
        backend = FakeEmbeddingBackend(dim=16)
        index = NormativaIndex(embedding_backend=backend, use_reranker=False)
        index.build(df)

        assert index._col_padre is None
        cands = index.semantic_search("Texto A1", top_k=2, min_score=-1.0)
        assert len(cands) == 2
        assert cands[0]["element_id"] == "A1"

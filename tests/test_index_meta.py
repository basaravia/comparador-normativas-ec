"""Defecto 4 de §2.2 — un índice no se carga con un backend distinto del que lo creó.

Hoy el daño se limita a un error críptico de dimensión: molesto, pero ruidoso. Con
proveedores de nube el riesgo cambia de naturaleza: dos modelos distintos de **la misma
dimensión** (1536 es un valor muy común) cargan sin protestar y devuelven vecinos sin
sentido, en silencio. Un papel de trabajo construido sobre eso es indistinguible de uno
correcto, y esa es la peor propiedad que puede tener un entregable de auditoría.

Estas pruebas usan embeddings falsos: no hay red ni modelos reales.
"""
from __future__ import annotations

import json

import pytest

from src.search_engine import NormativaIndex
from tests.fixtures import FakeEmbeddingBackend


def _indice(backend, normativa_df) -> NormativaIndex:
    idx = NormativaIndex(embedding_backend=backend, use_reranker=False)
    idx.build(normativa_df, text_col="embed_text")
    return idx


class TestFirmaDelIndice:

    def test_save_escribe_index_meta(self, tmp_path, normativa_df):
        backend = FakeEmbeddingBackend(dim=32)
        backend.nombre_modelo = "modelo-a"
        _indice(backend, normativa_df).save(tmp_path)

        meta = json.loads((tmp_path / "index_meta.json").read_text(encoding="utf-8"))
        assert meta["modelo"] == "modelo-a"
        assert meta["dim"] == 32
        assert meta["backend"] == "FakeEmbeddingBackend"
        assert "fecha" in meta

    def test_carga_con_el_mismo_backend(self, tmp_path, normativa_df):
        backend = FakeEmbeddingBackend(dim=32)
        backend.nombre_modelo = "modelo-a"
        _indice(backend, normativa_df).save(tmp_path)

        otro = NormativaIndex(embedding_backend=backend, use_reranker=False)
        otro.load(tmp_path)   # no debe lanzar
        assert otro._index.ntotal == len(normativa_df)


class TestRechazoPorModeloDistinto:

    def test_misma_dimension_pero_otro_modelo_se_rechaza(self, tmp_path, normativa_df):
        """El caso que motiva el ítem: **misma dim**, modelo distinto.

        Sin la firma esto cargaría sin una sola queja y devolvería vecinos sin sentido.
        """
        backend_a = FakeEmbeddingBackend(dim=1536)
        backend_a.nombre_modelo = "text-embedding-modelo-a"
        _indice(backend_a, normativa_df).save(tmp_path)

        backend_b = FakeEmbeddingBackend(dim=1536)      # ← misma dimensión
        backend_b.nombre_modelo = "text-embedding-modelo-b"
        otro = NormativaIndex(embedding_backend=backend_b, use_reranker=False)

        with pytest.raises(ValueError, match="otro backend"):
            otro.load(tmp_path)

    def test_el_mensaje_dice_qué_no_cuadra(self, tmp_path, normativa_df):
        backend_a = FakeEmbeddingBackend(dim=1536)
        backend_a.nombre_modelo = "modelo-a"
        _indice(backend_a, normativa_df).save(tmp_path)

        backend_b = FakeEmbeddingBackend(dim=1536)
        backend_b.nombre_modelo = "modelo-b"
        with pytest.raises(ValueError) as exc:
            NormativaIndex(embedding_backend=backend_b, use_reranker=False).load(tmp_path)

        mensaje = str(exc.value)
        assert "modelo-a" in mensaje and "modelo-b" in mensaje, (
            "el error debe decir qué modelo esperaba y cuál se le pasó"
        )

    def test_estricto_false_permite_cargar_avisando(self, tmp_path, normativa_df, caplog):
        """Escotilla para índices anteriores a esta versión."""
        backend_a = FakeEmbeddingBackend(dim=64)
        backend_a.nombre_modelo = "modelo-a"
        _indice(backend_a, normativa_df).save(tmp_path)

        backend_b = FakeEmbeddingBackend(dim=64)
        backend_b.nombre_modelo = "modelo-b"
        otro = NormativaIndex(embedding_backend=backend_b, use_reranker=False)
        otro.load(tmp_path, estricto=False)   # no lanza
        assert any("otro backend" in r.getMessage() for r in caplog.records), (
            "cargar con estricto=False no puede pasar en silencio: debe avisar"
        )


class TestIndiceSinFirma:

    def test_un_indice_antiguo_carga_pero_avisa(self, tmp_path, normativa_df, caplog):
        backend = FakeEmbeddingBackend(dim=32)
        _indice(backend, normativa_df).save(tmp_path)
        (tmp_path / "index_meta.json").unlink()      # simula un índice pre-existente

        NormativaIndex(embedding_backend=backend, use_reranker=False).load(tmp_path)
        assert any("no lleva firma" in r.getMessage() for r in caplog.records), (
            "cargar un índice sin firma no puede pasar en silencio"
        )

"""Ítem 3 — reanudación sin reprocesamiento.

Una corrida completa son horas de LLM. Antes, `results_df` solo se materializaba al
terminar `run()` entero: si el proceso moría a mitad, se perdía todo lo pagado.

Lo que estas pruebas fijan:
  · reanudar no repite ninguna llamada ya hecha
  · el resultado final es idéntico al de una corrida ininterrumpida
  · un cambio de documentos, modelo o alcance invalida la reanudación
  · un `rows.jsonl` truncado no se lleva por delante la corrida entera
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.checkpoint import CheckpointStore, Manifest, hash_documentos, purgar
from src.comparator import DocumentComparator
from tests.fixtures import FakeGrader, FakeIndex


def _manifest(unidades, **kw) -> Manifest:
    base = dict(run_id="r1", hash_documentos="abc", modelo_llm="m1",
                modelo_embeddings="e1", total_unidades=len(unidades),
                unidades=list(unidades))
    base.update(kw)
    return Manifest(**base)


class TestReanudarSinRepetir:
    """El corazón del ítem 3."""

    def _corrida(self, normativa_df, manual_df, checkpoint, hasta=None):
        """Corre el pipeline; si `hasta` se indica, aborta tras N unidades."""
        grader = FakeGrader()
        if hasta is not None:
            original = grader.analyze_comparison

            def _corta(row, lex, val):
                if grader.llamadas_analyze >= hasta:
                    raise KeyboardInterrupt("simula que matan el proceso")
                return original(row, lex, val)

            grader.analyze_comparison = _corta

        comparador = DocumentComparator(
            normativa_index=FakeIndex(normativa_df=normativa_df, plan={}),
            llm_grader=grader,
        )
        return comparador, grader

    def test_no_repite_llamadas_ya_completadas(self, tmp_path, normativa_df, manual_df):
        store = CheckpointStore(tmp_path / "run1")

        # Primera pasada: se interrumpe tras 3 secciones.
        comparador, grader1 = self._corrida(normativa_df, manual_df, store, hasta=3)
        with pytest.raises(KeyboardInterrupt):
            comparador.run(manual_df, normativa_df, max_workers=1, checkpoint=store)
        completadas = len(store.completadas())
        assert completadas >= 1, "no se persistió ninguna unidad antes de morir"

        # Segunda pasada: reanuda.
        comparador2, grader2 = self._corrida(normativa_df, manual_df, store)
        comparador2.run(manual_df, normativa_df, max_workers=1, checkpoint=store)

        assert grader2.llamadas_analyze == len(manual_df) - completadas, (
            f"reanudar repitió llamadas: hizo {grader2.llamadas_analyze} cuando quedaban "
            f"{len(manual_df) - completadas}"
        )

    def test_el_resultado_final_es_el_de_una_corrida_ininterrumpida(
        self, tmp_path, normativa_df, manual_df
    ):
        entero, _ = self._corrida(normativa_df, manual_df, None)
        esperado = entero.run(manual_df, normativa_df, max_workers=1)

        store = CheckpointStore(tmp_path / "run2")
        parcial, _ = self._corrida(normativa_df, manual_df, store, hasta=3)
        with pytest.raises(KeyboardInterrupt):
            parcial.run(manual_df, normativa_df, max_workers=1, checkpoint=store)
        reanudado, _ = self._corrida(normativa_df, manual_df, store)
        obtenido = reanudado.run(manual_df, normativa_df, max_workers=1, checkpoint=store)

        assert len(obtenido) == len(esperado)
        assert set(obtenido["jerarquia"]) == set(esperado["jerarquia"])


class TestSinReprocesamiento:
    """La decisión de guardar también las entradas (2026-08-12)."""

    def test_las_entradas_se_persisten_para_no_re_tabular(
        self, tmp_path, normativa_df, manual_df
    ):
        store = CheckpointStore(tmp_path / "run")
        store.guardar_entradas(normativa_df, manual_df)

        n, m = store.cargar_entradas()
        assert n is not None and m is not None
        assert len(n) == len(normativa_df) and len(m) == len(manual_df)

    def test_parquet_conserva_los_tipos(self, tmp_path, normativa_df, manual_df):
        """Con JSON, `es_referencia` volvía como string y dejaba de filtrar."""
        store = CheckpointStore(tmp_path / "run")
        store.guardar_entradas(normativa_df, manual_df)
        n, _ = store.cargar_entradas()
        assert n["es_referencia"].dtype == normativa_df["es_referencia"].dtype
        assert n[n["es_referencia"]].shape == normativa_df[normativa_df["es_referencia"]].shape


class TestInvalidacion:
    """Reanudar con otra configuración mezclaría dos corridas en un papel de trabajo."""

    def test_cambiar_los_documentos_invalida(self, tmp_path):
        store = CheckpointStore(tmp_path / "run")
        store.guardar_manifest(_manifest(["a", "b"]))
        store.anexar("a", {"chunk_id": "a"})

        ok, motivos = store.es_reanudable(_manifest(["a", "b"], hash_documentos="OTRO"))
        assert not ok and any("documentos" in m for m in motivos)

    def test_cambiar_el_modelo_invalida(self, tmp_path):
        store = CheckpointStore(tmp_path / "run")
        store.guardar_manifest(_manifest(["a"]))
        store.anexar("a", {"chunk_id": "a"})

        ok, motivos = store.es_reanudable(_manifest(["a"], modelo_llm="otro-modelo"))
        assert not ok and any("LLM" in m for m in motivos)

    def test_cambiar_el_alcance_invalida(self, tmp_path):
        store = CheckpointStore(tmp_path / "run")
        store.guardar_manifest(_manifest(["a", "b"]))
        store.anexar("a", {"chunk_id": "a"})

        ok, motivos = store.es_reanudable(_manifest(["a", "b", "c"]))
        assert not ok and any("alcance" in m for m in motivos)

    def test_la_misma_configuracion_si_reanuda(self, tmp_path):
        store = CheckpointStore(tmp_path / "run")
        store.guardar_manifest(_manifest(["a", "b"]))
        store.anexar("a", {"chunk_id": "a"})

        ok, motivos = store.es_reanudable(_manifest(["a", "b"]))
        assert ok, motivos


class TestResistenciaAArchivoTruncado:

    def test_una_linea_a_medias_no_se_lleva_la_corrida(self, tmp_path):
        """Si el proceso muere escribiendo, se pierde esa unidad, no el archivo."""
        store = CheckpointStore(tmp_path / "run")
        store.anexar("a", {"chunk_id": "a", "nivel_cumplimiento": "cumple"})
        store.anexar("b", {"chunk_id": "b", "nivel_cumplimiento": "parcial"})
        with store.rows_path.open("a", encoding="utf-8") as fh:
            fh.write('{"unidad_id": "c", "resulta')      # escritura interrumpida

        assert store.completadas() == {"a", "b"}
        assert len(store.cargar_parcial()) == 2

    def test_los_tipos_de_numpy_no_rompen_la_escritura(self, tmp_path):
        """Los resultados traen np.int64 y NaN; fallar aquí perdería la fila ya pagada."""
        import numpy as np

        store = CheckpointStore(tmp_path / "run")
        store.anexar("a", {
            "chunk_id": "a", "n": np.int64(3), "score": np.float64(0.9),
            "vacio": np.nan, "lista": [np.int64(1)],
        })
        # El archivo tiene que ser JSON ESTRICTO: `json.dumps` escribe el literal `NaN`
        # por defecto, que Python relee pero ningún parser conforme acepta.
        import json as _json
        crudo = store.rows_path.read_text(encoding="utf-8").strip()
        assert "NaN" not in crudo, "se escribió NaN: el archivo no es JSON válido"
        _json.loads(crudo)      # parseable

        fila = store.cargar_parcial().iloc[0]
        assert fila["n"] == 3
        assert pd.isna(fila["vacio"]), "pandas devuelve NaN donde el JSON dice null"


class TestPurga:

    def test_conserva_las_ultimas_n(self, tmp_path):
        for i in range(5):
            (tmp_path / f"2026081{i}_120000_aaa").mkdir()
        borradas = purgar(tmp_path, conservar=2)
        assert len(borradas) == 3
        assert len(list(tmp_path.iterdir())) == 2

    def test_ordena_por_fecha_sin_tocar_el_sistema_de_archivos(self, tmp_path):
        """Los run_id empiezan por fecha: ordenar por nombre ordena por antigüedad."""
        for nombre in ("20260810_010000_x", "20260812_010000_z", "20260811_010000_y"):
            (tmp_path / nombre).mkdir()
        purgar(tmp_path, conservar=1)
        assert [d.name for d in tmp_path.iterdir()] == ["20260812_010000_z"]


class TestHashDocumentos:

    def test_el_orden_de_los_archivos_no_altera_el_hash(self, tmp_path):
        a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
        a.write_bytes(b"x" * 10); b.write_bytes(b"y" * 20)
        assert hash_documentos([a, b]) == hash_documentos([b, a])

    def test_anadir_un_documento_cambia_el_hash(self, tmp_path):
        a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
        a.write_bytes(b"x" * 10); b.write_bytes(b"y" * 20)
        assert hash_documentos([a]) != hash_documentos([a, b])

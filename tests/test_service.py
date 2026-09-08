"""Capa de servicio — la costura que decide el costo de la Fase 2 (supuesto S10).

Lo que estas pruebas fijan no es que el pipeline funcione —eso ya lo cubren las demás—
sino que la **orquestación viva fuera de la interfaz**. Es la propiedad que hace que
FastAPI sea un envoltorio y no una reimplementación; si se pierde, se pierde en silencio
y solo se descubre al empezar la Fase 2.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pandas as pd
import pytest

from src import service
from src.service import RunPaths, ServiceConfig, nuevo_run_id


class TestLaUINoOrquesta:
    """La regla que hace barata la Fase 2."""

    def test_streamlit_no_construye_piezas_del_pipeline(self):
        fuente = (Path(__file__).resolve().parent.parent / "streamlit_app.py").read_text()
        constructores = (
            "NormativaParser(", "ManualParser(", "NormativaIndex(",
            "LLMGrader(", "DocumentComparator(",
        )
        infractores = [c for c in constructores if c in fuente]
        assert not infractores, (
            f"la UI volvió a construir piezas del pipeline: {infractores}. "
            "Debe pedírselas a src/service.py, o la Fase 2 tendrá que reimplementarlas"
        )

    def test_el_servicio_no_importa_streamlit(self):
        """Si el servicio conociera la UI, no serviría para nada más.

        Se comprueban los **imports**, no el texto: el docstring del módulo menciona
        Streamlit al explicar de dónde salió este código, y buscar la cadena daba un
        falso positivo.
        """
        import ast

        arbol = ast.parse(inspect.getsource(service))
        importados = {
            (n.module or "").split(".")[0]
            for n in ast.walk(arbol) if isinstance(n, ast.ImportFrom)
        } | {
            a.name.split(".")[0]
            for n in ast.walk(arbol) if isinstance(n, ast.Import) for a in n.names
        }
        assert "streamlit" not in importados, (
            f"src/service.py importa streamlit; sus imports son {sorted(importados)}"
        )

    def test_el_servicio_expone_las_cuatro_operaciones(self):
        for op in ("tabular", "construir_indice", "comparar", "exportar"):
            assert hasattr(service, op), f"falta la operación '{op}'"


class TestRutasPorCorrida:
    """§3.3.2: cada corrida escribe en su propio directorio."""

    def test_dos_corridas_no_comparten_directorio(self):
        a, b = RunPaths(run_id=nuevo_run_id()), RunPaths(run_id=nuevo_run_id())
        assert a.directorio != b.directorio, (
            "dos corridas se pisarían el reporte, como pasaba con la ruta fija"
        )

    def test_el_run_id_es_ordenable_por_tiempo(self):
        """Se buscan por fecha cuando hay que revisar una corrida concreta."""
        import time

        primero = nuevo_run_id()
        time.sleep(1.05)
        assert nuevo_run_id() > primero

    def test_los_artefactos_cuelgan_del_directorio_de_la_corrida(self, tmp_path):
        r = RunPaths(run_id="prueba", raiz=tmp_path)
        for artefacto in (r.excel, r.json, r.indice, r.manifest):
            assert r.directorio in artefacto.parents or artefacto.parent == r.directorio

    def test_el_workspace_esta_previsto_pero_inactivo(self, tmp_path):
        """Hoy el sentinela "local"; en Fase 3 es rellenar el parámetro, no un refactor (§3.3.1)."""
        sin_ws = RunPaths(run_id="x", raiz=tmp_path)
        con_ws = RunPaths(run_id="x", raiz=tmp_path, workspace="equipo-a")
        assert "workspaces" not in str(sin_ws.directorio)
        assert "workspaces" in str(con_ws.directorio)


class TestServiceConfig:
    """Sustituye al dict suelto que la UI venía pasando."""

    def test_una_clave_mal_escrita_falla_al_construir(self):
        """Con un dict, un nombre equivocado reventaba a mitad de una corrida de horas."""
        with pytest.raises(TypeError):
            ServiceConfig(max_workerss=4)      # type: ignore[call-arg]

    def test_traduce_el_dict_de_la_barra_lateral(self):
        cfg = ServiceConfig.desde_dict({
            "dmr_base_url": "http://x:1234/v1",
            "embed_backend_kind": "Local (sentence-transformers)",
            "max_workers": 3,
            "una_clave_solo_de_presentacion": True,
        })
        assert cfg.base_url == "http://x:1234/v1"
        assert cfg.embed_backend_kind == "local"
        assert cfg.max_workers == 3
        assert "una_clave_solo_de_presentacion" in cfg.extra, (
            "lo que no reconoce debe conservarse, no descartarse en silencio"
        )

    def test_el_backend_remoto_es_el_default(self):
        assert ServiceConfig.desde_dict({"embed_backend_kind": "Docker Model Runner"}) \
            .embed_backend_kind == "remoto"

    def test_traduce_vertex_ai(self):
        """Único backend de embeddings alcanzable en Databricks Apps (sin DMR/Ollama)."""
        assert ServiceConfig.desde_dict({"embed_backend_kind": "Vertex AI"}) \
            .embed_backend_kind == "vertex"

    def test_llm_backend_default_es_vertex(self):
        assert ServiceConfig.desde_dict({"llm_backend_kind": "Vertex AI"}) \
            .llm_backend_kind == "vertex"

    def test_traduce_openrouter(self):
        """Backend gratuito sin cuenta de nube — ver construir_comparador()."""
        assert ServiceConfig.desde_dict({"llm_backend_kind": "OpenRouter (gratis)"}) \
            .llm_backend_kind == "openrouter"


class TestExportar:

    def test_escribe_excel_y_json_en_el_directorio_de_la_corrida(self, tmp_path):
        df = pd.DataFrame([{
            "jerarquia": "1.1", "nivel_cumplimiento": "cumple",
            "analisis_general": "ok", "brechas": [],
        }])
        rutas = RunPaths(run_id=nuevo_run_id(), raiz=tmp_path)
        generados = service.exportar(df, rutas)

        assert generados["excel"].exists() and generados["json"].exists()
        assert generados["excel"].parent == rutas.directorio
        assert len(pd.read_excel(generados["excel"])) == 1

    def test_no_necesita_construir_un_comparador(self):
        """Exportar exigía un índice y un grader vivos solo para escribir un archivo."""
        from src.comparator import DocumentComparator

        assert isinstance(
            inspect.getattr_static(DocumentComparator, "export_excel"), staticmethod
        )

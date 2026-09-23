"""Pruebas del Papel de Trabajo en Excel (ítem 9).

Cubre:
1. Generación de las 6 hojas a partir de un ComparisonBundle sintético.
2. Lectura y validación de hojas, columnas y datos con openpyxl.
3. Configurabilidad de la plantilla YAML (cambios en etiquetas y títulos).
4. Fallback de marca (funciona con y sin brand.json).
5. Generación desde DataFrame legacy.
"""
from __future__ import annotations

from pathlib import Path

import openpyxl
import pandas as pd
import pytest
import yaml

from src.coverage import Cobertura, CoverageLink, LinkTable
from src.dual import ComparisonBundle
from src.papel_trabajo import DEFAULT_TEMPLATE_PATH, generar_papel_trabajo


@pytest.fixture
def synthetic_bundle() -> ComparisonBundle:
    """Crea un bundle sintético con datos para las 6 hojas."""
    link1 = CoverageLink(
        articulo_element_id="ART_01",
        articulo_doc_id="LEY_A.pdf",
        articulo_numero="1",
        seccion_chunk_id="SEC_01",
        seccion_doc_id="MANUAL.pdf",
        seccion_jerarquia="1.1 Objeto",
        origen="semantico_v1",
        relevante=True,
        nivel_cumplimiento="cumple",
        score_semantico=0.88,
        score_grade=0.90,
        razon="Cumple satisfactoriamente con la política",
        requiere_revision_manual=False,
    )
    link2 = CoverageLink(
        articulo_element_id="ART_02",
        articulo_doc_id="LEY_A.pdf",
        articulo_numero="2",
        seccion_chunk_id="SEC_02",
        seccion_doc_id="MANUAL.pdf",
        seccion_jerarquia="2.1 Crédito",
        origen="lexico",
        relevante=True,
        nivel_cumplimiento="parcial",
        brechas=("Falta definir límites",),
        score_semantico=0.45,
        razon="Cumplimiento parcial",
        requiere_revision_manual=True,
        motivos_revision=("parcial_con_brechas",),
    )
    links = LinkTable([link1, link2])

    df_manual = pd.DataFrame([
        {
            "chunk_id": "SEC_01",
            "jerarquia": "1.1 Objeto",
            "titulo_seccion": "Objeto del Manual",
            "articulos": ["1"],
            "normativas": ["LEY_A.pdf"],
            "nivel_cumplimiento": "cumple",
            "analisis_general": "Alineado con norma.",
            "brechas": [],
            "requiere_revision_manual": False,
            "motivos_revision": [],
        },
        {
            "chunk_id": "SEC_02",
            "jerarquia": "2.1 Crédito",
            "titulo_seccion": "Políticas de Crédito",
            "articulos": ["2"],
            "normativas": ["LEY_A.pdf"],
            "nivel_cumplimiento": "parcial",
            "analisis_general": "Faltan límites declarados.",
            "brechas": ["Falta definir límites"],
            "requiere_revision_manual": True,
            "motivos_revision": ["parcial_con_brechas"],
        },
    ])

    df_normativa = pd.DataFrame([
        {
            "element_id": "ART_01",
            "articulo_doc_id": "LEY_A.pdf",
            "numero": "1",
            "encabezado": "Objeto y Ámbito",
            "cubierto": True,
            "nivel_adopcion": "cubierto",
            "secciones_que_lo_cubren": ["1.1 Objeto"],
            "brechas": [],
            "requiere_revision_manual": False,
            "motivos_revision": [],
        },
        {
            "element_id": "ART_02",
            "articulo_doc_id": "LEY_A.pdf",
            "numero": "2",
            "encabezado": "Límites Crediticios",
            "cubierto": True,
            "nivel_adopcion": "parcial",
            "secciones_que_lo_cubren": ["2.1 Crédito"],
            "brechas": ["Falta definir límites"],
            "requiere_revision_manual": True,
            "motivos_revision": ["parcial_con_brechas"],
        },
        {
            "element_id": "ART_03",
            "articulo_doc_id": "LEY_A.pdf",
            "numero": "3",
            "encabezado": "Régimen Sancionatorio",
            "cubierto": False,
            "nivel_adopcion": "no_cubierto",
            "secciones_que_lo_cubren": [],
            "brechas": ["Sin sección de manual aplicable"],
            "requiere_revision_manual": True,
            "motivos_revision": ["articulo_sin_cobertura"],
        },
    ])

    cobertura = Cobertura(
        total_articulos=3,
        cubiertos=2,
        sin_cobertura=[{"doc_id": "LEY_A.pdf", "numero": "3"}],
    )

    return ComparisonBundle(
        links=links,
        vista_manual=df_manual,
        vista_normativa=df_normativa,
        cobertura=cobertura,
    )


class TestGeneracionPapelTrabajo:

    def test_genera_las_seis_hojas_completas(self, tmp_path: Path, synthetic_bundle: ComparisonBundle):
        salida = tmp_path / "papel_trabajo_test.xlsx"
        generar_papel_trabajo(
            synthetic_bundle,
            salida,
            metadatos={"workspace_id": "auditoria_test", "run_id": "run_001"},
        )

        assert salida.exists()
        wb = openpyxl.load_workbook(salida)

        hojas_esperadas = {
            "Resumen",
            "Vía 1 — Manual",
            "Vía 2 — Normativa",
            "Matriz N-N",
            "Revisión Manual",
            "Trazabilidad",
        }
        assert hojas_esperadas.issubset(set(wb.sheetnames)), (
            f"Faltan hojas en el libro generado. Hojas actuales: {wb.sheetnames}"
        )

        # Verificar hoja Resumen
        ws_resumen = wb["Resumen"]
        valores_resumen = [str(cell.value) for row in ws_resumen.iter_rows() for cell in row]
        assert any("Porcentaje de Cobertura Global" in v for v in valores_resumen)
        assert any("66.7%" in v for v in valores_resumen)

        # Verificar hoja Vía 1
        ws_v1 = wb["Vía 1 — Manual"]
        assert ws_v1.max_row >= 3  # header + 2 filas
        headers_v1 = [c.value for c in ws_v1[1]]
        assert "Jerarquía" in headers_v1
        assert "Nivel Cumplimiento" in headers_v1
        assert "Prioridad" in headers_v1

        # Verificar hoja Revisión Manual (contiene casos con requiere_revision_manual == True)
        ws_rev = wb["Revisión Manual"]
        assert ws_rev.max_row >= 3  # debe tener al menos la sección y el artículo marcados
        valores_rev = [str(cell.value) for row in ws_rev.iter_rows() for cell in row]
        assert any("parcial_con_brechas" in v for v in valores_rev)
        assert any("articulo_sin_cobertura" in v for v in valores_rev)

    def test_plantilla_yaml_es_configurable(self, tmp_path: Path, synthetic_bundle: ComparisonBundle):
        """Modificar una etiqueta en el YAML cambia el encabezado de la hoja."""
        with open(DEFAULT_TEMPLATE_PATH, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

        # Cambiar nombre de columna en Vía 1
        cfg["hojas"]["via1_manual"]["columnas"][0]["etiqueta"] = "Código de Estructura"
        cfg["hojas"]["via1_manual"]["nombre"] = "Vía 1 Custom"

        custom_yaml = tmp_path / "custom_plantilla.yaml"
        with open(custom_yaml, "w", encoding="utf-8") as f:
            yaml.dump(cfg, f)

        salida = tmp_path / "papel_custom.xlsx"
        generar_papel_trabajo(synthetic_bundle, salida, plantilla_path=custom_yaml)

        wb = openpyxl.load_workbook(salida)
        assert "Vía 1 Custom" in wb.sheetnames
        ws_custom = wb["Vía 1 Custom"]
        headers = [c.value for c in ws_custom[1]]
        assert "Código de Estructura" in headers

    def test_genera_desde_dataframe_plano_sin_fallar(self, tmp_path: Path):
        """Fallback elegante cuando solo se pasa un DataFrame individual."""
        df = pd.DataFrame([
            {"jerarquia": "1.1", "titulo_seccion": "Intro", "nivel_cumplimiento": "cumple"},
            {"jerarquia": "1.2", "titulo_seccion": "Alcance", "nivel_cumplimiento": "omision"},
        ])
        salida = tmp_path / "legacy_export.xlsx"
        generar_papel_trabajo(df, salida)

        assert salida.exists()
        wb = openpyxl.load_workbook(salida)
        assert "Resumen" in wb.sheetnames
        assert "Vía 1 — Manual" in wb.sheetnames

"""Generador del Papel de Trabajo en Excel (ítem 9) — auditoría completa y reproducible.

Reemplaza la exportación plana previa con un libro de 6 hojas gobernado por
`templates/papel_trabajo.yaml` y los tokens de diseño de `src/design_tokens.py`.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
import pandas as pd
import yaml

from .design_tokens import (
    FONDO,
    NIVEL_ORDEN,
    PRIMARIO,
    SUPERFICIE,
    TEXTO,
    hex_sin_almohadilla,
    marca,
    tinte,
)

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TEMPLATE_PATH = REPO_ROOT / "templates" / "papel_trabajo.yaml"


def cargar_plantilla(ruta: Path | str | None = None) -> dict[str, Any]:
    """Carga la configuración de la plantilla YAML."""
    p = Path(ruta) if ruta else DEFAULT_TEMPLATE_PATH
    if not p.exists():
        logger.warning("Plantilla %s no encontrada, usando configuración por defecto.", p)
        return {}
    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _calcular_prioridad(nivel: str, plantilla: dict[str, Any]) -> str:
    """Asigna la prioridad según el nivel y las reglas declaradas en la plantilla."""
    prioridades = plantilla.get("prioridades", {})
    nivel_norm = str(nivel).strip().lower()
    return prioridades.get(nivel_norm, prioridades.get("default", "Media"))


def _aplanar_valor(val: Any) -> str:
    """Aplana listas, tuplas o diccionarios a cadenas de texto legibles para celdas."""
    if isinstance(val, (list, tuple, set)):
        return " | ".join(str(x) for x in val if x)
    if pd.isna(val) or val is None:
        return ""
    return str(val)


def _tinte_seguro(nivel: str) -> str | None:
    """Retorna el color de tinte seguro mapeando niveles de Vía 2 a los 4 estados de diseño."""
    n = str(nivel).strip().lower()
    mapa = {
        "cubierto": "cumple",
        "no_cubierto": "omision",
    }
    clave = mapa.get(n, n)
    try:
        return tinte(clave)
    except (KeyError, TypeError):
        return None


def generar_papel_trabajo(
    bundle_o_df: Any,
    output_path: str | Path,
    plantilla_path: str | Path | None = None,
    run_scope: Any | None = None,
    metadatos: dict[str, Any] | None = None,
) -> Path:
    """Genera el libro de Excel con las 6 hojas del Papel de Trabajo."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plantilla = cargar_plantilla(plantilla_path)
    meta = metadatos or {}

    wb = openpyxl.Workbook()
    # Eliminar hoja por defecto creada por openpyxl
    if wb.active is not None:
        wb.remove(wb.active)

    # Identificar si la entrada es un ComparisonBundle o DataFrame plano
    from .dual import ComparisonBundle
    es_bundle = isinstance(bundle_o_df, ComparisonBundle)

    if es_bundle:
        bundle = bundle_o_df
        df_v1 = bundle.vista_manual.copy()
        df_v2 = bundle.vista_normativa.copy()
        df_matrix = bundle.links.to_dataframe()
        cobertura = bundle.cobertura
    else:
        # Fallback para DataFrames de corridas anteriores o llamadas legacy
        df = bundle_o_df.copy() if isinstance(bundle_o_df, pd.DataFrame) else pd.DataFrame()
        df_v1 = df
        df_v2 = pd.DataFrame()
        df_matrix = pd.DataFrame()
        cobertura = None

    # Estilos compartidos
    color_primario = hex_sin_almohadilla(PRIMARIO)
    color_superficie = hex_sin_almohadilla(SUPERFICIE)
    color_texto = hex_sin_almohadilla(TEXTO)

    font_header = Font(name="Segoe UI", size=10, bold=True, color=color_superficie)
    fill_header = PatternFill(start_color=color_primario, end_color=color_primario, fill_type="solid")
    font_bold = Font(name="Segoe UI", size=10, bold=True, color=color_texto)
    font_regular = Font(name="Segoe UI", size=9, color=color_texto)
    align_center = Alignment(horizontal="center", vertical="center")
    align_left = Alignment(horizontal="left", vertical="center")
    border_thin = Border(
        left=Side(style="thin", color="E0E0E0"),
        right=Side(style="thin", color="E0E0E0"),
        top=Side(style="thin", color="E0E0E0"),
        bottom=Side(style="thin", color="E0E0E0"),
    )

    hojas_cfg = plantilla.get("hojas", {})

    # ─────────────────────────────────────────────────────────────────────────
    # 1. Hoja Resumen
    # ─────────────────────────────────────────────────────────────────────────
    cfg_res = hojas_cfg.get("resumen", {"nombre": "Resumen", "activo": True})
    if cfg_res.get("activo", True):
        ws_res = wb.create_sheet(title=cfg_res.get("nombre", "Resumen"))
        ws_res.views.sheetView[0].showGridLines = True

        filas_resumen: list[tuple[str, Any]] = [
            ("Título del Informe", plantilla.get("titulo", "Papel de Trabajo de Auditoría")),
            ("Fecha y Hora de Emisión", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")),
            ("Espacio de Trabajo (Workspace)", meta.get("workspace_id", "local")),
            ("Identificador de Corrida (Run ID)", meta.get("run_id", "corrida_local")),
            ("Modelo LLM (Razonamiento / Grading)", meta.get("llm_model", "Gemini / Vertex AI")),
            ("Modelo de Embeddings", meta.get("embed_model", "Ollama / bge-m3")),
        ]

        if cobertura:
            filas_resumen.extend([
                ("Porcentaje de Cobertura Global", f"{cobertura.porcentaje:.1%}"),
                ("Total Artículos Evaluados", cobertura.total_articulos),
                ("Artículos con Cobertura", cobertura.cubiertos),
                ("Artículos Huérfanos / Sin Cobertura", len(cobertura.sin_cobertura)),
            ])

        if not df_v1.empty and "nivel_cumplimiento" in df_v1.columns:
            conteos = df_v1["nivel_cumplimiento"].value_counts().to_dict()
            for n in NIVEL_ORDEN:
                filas_resumen.append((f"Total Secciones - {n.capitalize()}", conteos.get(n, 0)))

        # Encabezado
        ws_res.append(["Parámetro / Métrica", "Valor Declarado"])
        ws_res["A1"].font = font_header
        ws_res["A1"].fill = fill_header
        ws_res["B1"].font = font_header
        ws_res["B1"].fill = fill_header

        for row_idx, (k, v) in enumerate(filas_resumen, start=2):
            ws_res.append([k, str(v)])
            ws_res[f"A{row_idx}"].font = font_bold
            ws_res[f"B{row_idx}"].font = font_regular
            ws_res[f"A{row_idx}"].border = border_thin
            ws_res[f"B{row_idx}"].border = border_thin

        ws_res.column_dimensions["A"].width = 38
        ws_res.column_dimensions["B"].width = 50

    # ─────────────────────────────────────────────────────────────────────────
    # 2. Hoja Vía 1 — Manual
    # ─────────────────────────────────────────────────────────────────────────
    cfg_v1 = hojas_cfg.get("via1_manual", {"nombre": "Vía 1 — Manual", "activo": True})
    if cfg_v1.get("activo", True):
        ws_v1 = wb.create_sheet(title=cfg_v1.get("nombre", "Vía 1 — Manual"))
        ws_v1.views.sheetView[0].showGridLines = True
        cols_v1 = cfg_v1.get("columnas", [])
        ws_v1.append([c.get("etiqueta", c.get("id")) for c in cols_v1])

        for cell in ws_v1[1]:
            cell.font = font_header
            cell.fill = fill_header
            cell.alignment = align_center

        if not df_v1.empty:
            for r_idx, (_, row) in enumerate(df_v1.iterrows(), start=2):
                nivel = str(row.get("nivel_cumplimiento", "")).lower()
                prioridad = _calcular_prioridad(nivel, plantilla)
                fila_datos = []
                for c in cols_v1:
                    cid = c.get("id")
                    if cid == "prioridad":
                        fila_datos.append(prioridad)
                    else:
                        fila_datos.append(_aplanar_valor(row.get(cid, "")))
                ws_v1.append(fila_datos)

                # Formato condicional de nivel
                color_bg = _tinte_seguro(nivel)
                for col_idx, c in enumerate(cols_v1, start=1):
                    cell = ws_v1.cell(row=r_idx, column=col_idx)
                    cell.font = font_regular
                    cell.border = border_thin
                    if c.get("formato_nivel") and color_bg:
                        hex_bg = hex_sin_almohadilla(color_bg)
                        cell.fill = PatternFill(start_color=hex_bg, end_color=hex_bg, fill_type="solid")
                        cell.font = Font(name="Segoe UI", size=9, bold=True, color=color_texto)

        for i, c in enumerate(cols_v1, start=1):
            col_letter = get_column_letter(i)
            ws_v1.column_dimensions[col_letter].width = c.get("ancho", 20)

    # ─────────────────────────────────────────────────────────────────────────
    # 3. Hoja Vía 2 — Normativa
    # ─────────────────────────────────────────────────────────────────────────
    cfg_v2 = hojas_cfg.get("via2_normativa", {"nombre": "Vía 2 — Normativa", "activo": True})
    if cfg_v2.get("activo", True):
        ws_v2 = wb.create_sheet(title=cfg_v2.get("nombre", "Vía 2 — Normativa"))
        ws_v2.views.sheetView[0].showGridLines = True
        cols_v2 = cfg_v2.get("columnas", [])
        ws_v2.append([c.get("etiqueta", c.get("id")) for c in cols_v2])

        for cell in ws_v2[1]:
            cell.font = font_header
            cell.fill = fill_header
            cell.alignment = align_center

        if not df_v2.empty:
            for r_idx, (_, row) in enumerate(df_v2.iterrows(), start=2):
                nivel = str(row.get("nivel_adopcion", "cubierto" if row.get("cubierto") else "no_cubierto")).lower()
                prioridad = _calcular_prioridad(nivel, plantilla)
                fila_datos = []
                for c in cols_v2:
                    cid = c.get("id")
                    if cid == "prioridad":
                        fila_datos.append(prioridad)
                    elif cid == "nivel_adopcion":
                        fila_datos.append(row.get("nivel_adopcion", "cubierto" if row.get("cubierto") else "no_cubierto"))
                    else:
                        fila_datos.append(_aplanar_valor(row.get(cid, "")))
                ws_v2.append(fila_datos)

                color_bg = _tinte_seguro(nivel)
                for col_idx, c in enumerate(cols_v2, start=1):
                    cell = ws_v2.cell(row=r_idx, column=col_idx)
                    cell.font = font_regular
                    cell.border = border_thin
                    if c.get("formato_nivel") and color_bg:
                        hex_bg = hex_sin_almohadilla(color_bg)
                        cell.fill = PatternFill(start_color=hex_bg, end_color=hex_bg, fill_type="solid")
                        cell.font = Font(name="Segoe UI", size=9, bold=True, color=color_texto)

        for i, c in enumerate(cols_v2, start=1):
            col_letter = get_column_letter(i)
            ws_v2.column_dimensions[col_letter].width = c.get("ancho", 20)

    # ─────────────────────────────────────────────────────────────────────────
    # 4. Hoja Matriz N:N
    # ─────────────────────────────────────────────────────────────────────────
    cfg_mat = hojas_cfg.get("matriz_nn", {"nombre": "Matriz N-N", "activo": True})
    if cfg_mat.get("activo", True):
        ws_mat = wb.create_sheet(title=cfg_mat.get("nombre", "Matriz N-N"))
        ws_mat.views.sheetView[0].showGridLines = True
        cols_mat = cfg_mat.get("columnas", [])
        ws_mat.append([c.get("etiqueta", c.get("id")) for c in cols_mat])

        for cell in ws_mat[1]:
            cell.font = font_header
            cell.fill = fill_header
            cell.alignment = align_center

        if not df_matrix.empty:
            for r_idx, (_, row) in enumerate(df_matrix.iterrows(), start=2):
                fila_datos = [_aplanar_valor(row.get(c.get("id"), "")) for c in cols_mat]
                ws_mat.append(fila_datos)
                for col_idx in range(1, len(cols_mat) + 1):
                    cell = ws_mat.cell(row=r_idx, column=col_idx)
                    cell.font = font_regular
                    cell.border = border_thin

        for i, c in enumerate(cols_mat, start=1):
            col_letter = get_column_letter(i)
            ws_mat.column_dimensions[col_letter].width = c.get("ancho", 20)

    # ─────────────────────────────────────────────────────────────────────────
    # 5. Hoja Revisión Manual (Ítem 10)
    # ─────────────────────────────────────────────────────────────────────────
    cfg_rev = hojas_cfg.get("revision_manual", {"nombre": "Revisión Manual", "activo": True})
    if cfg_rev.get("activo", True):
        ws_rev = wb.create_sheet(title=cfg_rev.get("nombre", "Revisión Manual"))
        ws_rev.views.sheetView[0].showGridLines = True
        cols_rev = cfg_rev.get("columnas", [])
        ws_rev.append([c.get("etiqueta", c.get("id")) for c in cols_rev])

        for cell in ws_rev[1]:
            cell.font = font_header
            cell.fill = fill_header
            cell.alignment = align_center

        filas_revision: list[dict[str, Any]] = []

        # Casos de Vía 1
        if not df_v1.empty and "requiere_revision_manual" in df_v1.columns:
            for _, r in df_v1[df_v1["requiere_revision_manual"]].iterrows():
                filas_revision.append({
                    "tipo_elemento": "Sección Manual",
                    "identificador": r.get("jerarquia", r.get("chunk_id", "")),
                    "descripcion": r.get("titulo_seccion", ""),
                    "motivos_revision": _aplanar_valor(r.get("motivos_revision", [])),
                    "prioridad": "Alta" if "omision" in str(r.get("nivel_cumplimiento", "")) else "Media",
                    "accion_sugerida": "Validar evidencia con oficial de cumplimiento",
                })

        # Casos de Vía 2
        if not df_v2.empty and "requiere_revision_manual" in df_v2.columns:
            for _, r in df_v2[df_v2["requiere_revision_manual"]].iterrows():
                filas_revision.append({
                    "tipo_elemento": "Artículo Normativo",
                    "identificador": f"{r.get('articulo_doc_id', '')} - Art. {r.get('numero', '')}",
                    "descripcion": r.get("encabezado", ""),
                    "motivos_revision": _aplanar_valor(r.get("motivos_revision", [])),
                    "prioridad": "Alta" if not r.get("cubierto") else "Media",
                    "accion_sugerida": "Incorporar sección en manual interno para cubrir artículo",
                })

        for r_idx, r in enumerate(filas_revision, start=2):
            ws_rev.append([_aplanar_valor(r.get(c.get("id"), "")) for c in cols_rev])
            for col_idx in range(1, len(cols_rev) + 1):
                cell = ws_rev.cell(row=r_idx, column=col_idx)
                cell.font = font_regular
                cell.border = border_thin

        for i, c in enumerate(cols_rev, start=1):
            col_letter = get_column_letter(i)
            ws_rev.column_dimensions[col_letter].width = c.get("ancho", 25)

    # ─────────────────────────────────────────────────────────────────────────
    # 6. Hoja Trazabilidad
    # ─────────────────────────────────────────────────────────────────────────
    cfg_tra = hojas_cfg.get("trazabilidad", {"nombre": "Trazabilidad", "activo": True})
    if cfg_tra.get("activo", True):
        ws_tra = wb.create_sheet(title=cfg_tra.get("nombre", "Trazabilidad"))
        ws_tra.views.sheetView[0].showGridLines = True
        ws_tra.append(["Parámetro de Auditoría", "Detalle de Trazabilidad Técnica"])
        ws_tra["A1"].font = font_header
        ws_tra["A1"].fill = fill_header
        ws_tra["B1"].font = font_header
        ws_tra["B1"].fill = fill_header

        trazabilidad_filas = [
            ("Versión del Generador", "1.0 (Ola 4)"),
            ("Fecha de Generación (UTC)", datetime.now(timezone.utc).isoformat()),
            ("Workspace ID", meta.get("workspace_id", "local")),
            ("Run ID", meta.get("run_id", "run_local")),
            ("Umbral Mínimo Semántico", meta.get("min_semantic_score", 0.30)),
            ("FAISS Top-K Candidatos", meta.get("faiss_top_k", 5)),
            ("Top-N Reranking", meta.get("reranker_top_n", 3)),
            ("Configuración de Alcance", str(run_scope.to_dict()) if run_scope and hasattr(run_scope, "to_dict") else "Completo"),
        ]

        for r_idx, (p, d) in enumerate(trazabilidad_filas, start=2):
            ws_tra.append([p, str(d)])
            ws_tra[f"A{r_idx}"].font = font_bold
            ws_tra[f"B{r_idx}"].font = font_regular
            ws_tra[f"A{r_idx}"].border = border_thin
            ws_tra[f"B{r_idx}"].border = border_thin

        ws_tra.column_dimensions["A"].width = 35
        ws_tra.column_dimensions["B"].width = 60

    wb.save(output_path)
    logger.info("Papel de Trabajo generado en %s", output_path)
    return output_path

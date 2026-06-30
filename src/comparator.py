"""Orquestador principal — integra todas las fases con procesamiento concurrente.

Fases por sección del manual:
  1 → Lexical scan          (regex, instantáneo)
  2 → Semantic search FAISS (vectorial, muy rápido)
  2b→ Reranking DMR         (qwen3-reranker, opcional)
  3 → Grade candidates      (LLM, grading de relevancia)
  4 → Comparative analysis  (LLM, análisis profundo)

Columnas generadas en el DataFrame de salida:
  articulos_lexicos, articulos_semanticos_raw, articulos_validados,
  tipo_coincidencia, nivel_cumplimiento,
  analisis_lexico, analisis_semantico_top1/2/3, analisis_general,
  brechas, ner_general, entidades_financieras, entidades_normativas
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

import pandas as pd
from tqdm import tqdm

from .llm_grader import ComparisonResult, LLMGrader
from .search_engine import NormativaIndex
from .config import FAISS_TOP_K, MAX_WORKERS, RERANKER_TOP_N

logger = logging.getLogger(__name__)


class DocumentComparator:
    """Pipeline de comparación normativa vs manual con procesamiento concurrente.

    Uso básico:
        comparator = DocumentComparator(normativa_index, llm_grader)
        results_df = comparator.run(manual_df, normativa_df)
        comparator.export_excel(results_df, "output/reporte.xlsx")
    """

    def __init__(
        self,
        normativa_index: NormativaIndex,
        llm_grader: LLMGrader,
        top_k_faiss: int = FAISS_TOP_K,
        top_n_rerank: int = RERANKER_TOP_N,
    ) -> None:
        self.index = normativa_index
        self.grader = llm_grader
        self.top_k_faiss = top_k_faiss
        self.top_n_rerank = top_n_rerank

    # ── API pública ───────────────────────────────────────────────────────

    def run(
        self,
        manual_df: pd.DataFrame,
        normativa_df: pd.DataFrame,
        max_workers: int = MAX_WORKERS,
        desc: str = "Comparando secciones del manual",
    ) -> pd.DataFrame:
        """Ejecuta el pipeline completo con procesamiento concurrente via ThreadPoolExecutor.

        Parámetros:
            manual_df   : DataFrame de secciones del manual (salida de ManualParser)
            normativa_df: DataFrame de artículos de la normativa (salida de NormativaParser)
            max_workers : Hilos simultáneos para llamadas LLM
            desc        : Descripción para la barra de progreso tqdm

        Retorna DataFrame del manual enriquecido con columnas de análisis.
        """
        rows = manual_df.to_dict("records")
        results: dict[int, dict] = {}

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self._process_row, row, normativa_df): i
                for i, row in enumerate(rows)
            }
            with tqdm(total=len(futures), desc=desc, unit="sección", colour="cyan") as pbar:
                for future in as_completed(futures):
                    idx = futures[future]
                    try:
                        results[idx] = future.result()
                    except Exception as e:
                        logger.error("Error en fila %d: %s", idx, e)
                        results[idx] = {**rows[idx], **self._empty_result()}
                    pbar.update(1)

        return pd.DataFrame([results[i] for i in range(len(rows))])

    def run_sample(
        self,
        manual_df: pd.DataFrame,
        normativa_df: pd.DataFrame,
        n: int = 5,
        max_workers: int = 2,
    ) -> pd.DataFrame:
        """Ejecuta el pipeline sobre una muestra aleatoria (útil para pruebas)."""
        sample = manual_df.sample(min(n, len(manual_df)), random_state=42)
        return self.run(sample, normativa_df, max_workers=max_workers, desc=f"Muestra {n} secciones")

    def export_excel(
        self,
        df: pd.DataFrame,
        output_path: str | Path,
    ) -> Path:
        """Exporta el DataFrame de resultados a Excel con formato visual por nivel de cumplimiento."""
        from openpyxl.styles import PatternFill, Font, Alignment

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        df_export = self._flatten_for_excel(df)

        with pd.ExcelWriter(str(output_path), engine="openpyxl") as writer:
            df_export.to_excel(writer, index=False, sheet_name="Comparación")
            ws = writer.sheets["Comparación"]

            # Encabezados: fondo azul oscuro, texto blanco bold
            header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
            header_font = Font(color="FFFFFF", bold=True, size=11)
            for cell in ws[1]:
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(wrap_text=True, horizontal="center", vertical="center")

            # Filas: color según nivel de cumplimiento
            fills = {
                "cumple":    PatternFill(start_color="E2EFDA", end_color="E2EFDA", fill_type="solid"),
                "parcial":   PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid"),
                "omision":   PatternFill(start_color="FCE4D6", end_color="FCE4D6", fill_type="solid"),
                "no_aplica": PatternFill(start_color="F2F2F2", end_color="F2F2F2", fill_type="solid"),
            }
            cumpl_col = next(
                (j for j, c in enumerate(ws[1], 1) if c.value == "nivel_cumplimiento"),
                None,
            )
            if cumpl_col:
                for row in ws.iter_rows(min_row=2):
                    level = str(row[cumpl_col - 1].value or "")
                    fill = fills.get(level)
                    if fill:
                        for cell in row:
                            cell.fill = fill

            # Ajuste de ancho de columnas
            for col in ws.columns:
                max_len = max(
                    (len(str(c.value or "")) for c in col), default=0
                )
                ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 70)

            ws.freeze_panes = "A2"

        logger.info("Excel exportado: %s (%d filas)", output_path, len(df_export))
        return output_path

    # ── Procesamiento por fila ────────────────────────────────────────────

    def _process_row(self, row: dict, normativa_df: pd.DataFrame) -> dict:
        """Pipeline completo para una sección del manual (ejecutado en thread)."""
        text = row.get("texto", row.get("contenido", ""))
        embed_text = row.get("embed_text", text)

        # Phase 2a: Escaneo léxico
        lexical = self.index.lexical_scan(text, normativa_df)

        # Phase 2b: Búsqueda semántica FAISS
        semantic_raw = self.index.semantic_search(embed_text, top_k=self.top_k_faiss)

        # Phase 2c: Reranking (si está habilitado en el índice)
        reranked = self.index.rerank(embed_text, semantic_raw, top_n=self.top_n_rerank)

        # Phase 3: Grading de candidatos semánticos
        graded = self.grader.grade_candidates(text, reranked)
        validated = [c for c in graded if c.get("relevante", True)]

        # Phase 4: Análisis comparativo profundo
        analysis: ComparisonResult = self.grader.analyze_comparison(row, lexical, validated)

        return {
            **row,
            # Búsqueda
            "articulos_lexicos":         [m.get("numero") for m in lexical],
            "articulos_semanticos_raw":  [
                {"numero": c.get("numero"), "sim": c.get("similarity", 0)}
                for c in semantic_raw
            ],
            "articulos_validados": [
                {
                    "numero": c.get("numero"),
                    "relevante": c.get("relevante"),
                    "score": c.get("score_grade", 0),
                }
                for c in graded
            ],
            # Análisis
            "tipo_coincidencia":       analysis.tipo_coincidencia,
            "nivel_cumplimiento":      analysis.nivel_cumplimiento,
            "analisis_lexico":         analysis.analisis_lexico,
            "analisis_semantico_top1": analysis.analisis_semantico_top1,
            "analisis_semantico_top2": analysis.analisis_semantico_top2,
            "analisis_semantico_top3": analysis.analisis_semantico_top3,
            "analisis_general":        analysis.analisis_general,
            # NER y brechas
            "brechas":                 analysis.brechas,
            "ner_general":             analysis.ner_general,
            "entidades_financieras":   analysis.entidades_financieras,
            "entidades_normativas":    analysis.entidades_normativas,
        }

    @staticmethod
    def _empty_result() -> dict:
        return {
            "articulos_lexicos": [],
            "articulos_semanticos_raw": [],
            "articulos_validados": [],
            "tipo_coincidencia": "ninguna",
            "nivel_cumplimiento": "no_aplica",
            "analisis_lexico": None,
            "analisis_semantico_top1": None,
            "analisis_semantico_top2": None,
            "analisis_semantico_top3": None,
            "analisis_general": "Error en procesamiento",
            "brechas": [],
            "ner_general": [],
            "entidades_financieras": [],
            "entidades_normativas": [],
        }

    @staticmethod
    def _flatten_for_excel(df: pd.DataFrame) -> pd.DataFrame:
        """Convierte columnas de listas a strings para exportación Excel."""
        df_out = df.copy()
        list_cols = [
            "articulos_lexicos", "brechas", "ner_general",
            "entidades_financieras", "entidades_normativas",
        ]
        for col in list_cols:
            if col in df_out.columns:
                df_out[col] = df_out[col].apply(
                    lambda x: "; ".join(str(i) for i in x) if isinstance(x, list) else str(x or "")
                )
        dict_cols = ["articulos_semanticos_raw", "articulos_validados"]
        for col in dict_cols:
            if col in df_out.columns:
                df_out[col] = df_out[col].apply(
                    lambda x: str(x) if isinstance(x, (list, dict)) else ""
                )
        return df_out

    # ── Resumen estadístico ───────────────────────────────────────────────

    @staticmethod
    def summary(df: pd.DataFrame) -> pd.DataFrame:
        """Genera tabla resumen por nivel de cumplimiento."""
        if "nivel_cumplimiento" not in df.columns:
            return pd.DataFrame()
        counts = df["nivel_cumplimiento"].value_counts().rename("secciones")
        pct = (counts / len(df) * 100).round(1).rename("porcentaje")
        return pd.concat([counts, pct], axis=1)

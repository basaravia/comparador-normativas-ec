"""Orquestador principal — integra todas las fases con procesamiento concurrente.

Fases por sección del manual:
  1 → Lexical scan          (regex, instantáneo)
  2 → Semantic search FAISS (vectorial, muy rápido)
  2b→ Reranking DMR         (qwen3-reranker, opcional)
  3 → Grade candidates      (LLM, grading de relevancia)
  4 → Comparative analysis  (LLM, análisis profundo)

Columnas generadas en el DataFrame de salida:
  articulos_lexicos, articulos_semanticos_raw, articulos_validados,
  tipo_coincidencia, nivel_cumplimiento, estado_analisis,
  analisis_lexico, analisis_semantico_top1/2/3, analisis_general,
  brechas, ner_general, entidades_financieras, entidades_normativas

`estado_analisis` ∈ {ok, error_modelo, error_parseo, omitido} es **independiente** de
`nivel_cumplimiento` (supuesto S2 del plan). Un fallo técnico nunca se expresa como un
veredicto de cumplimiento: cuando el análisis no se pudo hacer, `nivel_cumplimiento` queda
vacío y el motivo va en `estado_analisis`. Antes todo fallo salía como "no_aplica", que es
un veredicto legítimo —"se miró y no hay norma aplicable"— y confundía las dos cosas.

**`estado_analisis` es el campo autoritativo, no la ausencia del nivel.** Para saber si una
fila tiene veredicto hay que mirar `estado_analisis == "ok"`, nunca `nivel_cumplimiento is
None`: pandas 3.0 cambió la inferencia de dtype y una columna de strings con None pasa de
`object` (donde None sobrevive) a `str` (donde se vuelve NaN). El mismo código da `None` en
pandas 2.3 y `NaN` en 3.0, así que cualquier comparación con `is None` sobre un valor
sacado del DataFrame es frágil. Si hace falta comprobar el nivel, `pd.isna()`.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Optional

import pandas as pd
from tqdm import tqdm

from .design_tokens import ESTADO, PRIMARIO, SUPERFICIE, hex_sin_almohadilla
from .llm_grader import ComparisonResult, LLMGrader
from .search_engine import NormativaIndex
from .config import FAISS_TOP_K, MAX_WORKERS, MIN_SEMANTIC_SCORE, RERANKER_TOP_N
from .errors import (
    ComparadorError,
    LLMUnavailableError,
    RunAbortedError,
    classify_llm_exception,
)

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
        min_semantic_score: float = MIN_SEMANTIC_SCORE,
        max_fallos_consecutivos: int = 3,
    ) -> None:
        self.index = normativa_index
        self.grader = llm_grader
        self.top_k_faiss = top_k_faiss
        self.top_n_rerank = top_n_rerank
        # Defecto 1 de §2.2 del plan: antes de esto, `_process_row` nunca pasaba
        # `min_score` a `semantic_search()`, así que el umbral configurado en el
        # sidebar era decorativo y siempre corría con el default de config.py.
        self.min_semantic_score = min_semantic_score
        # Tres fallos de fila seguidos dejan de parecer casualidad: casi siempre es el
        # modelo degradándose, no las secciones. Configurable porque el umbral útil
        # depende del tamaño de la corrida.
        self.max_fallos_consecutivos = max_fallos_consecutivos

    # ── API pública ───────────────────────────────────────────────────────

    def run(
        self,
        manual_df: pd.DataFrame,
        normativa_df: pd.DataFrame,
        max_workers: int = MAX_WORKERS,
        desc: str = "Comparando secciones del manual",
        progress_callback: Optional[Callable[[int, int, dict], None]] = None,
    ) -> pd.DataFrame:
        """Ejecuta el pipeline completo con procesamiento concurrente via ThreadPoolExecutor.

        Parámetros:
            manual_df         : DataFrame de secciones del manual (salida de ManualParser)
            normativa_df      : DataFrame de artículos de la normativa (salida de NormativaParser)
            max_workers       : Hilos simultáneos para llamadas LLM
            desc              : Descripción para la barra de progreso tqdm
            progress_callback : Si se provee, se invoca tras cada fila completada con
                                 (completadas, total, resultado_fila) — útil para reportar
                                 avance a una UI (p.ej. Streamlit) sin depender de tqdm.

        Retorna DataFrame del manual enriquecido con columnas de análisis.
        """
        rows = manual_df.to_dict("records")
        results: dict[int, dict] = {}
        total = len(rows)
        fallos_consecutivos = 0
        abortar: ComparadorError | None = None

        # Envío acotado, no todo de golpe.
        #
        # Con `submit()` de las N filas por adelantado, `cancel_futures=True` solo puede
        # cancelar lo que aún no arrancó — y si el trabajo es rápido, para cuando el
        # bucle detecta el fallo ya se ejecutó todo. La cancelación quedaba a merced de
        # que el modelo fuese lento, que es justo lo que no se puede asumir.
        #
        # Manteniendo una ventana de tareas en vuelo, la corrida deja de enviar en
        # cuanto hay que abortar. Además evita retener en memoria una tarea por sección
        # en corridas de cientos de filas.
        ventana = max(max_workers * 2, 2)
        pendientes = iter(enumerate(rows))
        completed = 0

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures: dict = {}

            def _rellenar() -> None:
                while len(futures) < ventana:
                    try:
                        i, row = next(pendientes)
                    except StopIteration:
                        return
                    futures[executor.submit(self._process_row, row, normativa_df)] = i

            _rellenar()

            with tqdm(total=total, desc=desc, unit="sección", colour="cyan") as pbar:
                while futures:
                    hecho = next(as_completed(list(futures)))
                    idx = futures.pop(hecho)
                    future = hecho
                    completed += 1
                    try:
                        results[idx] = future.result()
                        fallos_consecutivos = 0
                    except Exception as e:
                        error = classify_llm_exception(e)

                        if isinstance(error, LLMUnavailableError):
                            # No tiene sentido seguir: el backend no va a mejorar en la
                            # fila siguiente. Se cancela lo pendiente en vez de gastar
                            # minutos generando filas vacías (ítem 1).
                            logger.error("Fila %d abortó la corrida: %s", idx, error)
                            # Esta fila falló; no se la deja caer en el relleno de
                            # "omitido" de abajo, que significa "nadie la miró".
                            results[idx] = {**rows[idx], **self._empty_result("error_modelo")}
                            abortar = error
                            executor.shutdown(wait=False, cancel_futures=True)
                            break

                        # Error de contenido: degrada solo esta fila y sigue.
                        logger.warning("Fila %d degradada: %s", idx, error)
                        results[idx] = {**rows[idx], **self._empty_result("error_parseo")}
                        fallos_consecutivos += 1

                        if fallos_consecutivos >= self.max_fallos_consecutivos:
                            # Varios fallos seguidos dejan de parecer casualidad: casi
                            # siempre es el modelo degradándose, no las secciones.
                            logger.error(
                                "%d fallos consecutivos: se aborta la corrida",
                                fallos_consecutivos,
                            )
                            abortar = error
                            executor.shutdown(wait=False, cancel_futures=True)
                            break

                    pbar.update(1)
                    if progress_callback is not None:
                        progress_callback(completed, total, results[idx])

                    # Solo se envía más trabajo si la corrida sigue viva.
                    _rellenar()

        # Las filas que nunca llegaron a procesarse quedan explícitamente como omitidas.
        # No son "no aplica": nadie las miró, y el papel de trabajo debe poder decirlo.
        for i, row in enumerate(rows):
            results.setdefault(i, {**row, **self._empty_result("omitido")})

        df = pd.DataFrame([results[i] for i in range(len(rows))])

        if abortar is not None:
            analizadas = sum(
                1 for r in results.values() if r.get("estado_analisis") != "omitido"
            )
            error = RunAbortedError(
                f"Corrida detenida tras {analizadas}/{total} secciones: {abortar}",
                completadas=analizadas,
                total=total,
                causa=abortar,
            )
            # Los resultados parciales viajan con la excepción: se han pagado en tiempo
            # de LLM y perderlos por un fallo al final sería gratuito. La UI los muestra
            # etiquetados como parciales.
            error.parciales = df
            raise error

        return df

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

    @staticmethod
    def export_excel(
        df: pd.DataFrame,
        output_path: str | Path,
    ) -> Path:
        """Exporta el DataFrame de resultados a Excel con formato visual por nivel.

        Estático porque no usa estado de la instancia: solo delega en `_flatten_for_excel`,
        que también lo es. Así `service.py` puede exportar sin construir un comparador
        —que exigiría un índice y un grader vivos solo para escribir un archivo—. Llamarlo
        sobre una instancia sigue funcionando, que es como lo hace `master.ipynb` (S5).
        """
        from openpyxl.styles import PatternFill, Font, Alignment

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        df_export = DocumentComparator._flatten_for_excel(df)

        with pd.ExcelWriter(str(output_path), engine="openpyxl") as writer:
            df_export.to_excel(writer, index=False, sheet_name="Comparación")
            ws = writer.sheets["Comparación"]

            # Encabezados: cromo de marca (§8.2 PLAN_MEJORAS_ANEXO.md — cabecera
            # = primario saturado), texto en superficie (blanco) bold.
            primario_hex = hex_sin_almohadilla(PRIMARIO)
            header_fill = PatternFill(start_color=primario_hex, end_color=primario_hex, fill_type="solid")
            header_font = Font(color=hex_sin_almohadilla(SUPERFICIE), bold=True, size=11)
            for cell in ws[1]:
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(wrap_text=True, horizontal="center", vertical="center")

            # Filas: color según nivel de cumplimiento. Tintes desaturados de
            # `design_tokens.ESTADO` — nunca el primario ni el acento de marca
            # (regla cromo/dato, §8.2): un "cumple" en verde saturado se
            # confundiría con el cromo de la cabecera de arriba.
            fills = {
                nivel: PatternFill(
                    start_color=hex_sin_almohadilla(datos["tinte"]),
                    end_color=hex_sin_almohadilla(datos["tinte"]),
                    fill_type="solid",
                )
                for nivel, datos in ESTADO.items()
                if not nivel.startswith("_")
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
        semantic_raw = self.index.semantic_search(
            embed_text, top_k=self.top_k_faiss, min_score=self.min_semantic_score
        )

        # Phase 2c: Reranking (si está habilitado en el índice)
        reranked = self.index.rerank(embed_text, semantic_raw, top_n=self.top_n_rerank)

        # Phase 3: Grading de candidatos semánticos
        graded = self.grader.grade_candidates(text, reranked)
        # `is True`, no truthiness con default True. Tras el ítem 4, `relevante` puede
        # ser None —el grading no pudo determinarlo— y un candidato indeterminado no
        # entra al análisis como si estuviera validado. El default optimista de antes
        # era justamente lo que colaba falsos positivos de cumplimiento.
        validated = [c for c in graded if c.get("relevante") is True]

        # Los indeterminados no se pierden: se cuentan y viajan a la fila para que el
        # flag de revisión manual (ítem 10) tenga de dónde tirar.
        indeterminados = [c for c in graded if c.get("relevante") is None]

        # Phase 4: Análisis comparativo profundo
        analysis: ComparisonResult = self.grader.analyze_comparison(row, lexical, validated)

        return {
            **row,
            "estado_analisis": "ok",
            # Candidatos que el grading no pudo determinar. Insumo del ítem 10.
            "candidatos_indeterminados": len(indeterminados),
            "requiere_revision": bool(indeterminados),
            # Búsqueda
            "articulos_lexicos": [
                m.get("numero") for m in lexical if m.get("match_type") != "ambiguo"
            ],
            # La ambigüedad viaja a la fila en vez de perderse aquí: la necesitan el
            # modelo N:N (ítem 5), la cobertura de la Vía 2 (ítem 6) y el flag de
            # revisión manual (ítem 10).
            "articulos_lexicos_ambiguos": [
                {"numero": m.get("numero"), "doc_id": m.get("doc_id"),
                 "razon": m.get("razon_match", "")}
                for m in lexical if m.get("match_type") == "ambiguo"
            ],
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
    def _empty_result(estado: str = "error_parseo") -> dict:
        """Fila sin análisis utilizable.

        `nivel_cumplimiento` es **None**, no "no_aplica" (supuesto S2). La diferencia no
        es cosmética: "no aplica" es un veredicto —significa que se miró la sección y no
        hay norma que le aplique— y usarlo para señalar un fallo técnico convierte un
        error en una afirmación de auditoría. El motivo real viaja en `estado_analisis`.
        """
        return {
            "articulos_lexicos": [],
            "articulos_semanticos_raw": [],
            "articulos_validados": [],
            "tipo_coincidencia": None,
            "nivel_cumplimiento": None,
            "estado_analisis": estado,
            "analisis_lexico": None,
            "analisis_semantico_top1": None,
            "analisis_semantico_top2": None,
            "analisis_semantico_top3": None,
            "analisis_general": None,
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

"""Phase 3: Retrieve-then-Grade con LLM — LangChain + Docker Model Runner.

Modelo recomendado: docker.io/ai/gemma4:latest
  · Tiene razonamiento interno (chain-of-thought) antes de generar la respuesta
  · Requiere max_tokens >= 4096 para acomodar el pensamiento + el JSON de salida
  · La respuesta final (content) es el JSON estructurado; el reasoning_content
    queda en additional_kwargs y no afecta al parser

Pipeline (LCEL):
  prompt | ChatOpenAI | PydanticOutputParser

Flujo por sección del manual:
  1. grade_candidates()  → filtra Top-K FAISS por relevancia real
  2. analyze_comparison() → análisis comparativo profundo + NER + compliance
"""
from __future__ import annotations

import logging
from typing import Literal, Optional

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from .config import (
    DMR_BASE_URL,
    DMR_LLM_MODEL,
    LLM_GRADER_MAX_TOKENS,
    LLM_MAX_TOKENS,
    LLM_TEMPERATURE,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Modelos Pydantic para salidas estructuradas
# ──────────────────────────────────────────────────────────────────────────────

class CandidateGrade(BaseModel):
    """Evaluación de un candidato normativo individual."""
    element_id: str = Field(description="ID del fragmento evaluado")
    relevante: bool = Field(description="True si el candidato regula el mismo proceso/control")
    score: float = Field(ge=0.0, le=1.0, description="Score de relevancia 0.0–1.0")
    razon: str = Field(description="Justificación en máximo 100 caracteres")


class GradingResult(BaseModel):
    """Resultado del grading de candidatos FAISS."""
    candidatos: list[CandidateGrade]


class ComparisonResult(BaseModel):
    """Análisis comparativo completo de una sección del manual vs la normativa."""

    tipo_coincidencia: Literal["lexica", "semantica", "ninguna"] = Field(
        description="lexica: art. referenciado directamente | semantica: match por significado | ninguna"
    )
    nivel_cumplimiento: Literal["cumple", "parcial", "omision", "no_aplica"] = Field(
        description="cumple: implementado correctamente | parcial: incompleto | omision: no abordado | no_aplica"
    )
    analisis_lexico: Optional[str] = Field(
        None,
        description="Análisis de la coincidencia léxica (solo si tipo_coincidencia=lexica)"
    )
    analisis_semantico_top1: Optional[str] = Field(
        None,
        description="Análisis comparativo con el candidato semántico más relevante"
    )
    analisis_semantico_top2: Optional[str] = Field(
        None,
        description="Análisis comparativo con el segundo candidato semántico"
    )
    analisis_semantico_top3: Optional[str] = Field(
        None,
        description="Análisis comparativo con el tercer candidato semántico"
    )
    analisis_general: str = Field(
        description="Evaluación general: modificaciones, incumplimientos u omisiones detectadas"
    )
    brechas: list[str] = Field(
        default_factory=list,
        description="Lista de brechas o discrepancias específicas identificadas"
    )
    ner_general: list[str] = Field(
        default_factory=list,
        description="Entidades nombradas generales (organizaciones, personas, fechas)"
    )
    entidades_financieras: list[str] = Field(
        default_factory=list,
        description="Entidades financieras: montos, tasas, plazos, productos, límites"
    )
    entidades_normativas: list[str] = Field(
        default_factory=list,
        description="Referencias normativas: artículos, resoluciones, leyes, circulares"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Prompts del sistema
# ──────────────────────────────────────────────────────────────────────────────

_SYS_GRADER = (
    "Eres un especialista en cumplimiento normativo bancario ecuatoriano. "
    "Evalúas si fragmentos de normativas regulatorias (SBS, BCE, SEPS, UAF) son "
    "relevantes para secciones específicas de manuales internos bancarios. "
    "Responde ÚNICAMENTE con el JSON solicitado, sin texto adicional."
)

_SYS_ANALYST = (
    "Eres un analista experto en cumplimiento normativo bancario ecuatoriano. "
    "Realizas análisis comparativos profundos entre normativas de entes de control "
    "(SBS, BCE, SEPS, UAF) y manuales internos de bancos. "
    "Identificas modificaciones, brechas, omisiones e incumplimientos. "
    "Responde ÚNICAMENTE con el JSON solicitado, sin texto adicional."
)

_GRADER_USER = """\
Evalúa la relevancia de los candidatos normativos para la sección del manual.

=== SECCIÓN DEL MANUAL INTERNO ===
{manual_text}

=== CANDIDATOS NORMATIVOS (recuperados por FAISS) ===
{candidates_text}

Un candidato es RELEVANTE si regula el mismo proceso, control o actividad que describe el manual.
Es IRRELEVANTE si coincidió por palabras genéricas pero trata un tema diferente.

{format_instructions}"""

_ANALYST_USER = """\
Analiza comparativamente esta sección del manual interno contra la normativa regulatoria ecuatoriana.

=== SECCIÓN DEL MANUAL ===
Jerarquía: {jerarquia}
{manual_text}

=== NORMATIVA DE REFERENCIA ===
{referencias}

=== INSTRUCCIÓN ===
{instruccion}

Genera un análisis que incluya:
1. Comparación directa norma vs manual (coincidencias y diferencias)
2. Identificación de brechas: aspectos de la norma no cubiertos en el manual
3. Nivel de cumplimiento general
4. Extracción de todas las entidades relevantes

{format_instructions}"""


class LLMGrader:
    """Grader y analizador comparativo usando LangChain + Docker Model Runner.

    Usa gemma4 (modelo con razonamiento interno) para análisis profundo de
    normativas bancarias ecuatorianas contra manuales internos.

    Parámetros:
        model             : ID del modelo en DMR (default: docker.io/ai/gemma4:latest)
        base_url          : Endpoint DMR (default: http://localhost:12434/engines/v1)
        temperature       : 0.0 para respuestas deterministas (recomendado)
        max_tokens        : Presupuesto de tokens del análisis comparativo (default: LLM_MAX_TOKENS)
        grader_max_tokens : Presupuesto de tokens del grading de candidatos (default: LLM_GRADER_MAX_TOKENS)
    """

    def __init__(
        self,
        model: str = DMR_LLM_MODEL,
        base_url: str = DMR_BASE_URL,
        temperature: float = LLM_TEMPERATURE,
        max_tokens: int = LLM_MAX_TOKENS,
        grader_max_tokens: int = LLM_GRADER_MAX_TOKENS,
    ) -> None:
        self._llm_grader = ChatOpenAI(
            model=model,
            base_url=base_url,
            api_key="ignored",
            temperature=temperature,
            max_tokens=grader_max_tokens,
            timeout=120,   # gemma4 CoT puede tardar; 2 min es suficiente para grading
            max_retries=0,
        )
        self._llm_analyst = ChatOpenAI(
            model=model,
            base_url=base_url,
            api_key="ignored",
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=180,   # análisis comparativo puede requerir más tokens de razonamiento
            max_retries=0,
        )
        self._build_chains()

    def _build_chains(self) -> None:
        grader_parser = PydanticOutputParser(pydantic_object=GradingResult)
        grader_prompt = ChatPromptTemplate.from_messages([
            ("system", _SYS_GRADER),
            ("human", _GRADER_USER),
        ]).partial(format_instructions=grader_parser.get_format_instructions())
        self._grading_chain = grader_prompt | self._llm_grader | grader_parser

        analyst_parser = PydanticOutputParser(pydantic_object=ComparisonResult)
        analyst_prompt = ChatPromptTemplate.from_messages([
            ("system", _SYS_ANALYST),
            ("human", _ANALYST_USER),
        ]).partial(format_instructions=analyst_parser.get_format_instructions())
        self._analysis_chain = analyst_prompt | self._llm_analyst | analyst_parser

    # ── API pública ───────────────────────────────────────────────────────

    def grade_candidates(
        self,
        manual_text: str,
        candidates: list[dict],
    ) -> list[dict]:
        """Evalúa candidatos FAISS y retorna lista enriquecida con relevance scores.

        Cada candidato recibe: 'relevante' (bool), 'score_grade' (float), 'razon_grade' (str).
        """
        if not candidates:
            return []

        candidates_text = self._format_candidates(candidates)
        try:
            result: GradingResult = self._grading_chain.invoke({
                "manual_text": manual_text[:1500],
                "candidates_text": candidates_text,
            })
        except Exception as e:
            logger.warning("Grading falló (%s). Se asumen todos relevantes.", e)
            return [{**c, "relevante": True, "score_grade": 0.5, "razon_grade": ""} for c in candidates]

        grade_map = {g.element_id: g for g in result.candidatos}
        enriched = []
        for c in candidates:
            eid = c.get("element_id", c.get("chunk_id", ""))
            grade = grade_map.get(eid)
            enriched.append({
                **c,
                "relevante": grade.relevante if grade else True,
                "score_grade": grade.score if grade else 0.5,
                "razon_grade": grade.razon if grade else "",
            })
        return enriched

    def analyze_comparison(
        self,
        manual_row: dict,
        lexical_matches: list[dict],
        validated_candidates: list[dict],
    ) -> ComparisonResult:
        """Genera análisis comparativo completo para una sección del manual.

        Reglas de combinación:
          - Si hay coincidencia léxica → basa el análisis en ella (prioridad)
          - Si hay candidatos semánticos validados → analiza Top 1/2/3
          - Si no hay nada → evalúa omisión o sección sin norma aplicable
        """
        manual_text = manual_row.get("texto", manual_row.get("contenido", ""))
        jerarquia = manual_row.get("jerarquia", manual_row.get("seccion", ""))

        has_lexical = bool(lexical_matches)
        relevant = [c for c in validated_candidates if c.get("relevante", True)]
        has_semantic = bool(relevant)

        tipo = "lexica" if has_lexical else ("semantica" if has_semantic else "ninguna")

        referencias = self._build_referencias(lexical_matches, relevant)
        instruccion = {
            "lexica": "Basa el análisis en las coincidencias léxicas (artículos referenciados directamente). "
                      "Compara punto a punto la normativa vs el manual.",
            "semantica": "Basa el análisis en los candidatos semánticos validados (Top 1, 2, 3). "
                         "Evalúa qué tan bien el manual implementa cada artículo.",
            "ninguna": "No existen normas relacionadas. Determina si es una omisión del manual "
                       "o si esta sección genuinamente no tiene norma aplicable.",
        }[tipo]

        try:
            result: ComparisonResult = self._analysis_chain.invoke({
                "jerarquia": jerarquia or "(sin jerarquía)",
                "manual_text": manual_text[:2000],
                "referencias": referencias,
                "instruccion": instruccion,
            })
            result.tipo_coincidencia = tipo
            return result
        except Exception as e:
            logger.error("Análisis falló para '%s': %s", jerarquia, e)
            return ComparisonResult(
                tipo_coincidencia=tipo,
                nivel_cumplimiento="no_aplica",
                analisis_general=f"Error en análisis LLM: {e}",
            )

    # ── Helpers privados ─────────────────────────────────────────────────

    @staticmethod
    def _format_candidates(candidates: list[dict]) -> str:
        parts = []
        for i, c in enumerate(candidates, 1):
            eid = c.get("element_id", c.get("chunk_id", f"C{i}"))
            num = c.get("numero", "?")
            enc = c.get("encabezado", "")
            body = str(c.get("contenido", c.get("texto", "")))[:600]
            sim = c.get("similarity", 0)
            parts.append(
                f"[{i}] ID={eid} | Art.{num}: {enc} (sim={sim:.3f})\n{body}"
            )
        return "\n\n".join(parts)

    @staticmethod
    def _build_referencias(
        lexical: list[dict],
        semantic: list[dict],
    ) -> str:
        parts = []
        if lexical:
            lm_text = "\n\n".join(
                f"Artículo {m.get('numero','?')}: {m.get('encabezado','')}\n"
                f"{str(m.get('contenido',''))[:800]}"
                for m in lexical[:3]
            )
            parts.append(f"COINCIDENCIAS LÉXICAS:\n{lm_text}")
        if semantic:
            sem_text = "\n\n".join(
                f"[Top {i+1}] Art.{c.get('numero','?')}: {c.get('encabezado','')}\n"
                f"{str(c.get('contenido',''))[:600]}"
                for i, c in enumerate(semantic[:3])
            )
            parts.append(f"CANDIDATOS SEMÁNTICOS VALIDADOS:\n{sem_text}")
        if not parts:
            parts.append("Sin artículos normativos relevantes identificados.")
        return "\n\n".join(parts)

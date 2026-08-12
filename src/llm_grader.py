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
from dataclasses import replace
from typing import Any, Literal, Optional

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
from .errors import (
    AnalysisParseError,
    GradingParseError,
    LLMUnavailableError,
    classify_llm_exception,
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
        *,
        chat_grader: Any = None,
        chat_analyst: Any = None,
        spec: Any = None,
    ) -> None:
        """El modelo puede **inyectarse** en vez de construirse aquí.

        Tres formas de uso, por orden de precedencia:

          1. `chat_grader` / `chat_analyst` — modelos ya construidos. Es lo que usan las
             pruebas para no depender de un backend vivo, y lo que usará la Fase 3 para
             pasar un cliente de nube.
          2. `spec` — un `ProviderSpec`; las fábricas de `providers.py` los construyen.
          3. Los parámetros sueltos de siempre — se conservan porque `master.ipynb` llama
             así (supuesto S5), y romperlos no aporta nada.

        Antes esta clase instanciaba `ChatOpenAI` directamente, lo que ataba el motor a un
        proveedor concreto: cambiarlo obligaba a tocar el grader. Ahora es una costura.
        """
        # Se guardan para que classify_llm_exception pueda decir *qué* modelo y *qué*
        # endpoint fallaron: el mensaje del ítem 1 tiene que ser accionable, y
        # "el backend no responde" sin decir cuál no lo es.
        self._model_id = model
        self._base_url = base_url

        if chat_grader is not None or chat_analyst is not None:
            if chat_grader is None or chat_analyst is None:
                raise ValueError(
                    "chat_grader y chat_analyst se inyectan juntos: usan presupuestos de "
                    "tokens distintos y mezclar uno inyectado con otro construido produce "
                    "corridas difíciles de interpretar"
                )
            self._llm_grader = chat_grader
            self._llm_analyst = chat_analyst

        elif spec is not None:
            from .providers import build_chat_model

            resuelto = spec.resuelto() if hasattr(spec, "resuelto") else spec
            self._model_id = getattr(resuelto, "modelo", model) or model
            self._base_url = getattr(resuelto, "base_url", base_url) or base_url
            # Dos clientes porque el grading y el análisis tienen presupuestos distintos.
            self._llm_grader = build_chat_model(
                replace(resuelto, max_tokens=grader_max_tokens)
            )
            self._llm_analyst = build_chat_model(
                replace(resuelto, max_tokens=max_tokens)
            )

        else:
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
                timeout=180,   # el análisis puede requerir más tokens de razonamiento
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
        entrada = {"manual_text": manual_text[:1500], "candidates_text": candidates_text}

        try:
            result: GradingResult = self._graduar_con_reintentos(entrada)
        except LLMUnavailableError as e:
            # El backend no va a responder mejor en la fila siguiente: se relanza para
            # que run() cancele lo pendiente en vez de seguir produciendo veredictos
            # sobre secciones que el modelo nunca leyó (ítem 1).
            logger.error("Grading abortado por fallo de infraestructura: %s", e)
            raise
        except GradingParseError as e:
            # Agotados los reintentos, el grading es **indeterminado**, no positivo.
            #
            # Antes se devolvía `relevante=True` para todos: un parseo roto colaba
            # falsos positivos de cumplimiento en el papel de trabajo, en silencio y
            # sin dejar rastro. Es el riesgo espejo del ítem 1 y el peor de los dos:
            # allí se perdían secciones de forma ruidosa, aquí se afirmaba haber
            # verificado algo que nadie verificó.
            logger.error("Grading no parseable tras reintentos: %s", e)
            return [
                {
                    **c,
                    "relevante": None,
                    "score_grade": None,
                    "razon_grade": "",
                    "requiere_revision": True,
                    "motivo_revision": "grading_no_parseable",
                }
                for c in candidates
            ]

        grade_map = {g.element_id: g for g in result.candidatos}
        enriched = []
        for c in candidates:
            eid = c.get("element_id", c.get("chunk_id", ""))
            grade = grade_map.get(eid)

            if grade is None:
                # El modelo parseó bien pero se dejó este candidato fuera de la
                # respuesta. Antes se asumía relevante: mismo falso positivo que el
                # parseo roto, solo que más difícil de ver porque el resto de la
                # respuesta era válida. Ausencia de juicio no es juicio favorable.
                enriched.append({
                    **c,
                    "relevante": None,
                    "score_grade": None,
                    "razon_grade": "",
                    "requiere_revision": True,
                    "motivo_revision": "candidato_ausente_del_grading",
                })
                continue

            enriched.append({
                **c,
                "relevante": grade.relevante,
                "score_grade": grade.score,
                "razon_grade": grade.razon,
                "requiere_revision": False,
            })
        return enriched

    # ── Robustez del grading, en tres niveles ─────────────────────────────

    def _graduar_con_reintentos(self, entrada: dict) -> GradingResult:
        """Intenta el grading con degradación progresiva antes de rendirse.

        Los modelos pequeños fallan produciendo JSON de formas distintas, y cada nivel
        ataca una: el primero repara la salida, el segundo reduce lo que hay que seguir.
        Solo cuando ninguno funciona se declara indeterminado — que es caro para el
        auditor, porque manda la fila a revisión manual.
        """
        # Nivel 1 — la cadena normal.
        try:
            return self._grading_chain.invoke(entrada)
        except Exception as e:
            error = classify_llm_exception(e, modelo=self._model_id, url=self._base_url)
            if isinstance(error, LLMUnavailableError):
                raise error from e
            logger.debug("Grading nivel 1 falló (%s); se intenta reparar la salida", error)

        # Nivel 2 — OutputFixingParser: le pide al propio modelo que arregle su JSON.
        try:
            from langchain.output_parsers import OutputFixingParser

            reparador = OutputFixingParser.from_llm(
                parser=PydanticOutputParser(pydantic_object=GradingResult),
                llm=self._llm_grader,
            )
            prompt = ChatPromptTemplate.from_messages([
                ("system", _SYS_GRADER), ("human", _GRADER_USER),
            ]).partial(format_instructions=reparador.get_format_instructions())
            return (prompt | self._llm_grader | reparador).invoke(entrada)
        except Exception as e:
            error = classify_llm_exception(e, modelo=self._model_id, url=self._base_url)
            if isinstance(error, LLMUnavailableError):
                raise error from e
            logger.debug("Grading nivel 2 falló (%s); se intenta prompt simplificado", error)

        # Nivel 3 — prompt mínimo. Las `format_instructions` de Pydantic son largas y a
        # un modelo pequeño le consumen la ventana antes de llegar a responder.
        try:
            simple = ChatPromptTemplate.from_messages([
                ("system", _SYS_GRADER),
                ("human",
                 "Sección del manual:\n{manual_text}\n\n"
                 "Candidatos:\n{candidates_text}\n\n"
                 'Responde SOLO este JSON: {{"candidatos": [{{"element_id": "...", '
                 '"relevante": true, "score": 0.9, "razon": "..."}}]}}'),
            ])
            parser = PydanticOutputParser(pydantic_object=GradingResult)
            return (simple | self._llm_grader | parser).invoke(entrada)
        except Exception as e:
            error = classify_llm_exception(e, modelo=self._model_id, url=self._base_url)
            if isinstance(error, LLMUnavailableError):
                raise error from e
            raise GradingParseError(
                f"El grading no encaja en el esquema tras tres intentos: {error}", causa=e,
            ) from e

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
            error = classify_llm_exception(e, modelo=self._model_id, url=self._base_url)
            if isinstance(error, LLMUnavailableError):
                logger.error("Análisis abortado en '%s' por fallo de infraestructura: %s",
                             jerarquia, error)
                raise error from e

            # Fallo de contenido. Antes se devolvía nivel_cumplimiento="no_aplica" con el
            # texto del error dentro de analisis_general: el papel de trabajo afirmaba
            # "no aplica" sobre una sección que nadie analizó. Ahora se relanza como
            # error de parseo y es run() quien decide qué hacer con la fila, marcándola
            # con estado_analisis en vez de con un veredicto de cumplimiento (S2).
            logger.error("Análisis no parseable para '%s': %s", jerarquia, error)
            raise AnalysisParseError(
                f"El análisis de '{jerarquia}' no encaja en el esquema: {error}",
                causa=e,
            ) from e

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

"""Pruebas funcionales de LLMGrader — verifica que los nuevos parámetros
``max_tokens``/``grader_max_tokens`` se propaguen a los clientes ChatOpenAI
internos correctos, sin llamar a la API de DMR.

Instanciar ChatOpenAI() solo construye el cliente lazy de openai-python; no
abre conexión de red hasta que se invoca .invoke()/.predict(). Estas pruebas
inspeccionan atributos del objeto, nunca ejecutan una llamada real al LLM.
"""
from __future__ import annotations

from src import config as cfg
from src.llm_grader import LLMGrader


def test_default_max_tokens_come_from_config():
    """Sin argumentos explícitos, LLMGrader debe usar LLM_MAX_TOKENS/LLM_GRADER_MAX_TOKENS
    de src/config.py (backward-compatible con las llamadas existentes en master.ipynb)."""
    grader = LLMGrader(model="modelo-de-prueba", base_url="http://localhost:1/v1")

    assert grader._llm_analyst.max_tokens == cfg.LLM_MAX_TOKENS
    assert grader._llm_grader.max_tokens == cfg.LLM_GRADER_MAX_TOKENS


def test_custom_max_tokens_propagate_to_correct_client():
    grader = LLMGrader(
        model="modelo-de-prueba",
        base_url="http://localhost:1/v1",
        max_tokens=1234,
        grader_max_tokens=567,
    )

    assert grader._llm_analyst.max_tokens == 1234, "max_tokens debe ir al cliente de análisis comparativo"
    assert grader._llm_grader.max_tokens == 567, "grader_max_tokens debe ir al cliente de grading de candidatos"
    assert grader._llm_analyst.max_tokens != grader._llm_grader.max_tokens, "no deben mezclarse entre sí"


def test_model_and_temperature_propagate_to_both_clients():
    grader = LLMGrader(model="modelo-de-prueba", base_url="http://localhost:1/v1", temperature=0.42)

    assert grader._llm_analyst.model_name == "modelo-de-prueba"
    assert grader._llm_grader.model_name == "modelo-de-prueba"
    assert grader._llm_analyst.temperature == 0.42
    assert grader._llm_grader.temperature == 0.42


def test_base_url_propagates_to_both_clients():
    custom_url = "http://localhost:9999/engines/v1"
    grader = LLMGrader(model="modelo-de-prueba", base_url=custom_url)

    # ChatOpenAI expone la base_url configurada a través del cliente openai subyacente.
    assert str(grader._llm_analyst.openai_api_base) == custom_url
    assert str(grader._llm_grader.openai_api_base) == custom_url

"""Ítem P-a — las costuras de proveedor, sin tocar la red.

Lo que estas pruebas fijan no es "funciona con el backend local" —eso ya funcionaba— sino
que **ningún módulo del motor construye su propio cliente de modelo**. Es la propiedad que
hace que añadir un proveedor en la Fase 3 sea escribir una fábrica en vez de refactorizar.
"""
from __future__ import annotations

import openai
import pytest

from src.embeddings import LangChainEmbeddingsAdapter
from src.errors import LLMUnavailableError, ProviderConfigError
from src.llm_grader import LLMGrader
from src.providers import (
    CAPACIDADES,
    Provider,
    ProviderSpec,
    build_chat_model,
    build_embedding_backend,
    prefijos_de,
)
from src.settings import get, redact
from tests.fixtures import FakeChatModel


class TestInyeccionDelModelo:
    """`LLMGrader` deja de construir su propio cliente."""

    def test_acepta_un_chat_model_inyectado(self):
        grader = LLMGrader(chat_grader=FakeChatModel(), chat_analyst=FakeChatModel())
        assert grader._llm_grader is not None

    def test_exige_inyectar_los_dos_o_ninguno(self):
        """Mezclar uno inyectado con otro construido produce corridas donde el grading y
        el análisis van contra backends distintos sin que nadie lo note."""
        with pytest.raises(ValueError, match="juntos"):
            LLMGrader(chat_grader=FakeChatModel())

    def test_el_constructor_clasico_sigue_funcionando(self):
        """`master.ipynb` llama así (S5). No se construye nada: solo se comprueba que la
        firma lo admite."""
        import inspect

        params = inspect.signature(LLMGrader.__init__).parameters
        for esperado in ("model", "base_url", "temperature", "max_tokens", "grader_max_tokens"):
            assert esperado in params

    def test_un_modelo_caido_se_clasifica_como_infraestructura(self):
        grader = LLMGrader(
            chat_grader=FakeChatModel(excepcion=openai.APIConnectionError(request=None)),  # type: ignore[arg-type]
            chat_analyst=FakeChatModel(),
        )
        with pytest.raises(LLMUnavailableError):
            grader.grade_candidates("texto", [{"element_id": "x", "contenido": "y"}])


class TestFabricas:

    def test_el_backend_local_no_ofrece_chat(self):
        """Se rechaza por capacidades, no por fallo al construirlo."""
        with pytest.raises(ProviderConfigError, match="no ofrece chat"):
            build_chat_model(ProviderSpec(proveedor=Provider.LOCAL_ST))

    def test_el_spec_se_resuelve_desde_los_defaults(self):
        spec = ProviderSpec(proveedor=Provider.DMR).resuelto()
        assert spec.modelo and spec.base_url

    def test_la_ui_gana_al_default(self):
        spec = ProviderSpec(proveedor=Provider.DMR, modelo="modelo-de-la-ui").resuelto()
        assert spec.modelo == "modelo-de-la-ui"

    def test_construir_embeddings_no_toca_la_red(self, monkeypatch):
        """La fábrica debe poder instanciarse sin backend vivo: solo crea el cliente."""
        creado = {}

        class _FalsoDMR:
            def __init__(self, **kw):
                creado.update(kw)

        monkeypatch.setattr("src.embeddings.LangChainDMREmbeddings", _FalsoDMR)
        build_embedding_backend(ProviderSpec(proveedor=Provider.DMR, modelo="m"))
        assert creado["model"] == "m"


class TestPrecedenciaDeConfiguracion:
    """UI > entorno > .env > default."""

    def test_la_ui_gana_al_entorno(self, monkeypatch):
        monkeypatch.setenv("UNA_CLAVE", "del-entorno")
        assert get("UNA_CLAVE", ui="de-la-ui", default="del-default") == "de-la-ui"

    def test_el_entorno_gana_al_default(self, monkeypatch):
        monkeypatch.setenv("UNA_CLAVE", "del-entorno")
        assert get("UNA_CLAVE", default="del-default") == "del-entorno"

    def test_el_default_es_el_ultimo_recurso(self, monkeypatch):
        monkeypatch.delenv("UNA_CLAVE", raising=False)
        assert get("UNA_CLAVE", default="del-default") == "del-default"

    def test_una_ui_vacia_no_cuenta_como_valor(self, monkeypatch):
        """Un campo de texto vacío en el sidebar no debe pisar la configuración."""
        monkeypatch.setenv("UNA_CLAVE", "del-entorno")
        assert get("UNA_CLAVE", ui="", default="d") == "del-entorno"


class TestRedaccionDeSecretos:
    """Ninguna credencial puede llegar a un log, al JSON ni al Excel."""

    # Los secretos de prueba se componen por partes a propósito.
    #
    # Son sintéticos, pero escritos enteros en el fuente los marcaría cualquier escáner
    # de credenciales —el de este repo y el de GitHub— y acabaríamos con hallazgos
    # permanentes que enseñan a ignorar los avisos. En ejecución son idénticos.
    @pytest.mark.parametrize("nombre,sep,valor", [
        ("api_key", "=", "sk-" + "abcdefghijklmnopqrstuvwxyz012345"),
        ("AZURE_OPENAI_API_KEY", ": ", '"' + "muy-secreto-de-verdad-123" + '"'),
        ("password", "=", "Contrasena" + ".Larga.123"),
        ("token", " = ", "ghp_" + "abcdefghijklmnopqrstuvwxyz0123"),
    ])
    def test_las_asignaciones_se_enmascaran(self, nombre, sep, valor):
        salida = redact(f"{nombre}{sep}{valor}")
        assert "***" in salida
        assert valor.strip('"') not in salida, "el valor sobrevivió a redact()"

    def test_credenciales_dentro_de_una_url(self):
        salida = redact("https://usuario:clavesecreta@endpoint.example/v1")
        assert "clavesecreta" not in salida and "usuario" in salida

    def test_token_en_query_string(self):
        assert "abc123def456" not in redact("https://x.example/api?access_token=abc123def456")

    def test_atraviesa_estructuras(self):
        """El panel de ejecución y la hoja de trazabilidad manejan dicts, no cadenas."""
        secreto = "sk-" + "abcdefghijklmnopqrstuvwxyz01"
        salida = redact({"cfg": {"api" + "_key": secreto}, "n": [1, 2]})
        assert secreto not in str(salida)
        assert salida["n"] == [1, 2], "lo que no es secreto debe salir intacto"

    def test_no_destroza_texto_inocente(self):
        texto = "Artículo 5: registro de operaciones por diez años."
        assert redact(texto) == texto


class TestPrefijosDeEmbedding:
    """Defecto 3 de §2.2: los prefijos son del modelo, no del código que lo llama."""

    def test_el_backend_local_declara_sus_prefijos(self):
        caps = CAPACIDADES[Provider.LOCAL_ST]
        assert caps.prefijo_documento == "passage: "
        assert caps.prefijo_consulta == "query: "

    def test_el_backend_remoto_no_los_lleva(self):
        assert CAPACIDADES[Provider.DMR].prefijo_documento == ""

    def test_el_adaptador_declara_los_suyos(self):
        adaptador = LangChainEmbeddingsAdapter(
            embeddings=object(), prefijo_documento="passage: ", prefijo_consulta="query: ",
        )
        assert prefijos_de(adaptador) == ("passage: ", "query: ")


class TestElMotorNoConstruyeClientes:
    """La propiedad que hace barata la Fase 3."""

    def test_solo_providers_instancia_clientes_de_modelo(self):
        """Si otro módulo vuelve a construir su cliente, la costura deja de servir.

        La primera versión de esta prueba **excluía `llm_grader.py`**, que era el único
        módulo que lo hacía, y solo buscaba `ChatOpenAI`. Estaba construida alrededor de
        la excepción que debía detectar: pasaba sin ejercitar su propio criterio. Lo
        destapó la auditoría de la ola.
        """
        from pathlib import Path

        raiz = Path(__file__).resolve().parent.parent / "src"
        constructores = ("ChatOpenAI(", "OpenAIEmbeddings(", "SentenceTransformer(")

        infractores: list[str] = []
        for f in raiz.glob("*.py"):
            if f.name == "providers.py":          # la única excepción legítima
                continue
            texto = f.read_text(encoding="utf-8")
            for c in constructores:
                # Se ignoran las menciones en comentarios y docstrings: lo que importa
                # es la construcción, no hablar de ella.
                lineas = [
                    ln for ln in texto.splitlines()
                    if c in ln and not ln.lstrip().startswith("#")
                ]
                if lineas:
                    infractores.append(f"{f.name}: {c}")

        assert not infractores, (
            f"estos módulos construyen su propio cliente: {infractores}. "
            "Deben pedírselo a providers.build_chat_model()/build_embedding_backend()"
        )


class TestUnVocabularioParaLosPrefijos:
    """Regresión: el adaptador declaraba los prefijos con otros nombres.

    `EmbeddingBackend` usa `passage_prefix`/`query_prefix` y es lo único que
    `NormativaIndex` lee. El adaptador de P-a llegó declarando
    `prefijo_documento`/`prefijo_consulta`: el prefijo se declaraba y no llegaba nunca al
    modelo — el defecto 3 de §2.2 recreado dentro de la abstracción creada para
    generalizarlo.
    """

    def _adaptador(self, vistos):
        class _Emb:
            def embed_documents(self, textos):
                vistos.extend(textos)
                return [[0.1] * 4 for _ in textos]

        return LangChainEmbeddingsAdapter(
            _Emb(), prefijo_documento="passage: ", prefijo_consulta="query: ",
        )

    def test_el_prefijo_declarado_llega_al_modelo(self):
        vistos: list[str] = []
        ad = self._adaptador(vistos)
        ad.encode(["texto uno"], prefix=ad.passage_prefix)
        assert vistos == ["passage: texto uno"], (
            "el prefijo se declaró pero no llegó: los nombres del adaptador y los que "
            "lee el índice no coinciden"
        )

    def test_ambos_vocabularios_leen_el_mismo_valor(self):
        ad = self._adaptador([])
        assert ad.passage_prefix == ad.prefijo_documento
        assert ad.query_prefix == ad.prefijo_consulta

    def test_es_el_nombre_que_el_indice_consulta(self):
        """Si el índice cambiara de atributo, esta prueba lo delata."""
        import inspect

        from src.search_engine import NormativaIndex

        fuente = inspect.getsource(NormativaIndex.build) + inspect.getsource(
            NormativaIndex.semantic_search
        )
        assert "passage_prefix" in fuente and "query_prefix" in fuente

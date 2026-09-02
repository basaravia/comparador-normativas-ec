"""Backends de embeddings para búsqueda semántica FAISS.

Dos implementaciones:
  LangChainDMREmbeddings    → vía Docker Model Runner (OpenAI-compatible)
  SentenceTransformersEmbeddings → modelo local (intfloat/multilingual-e5-large)

Ambas retornan vectores L2-normalizados (float32) listos para IndexFlatIP.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence

import numpy as np

from .config import (
    DMR_BASE_URL,
    DMR_EMBED_MODEL,
    EMBED_BATCH_SIZE,
)


class EmbeddingBackend(ABC):
    """Interfaz base para backends de embedding.

    ``passage_prefix``/``query_prefix`` declaran, por backend, el prefijo que
    ``encode()`` espera recibir para documentos y para consultas respectivamente
    (defecto 3 de §2.2 del plan). El default es "": la mayoría de las APIs
    OpenAI-compatibles (DMR incluido) no lo necesitan y anteponerlo a ciegas
    degradaría sus embeddings. Un backend que sí lo requiera (p. ej. modelos
    E5) lo declara sobreescribiendo estos atributos — quien construye el
    índice (`NormativaIndex`) los lee del backend en vez de decidir por él.
    """

    passage_prefix: str = ""
    query_prefix: str = ""

    @abstractmethod
    def encode(self, texts: Sequence[str], prefix: str = "") -> np.ndarray:
        """Retorna embeddings L2-normalizados, shape (len(texts), dim)."""

    @property
    @abstractmethod
    def dim(self) -> int:
        """Dimensionalidad del espacio de embedding."""

    def _l2_normalize(self, arr: np.ndarray) -> np.ndarray:
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        return (arr / norms).astype(np.float32)


class LangChainEmbeddingsAdapter(EmbeddingBackend):
    """Envuelve cualquier objeto `Embeddings` de LangChain en la interfaz del proyecto.

    Es la costura que hace que añadir un proveedor de embeddings no requiera escribir una
    clase nueva: Azure, Vertex o cualquier otro exponen `Embeddings` de LangChain, y desde
    aquí entran con batching y normalización L2 ya resueltos.

    `LangChainDMREmbeddings` queda como un caso particular de esto.
    """

    def __init__(
        self,
        embeddings: object,
        *,
        batch_size: int = EMBED_BATCH_SIZE,
        prefijo_documento: str = "",
        prefijo_consulta: str = "",
        nombre_modelo: str = "desconocido",
    ) -> None:
        self._embedder = embeddings
        self._batch_size = batch_size
        self._dim: int | None = None
        self.nombre_modelo = nombre_modelo

        # Los prefijos son del modelo, no del código que lo llama.
        #
        # `passage_prefix`/`query_prefix` son los nombres de `EmbeddingBackend` y los
        # únicos que `NormativaIndex` lee. Este adaptador llegó declarando
        # `prefijo_documento`/`prefijo_consulta`, un segundo vocabulario en el mismo
        # archivo: el prefijo se declaraba y no llegaba nunca al modelo — el defecto 3
        # de §2.2 recreado justo dentro de la abstracción creada para generalizarlo.
        #
        # Manda el nombre de la clase base. Los alias en español se conservan como
        # propiedades de solo lectura para no romper a quien ya los use, pero no son
        # una segunda fuente: ambos leen el mismo atributo.
        self.passage_prefix = prefijo_documento
        self.query_prefix = prefijo_consulta

    @property
    def prefijo_documento(self) -> str:
        return self.passage_prefix

    @property
    def prefijo_consulta(self) -> str:
        return self.query_prefix

    def encode(self, texts: Sequence[str], prefix: str = "") -> np.ndarray:
        textos = [f"{prefix}{t}" if prefix else t for t in texts]
        vecs: list[list[float]] = []
        for i in range(0, len(textos), self._batch_size):
            vecs.extend(self._embedder.embed_documents(textos[i: i + self._batch_size]))

        arr = np.array(vecs, dtype=np.float32)
        if self._dim is None and arr.size > 0:
            self._dim = arr.shape[1]
        return self._l2_normalize(arr)

    @property
    def dim(self) -> int:
        if self._dim is None:
            self._dim = len(self._embedder.embed_query("dimension"))
        return self._dim


class LangChainDMREmbeddings(EmbeddingBackend):
    """Embeddings via Docker Model Runner usando la API OpenAI-compatible.

    Modelos recomendados (orden de preferencia para español legal):
      1. ai/qwen3-embedding:latest        → 2560 dim, mejor calidad
      2. ai/granite-embedding-multilingual:latest → 768 dim, más rápido
    """

    # Los modelos de embedding servidos por DMR (qwen3-embedding, granite) no
    # son de la familia E5: no esperan "passage: "/"query: ". Se declaran
    # explícitos (en vez de heredar el default en silencio) para que quede
    # documentado por qué este backend no los usa.
    passage_prefix = ""
    query_prefix = ""

    def __init__(
        self,
        model: str = DMR_EMBED_MODEL,
        base_url: str = DMR_BASE_URL,
        api_key: str = "ignored",
        batch_size: int = EMBED_BATCH_SIZE,
    ) -> None:
        # El cliente lo construye providers.py, no esta clase. Antes se instanciaba
        # `OpenAIEmbeddings` aquí, de modo que la costura existía sin que el camino real
        # pasara por ella — el DoD de P-a decía justo lo contrario.
        from .providers import construir_embeddings_openai

        self._model = model
        self.nombre_modelo = model
        self._batch_size = batch_size
        self._embedder = construir_embeddings_openai(
            model=model, base_url=base_url, api_key=api_key,
        )
        self._dim: int | None = None

    def encode(self, texts: Sequence[str], prefix: str = "") -> np.ndarray:
        texts = [f"{prefix}{t}" if prefix else t for t in texts]
        all_vecs: list[list[float]] = []

        for i in range(0, len(texts), self._batch_size):
            batch = texts[i: i + self._batch_size]
            all_vecs.extend(self._embedder.embed_documents(batch))

        arr = np.array(all_vecs, dtype=np.float32)
        if self._dim is None and arr.size > 0:
            self._dim = arr.shape[1]
        return self._l2_normalize(arr)

    def encode_query(self, text: str, prefix: str = "query: ") -> np.ndarray:
        """Encode de una consulta (sin batching, con prefijo de query)."""
        vec = self._embedder.embed_query(f"{prefix}{text}" if prefix else text)
        arr = np.array([vec], dtype=np.float32)
        return self._l2_normalize(arr)

    @property
    def dim(self) -> int:
        if self._dim is None:
            self.encode(["ping"])
        return self._dim  # type: ignore[return-value]

    @property
    def model_name(self) -> str:
        return self._model


class SentenceTransformersEmbeddings(EmbeddingBackend):
    """Embeddings locales via sentence-transformers.

    Modelo recomendado: intfloat/multilingual-e5-large
    Requiere prefijos: "passage: " para documentos, "query: " para búsquedas.
    """

    passage_prefix = "passage: "
    query_prefix = "query: "

    def __init__(
        self,
        model_name: str = "intfloat/multilingual-e5-large",
        device: str = "auto",
        batch_size: int = EMBED_BATCH_SIZE,
    ) -> None:
        from .providers import construir_sentence_transformer

        _device = self._resolve_device(device)
        self._model = construir_sentence_transformer(model_name=model_name, device=_device)
        self._batch_size = batch_size
        # El identificador del modelo, como string. `_model` es el objeto cargado, no su
        # nombre, y `index_meta.json` necesita algo serializable para poder rechazar
        # después un índice construido con otro modelo.
        self.nombre_modelo = model_name

    def encode(
        self,
        texts: Sequence[str],
        prefix: str = "passage: ",
    ) -> np.ndarray:
        prefixed = [f"{prefix}{t}" for t in texts]
        vecs = self._model.encode(
            prefixed,
            batch_size=self._batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return np.array(vecs, dtype=np.float32)

    @property
    def dim(self) -> int:
        return self._model.get_sentence_embedding_dimension()  # type: ignore[return-value]

    @staticmethod
    def _resolve_device(device: str) -> str:
        # Delegado a providers.resolve_device: implementarlo aquí también duplicaría el
        # chequeo de que el wheel de torch trae kernels para la GPU presente (no solo
        # que hay driver), que es lo que corrigió el bug de "auto" cayendo a una CUDA
        # que en realidad no podía ejecutar nada en esta máquina (GTX 960M, sm_50 no
        # cubierto por los wheels recientes).
        from .providers import resolve_device

        return resolve_device(device)

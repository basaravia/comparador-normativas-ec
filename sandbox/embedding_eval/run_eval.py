"""Evaluación aislada: ¿qué modelo de embedding discrimina mejor entre secciones de
manual de control interno y artículos de normativa bancaria en español?

NO es parte del pipeline de producción (src/) ni se importa desde ahí. Vive en la rama
`sandbox/embedding-eval`, pensada para descartarse una vez que la comparación informe
la elección — ver sandbox/embedding_eval/README.md.

Metodología (100% LangChain, igual que src/providers.py):
  1. Por cada modelo candidato, se instancia su clase oficial de LangChain
     (`OpenAIEmbeddings` para los servidos por Ollama vía su endpoint OpenAI-compat,
     `VertexAIEmbeddings` para Vertex, `HuggingFaceEmbeddings` para el local).
  2. Se indexan los 14 artículos de NORMATIVA con `langchain_community.vectorstores.FAISS`,
     configurado igual que la producción (`src/search_engine.py`): coseno vía
     `DistanceStrategy.MAX_INNER_PRODUCT` sobre vectores L2-normalizados — NO la
     distancia euclidiana que LangChain usa por defecto.
  3. Se consulta con las 14 secciones de manual (parafraseadas a propósito, ver
     corpus.py) y se mide en qué posición del ranking aparece el artículo correcto.

Métricas por modelo:
  - top1 / top3: cuántas de las 14 consultas acertaron el artículo correcto en
    posición 1 / dentro del top-3.
  - MRR (Mean Reciprocal Rank): 1/rank promediado — penaliza más un acierto en
    posición 3 que uno en posición 2, a diferencia de top-3 que los trata igual.
  - margen: score_coseno(correcto) - score_coseno(mejor incorrecto). Positivo y grande
    = separación clara; negativo = el modelo puso un artículo equivocado por delante.

Uso:
    source .venv/bin/activate
    pip install -r sandbox/embedding_eval/requirements.txt   # deps propias del sandbox
    python sandbox/embedding_eval/run_eval.py
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # raíz del repo, para importar src.config

from corpus import MANUAL_QUERIES, NORMATIVA  # noqa: E402

from langchain_community.vectorstores import FAISS  # noqa: E402
from langchain_community.vectorstores.utils import DistanceStrategy  # noqa: E402
from langchain_core.embeddings import Embeddings  # noqa: E402

from src import config as cfg  # noqa: E402


# ──────────────────────────────────────────────────────────────────────────────
# Modelos candidatos
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class Candidato:
    nombre: str
    dim_esperada: int
    costo: str  # "gratis (GPU local)" | "pago (API cloud)"
    build: "callable"
    notas: str = ""


def _ollama_embeddings(model: str):
    from langchain_openai import OpenAIEmbeddings

    return OpenAIEmbeddings(
        model=model, base_url=cfg.OLLAMA_BASE_URL, api_key="ignored",
        check_embedding_ctx_length=False,
    )


def _vertex_embeddings(model: str, location: str):
    from langchain_google_vertexai import VertexAIEmbeddings

    return VertexAIEmbeddings(model_name=model, project=cfg.VERTEX_PROJECT_ID, location=location)


class E5Embeddings(Embeddings):
    """Envoltorio LangChain-compatible para intfloat/multilingual-e5-large.

    E5 exige los prefijos "passage: "/"query: " en el texto (defecto documentado en
    src/embeddings.py — SentenceTransformersEmbeddings ya lo hace para el pipeline
    de producción); HuggingFaceEmbeddings de LangChain no los añade por su cuenta.

    Hereda de `Embeddings` (no un objeto "duck-typed" cualquiera): `FAISS.from_texts`
    detecta la subclase por `isinstance`, y sin ella cae a su ruta legada de
    "embedding_function callable" — que para esta clase (sin `__call__`) rompe con
    "object is not callable" en vez de usar embed_documents/embed_query.
    """

    def __init__(self, model_name: str, device: str):
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name, device=device)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vecs = self._model.encode([f"passage: {t}" for t in texts], normalize_embeddings=True)
        return vecs.tolist()

    def embed_query(self, text: str) -> list[float]:
        vec = self._model.encode(f"query: {text}", normalize_embeddings=True)
        return vec.tolist()


def _local_e5_embeddings():
    from src.providers import resolve_device

    return E5Embeddings("intfloat/multilingual-e5-large", device=resolve_device("auto"))


CANDIDATOS: list[Candidato] = [
    Candidato(
        "ollama/qwen3-embedding:0.6b", 1024, "gratis (GPU local)",
        lambda: _ollama_embeddings("qwen3-embedding:0.6b"),
        "Default actual del pipeline (src/config.py). El tag recomendado originalmente "
        "(qwen3-embedding:latest/8b, 2560d) no cabe en 4GB VRAM — ver dependencies/README.md.",
    ),
    Candidato(
        "ollama/bge-m3", 1024, "gratis (GPU local)",
        lambda: _ollama_embeddings("bge-m3"),
        "Alternativa ya descargada; multilingüe, buen desempeño reportado en benchmarks públicos.",
    ),
    Candidato(
        "vertex/text-multilingual-embedding-002", 768, "pago (API cloud)",
        lambda: _vertex_embeddings("text-multilingual-embedding-002", cfg.VERTEX_EMBED_LOCATION),
        "Multilingüe dedicado de Google. location='us-central1', no 'global' (ver config.py).",
    ),
    Candidato(
        "vertex/gemini-embedding-001", 3072, "pago (API cloud)",
        lambda: _vertex_embeddings("gemini-embedding-001", cfg.VERTEX_EMBED_LOCATION),
        "Basado en Gemini, mayor dimensión — cota superior de calidad/costo a comparar.",
    ),
    Candidato(
        "local/multilingual-e5-large", 1024, "gratis (CPU local)",
        _local_e5_embeddings,
        "Era el default de SentenceTransformersEmbeddings antes de esta rama (Provider.LOCAL_ST). "
        "CPU, no GPU: el wheel de torch instalado no soporta esta GPU (ver providers.resolve_device).",
    ),
]


# ──────────────────────────────────────────────────────────────────────────────
# Evaluación
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class ResultadoConsulta:
    espera_id: str
    rank_correcto: int  # 1-indexado; None-like -1 si no aparece (no debería pasar, k=len(corpus))
    score_correcto: float
    mejor_incorrecto_id: str
    mejor_incorrecto_score: float


@dataclass
class ResultadoModelo:
    nombre: str
    dim_real: int
    tiempo_indexado_s: float
    tiempo_consultas_s: float
    consultas: list[ResultadoConsulta] = field(default_factory=list)
    error: str | None = None

    @property
    def top1(self) -> int:
        return sum(1 for c in self.consultas if c.rank_correcto == 1)

    @property
    def top3(self) -> int:
        return sum(1 for c in self.consultas if 1 <= c.rank_correcto <= 3)

    @property
    def mrr(self) -> float:
        return sum(1.0 / c.rank_correcto for c in self.consultas) / len(self.consultas)

    @property
    def margen_promedio(self) -> float:
        return sum(c.score_correcto - c.mejor_incorrecto_score for c in self.consultas) / len(self.consultas)


def evaluar_modelo(candidato: Candidato) -> ResultadoModelo:
    embedder = candidato.build()

    t0 = time.monotonic()
    textos = [n["texto"] for n in NORMATIVA]
    metadatas = [{"id": n["id"]} for n in NORMATIVA]
    vectorstore = FAISS.from_texts(
        textos, embedder, metadatas=metadatas,
        distance_strategy=DistanceStrategy.MAX_INNER_PRODUCT,
        normalize_L2=True,
    )
    t_index = time.monotonic() - t0

    dim_real = vectorstore.index.d

    t0 = time.monotonic()
    resultados: list[ResultadoConsulta] = []
    for q in MANUAL_QUERIES:
        hits = vectorstore.similarity_search_with_score(q["texto"], k=len(NORMATIVA))
        rank_correcto = None
        score_correcto = None
        mejor_incorrecto_id = None
        mejor_incorrecto_score = None
        for rank, (doc, score) in enumerate(hits, start=1):
            hid = doc.metadata["id"]
            if hid == q["espera_id"]:
                rank_correcto = rank
                score_correcto = float(score)
            elif mejor_incorrecto_score is None:
                mejor_incorrecto_id = hid
                mejor_incorrecto_score = float(score)
        resultados.append(ResultadoConsulta(
            espera_id=q["espera_id"], rank_correcto=rank_correcto, score_correcto=score_correcto,
            mejor_incorrecto_id=mejor_incorrecto_id, mejor_incorrecto_score=mejor_incorrecto_score,
        ))
    t_query = time.monotonic() - t0

    return ResultadoModelo(
        nombre=candidato.nombre, dim_real=dim_real,
        tiempo_indexado_s=t_index, tiempo_consultas_s=t_query, consultas=resultados,
    )


def main() -> None:
    n = len(NORMATIVA)
    resultados: list[ResultadoModelo] = []

    for candidato in CANDIDATOS:
        print(f"\n=== {candidato.nombre} ===")
        try:
            r = evaluar_modelo(candidato)
        except Exception as e:  # noqa: BLE001 — se reporta y se sigue con el resto
            print(f"  FALLÓ: {type(e).__name__}: {e}")
            resultados.append(ResultadoModelo(
                nombre=candidato.nombre, dim_real=-1, tiempo_indexado_s=0, tiempo_consultas_s=0,
                error=f"{type(e).__name__}: {e}",
            ))
            continue
        print(f"  dim={r.dim_real} | top1={r.top1}/{n} | top3={r.top3}/{n} | "
              f"MRR={r.mrr:.3f} | margen_prom={r.margen_promedio:+.4f} | "
              f"indexado={r.tiempo_indexado_s:.2f}s | consultas={r.tiempo_consultas_s:.2f}s")
        fallidas = [c for c in r.consultas if c.rank_correcto != 1]
        if fallidas:
            print("  fallos (no top-1):")
            for c in fallidas:
                print(f"    {c.espera_id}: rank={c.rank_correcto}, "
                      f"score_correcto={c.score_correcto:.4f}, "
                      f"top1_equivocado={c.mejor_incorrecto_id} (score={c.mejor_incorrecto_score:.4f})")
        resultados.append(r)

    print("\n" + "=" * 100)
    print(f"{'modelo':<42} {'dim':>5} {'top1':>7} {'top3':>7} {'MRR':>7} {'margen':>9} {'idx(s)':>7} {'qry(s)':>7}")
    print("-" * 100)
    for r in resultados:
        if r.error:
            print(f"{r.nombre:<42} FALLÓ: {r.error}")
            continue
        print(f"{r.nombre:<42} {r.dim_real:>5} {r.top1:>4}/{n:<2} {r.top3:>4}/{n:<2} "
              f"{r.mrr:>7.3f} {r.margen_promedio:>+9.4f} {r.tiempo_indexado_s:>7.2f} {r.tiempo_consultas_s:>7.2f}")


if __name__ == "__main__":
    main()

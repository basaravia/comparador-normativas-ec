"""
Validation script for 02_rag_index.ipynb
Tests: docling, faiss, sentence_transformers imports; Docling PDF conversion;
HybridChunker; embeddings with intfloat/multilingual-e5-small (cached, avoids download);
FAISS IndexFlatIP build; semantic search with score > 0.7.

Uses intfloat/multilingual-e5-small (384 dims, already cached) instead of
multilingual-e5-large to avoid a large download.
"""
import sys
import json
import logging
import warnings
import tempfile
from pathlib import Path

# Silence docling verbosity
logging.getLogger("docling").setLevel(logging.ERROR)
logging.getLogger("docling_core").setLevel(logging.ERROR)
logging.getLogger("transformers").setLevel(logging.ERROR)
warnings.filterwarnings("ignore")

PROJECT_ROOT = Path(__file__).parent
DOCS_DIR     = PROJECT_ROOT / "document_test"
# Pick the smaller PDF to keep the test fast
PDF_FILES    = sorted(DOCS_DIR.glob("*.pdf"))

EMBED_MODEL       = "intfloat/multilingual-e5-small"   # already cached
E5_PREFIX_DOC     = "passage: "
E5_PREFIX_QUERY   = "query: "
MAX_TOKENS        = 512
DEVICE            = "cpu"   # safe default for CI-style validation

PASS = "[PASS]"
FAIL = "[FAIL]"
results = []


def check(label: str, condition: bool, detail: str = "") -> bool:
    status = PASS if condition else FAIL
    msg = f"{status}  {label}"
    if detail:
        msg += f"\n         detail: {detail}"
    print(msg)
    results.append((label, condition))
    return condition


# ── Test 1: imports ──────────────────────────────────────────────────────────
print("\n=== Test 1: imports críticos ===")

try:
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, EasyOcrOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption
    check("docling importa sin error", True)
except ImportError as e:
    check("docling importa sin error", False, str(e))
    sys.exit(1)

try:
    from docling.chunking import HybridChunker
    check("docling.chunking.HybridChunker importa sin error", True)
except ImportError as e:
    check("docling.chunking.HybridChunker importa sin error", False, str(e))
    sys.exit(1)

try:
    import faiss
    check("faiss importa sin error", True)
except ImportError as e:
    check("faiss importa sin error", False, str(e))
    sys.exit(1)

try:
    from sentence_transformers import SentenceTransformer
    check("sentence_transformers importa sin error", True)
except ImportError as e:
    check("sentence_transformers importa sin error", False, str(e))
    sys.exit(1)

try:
    import numpy as np
    check("numpy importa sin error", True)
except ImportError as e:
    check("numpy importa sin error", False, str(e))
    sys.exit(1)


# ── Test 2: PDFs de prueba existen ───────────────────────────────────────────
print("\n=== Test 2: archivos PDF en document_test/ ===")
check(
    "document_test/ contiene al menos 1 PDF",
    len(PDF_FILES) > 0,
    f"encontrados: {[p.name for p in PDF_FILES]}",
)
if not PDF_FILES:
    sys.exit(1)

# Use the smallest PDF for speed
pdf_path = min(PDF_FILES, key=lambda p: p.stat().st_size)
check(
    f"PDF seleccionado existe: {pdf_path.name}",
    pdf_path.exists(),
    str(pdf_path),
)
print(f"  [INFO] PDF a convertir: {pdf_path.name} ({pdf_path.stat().st_size // 1024} KB)")


# ── Test 3: Docling convierte el PDF ────────────────────────────────────────
print("\n=== Test 3: conversión Docling ===")
pipeline_opts = PdfPipelineOptions(
    do_ocr=False,           # OCR off para acelerar la validación
    do_table_structure=True,
)

converter = DocumentConverter(
    format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_opts)}
)

try:
    result = converter.convert(str(pdf_path))
    doc = result.document
    check("converter.convert() no lanza excepción", True)
except Exception as e:
    check("converter.convert() no lanza excepción", False, str(e))
    sys.exit(1)

try:
    md_text = doc.export_to_markdown()
    check(
        "export_to_markdown() devuelve texto no vacío",
        len(md_text) > 100,
        f"{len(md_text):,} chars",
    )
    check(
        "markdown exportado contiene texto legible (len > 200)",
        len(md_text.strip()) > 200,
    )
except Exception as e:
    check("export_to_markdown() no lanza excepción", False, str(e))


# ── Test 4: HybridChunker produce chunks ─────────────────────────────────────
print("\n=== Test 4: HybridChunker ===")
try:
    chunker = HybridChunker(
        tokenizer=EMBED_MODEL,
        max_tokens=MAX_TOKENS,
        merge_peers=True,
    )
    doc_chunks = list(chunker.chunk(doc))
    check("HybridChunker.chunk() no lanza excepción", True)
    check(
        "HybridChunker produce al menos 1 chunk",
        len(doc_chunks) > 0,
        f"chunks generados: {len(doc_chunks)}",
    )
    print(f"  [INFO] {len(doc_chunks)} chunks generados")
except Exception as e:
    check("HybridChunker.chunk() no lanza excepción", False, str(e))
    doc_chunks = []
    sys.exit(1)

# Construir all_chunks con la misma estructura del notebook
all_chunks = []
for chunk in doc_chunks:
    pages = set()
    for item in chunk.meta.doc_items:
        for prov in getattr(item, 'prov', []):
            if hasattr(prov, 'page_no'):
                pages.add(prov.page_no)
    headings = chunk.meta.headings or []
    heading_path = " > ".join(headings)
    embed_text = f"{heading_path}\n{chunk.text}" if heading_path else chunk.text

    all_chunks.append({
        "id":           len(all_chunks),
        "source":       pdf_path.stem,
        "page_start":   min(pages) if pages else None,
        "page_end":     max(pages) if pages else None,
        "headings":     headings,
        "heading_path": heading_path,
        "text":         chunk.text,
        "embed_text":   embed_text,
    })

check(
    "all_chunks tiene misma cantidad que doc_chunks",
    len(all_chunks) == len(doc_chunks),
)
check(
    "cada chunk tiene campo 'text' no vacío",
    all(len(c["text"].strip()) > 0 for c in all_chunks),
    f"chunks con texto vacío: {sum(1 for c in all_chunks if not c['text'].strip())}",
)


# ── Test 5: embeddings con multilingual-e5-small ─────────────────────────────
print("\n=== Test 5: embeddings intfloat/multilingual-e5-small ===")
try:
    embed_model = SentenceTransformer(EMBED_MODEL)
    DIM = embed_model.get_embedding_dimension()
    check("SentenceTransformer carga sin error", True)
    check(
        "dimensión del modelo es 384 (multilingual-e5-small)",
        DIM == 384,
        f"DIM={DIM}",
    )
    print(f"  [INFO] Modelo cargado: {EMBED_MODEL}, dim={DIM}")
except Exception as e:
    check("SentenceTransformer carga sin error", False, str(e))
    sys.exit(1)

try:
    texts_to_embed = [E5_PREFIX_DOC + c["embed_text"] for c in all_chunks]
    embeddings = embed_model.encode(
        texts_to_embed,
        batch_size=8,
        normalize_embeddings=True,
        show_progress_bar=False,
        device=DEVICE,
    )
    embeddings = embeddings.astype(np.float32)
    check("encode() no lanza excepción", True)
    check(
        f"shape de embeddings es ({len(all_chunks)}, {DIM})",
        embeddings.shape == (len(all_chunks), DIM),
        f"shape={embeddings.shape}",
    )
    # Verificar que los vectores están normalizados (L2 ≈ 1.0)
    norms = np.linalg.norm(embeddings, axis=1)
    check(
        "vectores normalizados (|v| ≈ 1.0)",
        bool(np.allclose(norms, 1.0, atol=1e-5)),
        f"norma media={norms.mean():.6f}",
    )
except Exception as e:
    check("encode() no lanza excepción", False, str(e))
    sys.exit(1)


# ── Test 6: índice FAISS ─────────────────────────────────────────────────────
print("\n=== Test 6: índice FAISS IndexFlatIP ===")
try:
    index = faiss.IndexFlatIP(DIM)
    index.add(embeddings)
    check("faiss.IndexFlatIP.add() no lanza excepción", True)
    check(
        "index.ntotal == len(all_chunks)",
        index.ntotal == len(all_chunks),
        f"ntotal={index.ntotal}, n_chunks={len(all_chunks)}",
    )
    print(f"  [INFO] {index.ntotal} vectores indexados, dim={DIM}")
except Exception as e:
    check("FAISS index build", False, str(e))
    sys.exit(1)


# ── Test 7: búsqueda semántica con score > 0.7 ───────────────────────────────
print("\n=== Test 7: búsqueda semántica ===")
# Queries relevantes al dominio de políticas corporativas (document_test PDFs)
QUERIES = [
    "política de seguridad de la información",
    "responsabilidades del colaborador",
    "conflicto de intereses",
]

for query in QUERIES:
    try:
        q_vec = embed_model.encode(
            [E5_PREFIX_QUERY + query],
            normalize_embeddings=True,
            device=DEVICE,
        ).astype(np.float32)

        scores, indices = index.search(q_vec, 5)
        top_score = float(scores[0][0]) if len(scores[0]) > 0 else 0.0
        top_idx   = int(indices[0][0]) if len(indices[0]) > 0 else -1

        check(
            f"query '{query[:45]}' devuelve resultado válido (idx != -1)",
            top_idx != -1,
            f"top_idx={top_idx}",
        )
        check(
            f"query '{query[:45]}' score > 0.7",
            top_score > 0.7,
            f"top_score={top_score:.4f}",
        )
        if top_idx >= 0:
            chunk_text = all_chunks[top_idx]["text"][:120].strip()
            print(f"  [INFO] top chunk: score={top_score:.4f} | '{chunk_text}'")
    except Exception as e:
        check(f"búsqueda para '{query[:45]}'", False, str(e))


# ── Test 8: persistencia FAISS + metadatos (en tempdir) ──────────────────────
print("\n=== Test 8: guardar/cargar índice FAISS ===")
with tempfile.TemporaryDirectory() as tmpdir:
    index_path = Path(tmpdir) / "index.faiss"
    meta_path  = Path(tmpdir) / "chunks_metadata.json"
    try:
        faiss.write_index(index, str(index_path))
        check("faiss.write_index() no lanza excepción", True)
        check("index.faiss creado y no vacío", index_path.exists() and index_path.stat().st_size > 0)

        meta_payload = {
            "embed_model": EMBED_MODEL,
            "dim": DIM,
            "index_type": "flat",
            "e5_prefix_doc": E5_PREFIX_DOC,
            "e5_prefix_query": E5_PREFIX_QUERY,
            "n_chunks": len(all_chunks),
            "sources": [pdf_path.stem],
            "chunks": all_chunks,
        }
        meta_path.write_text(json.dumps(meta_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        check("chunks_metadata.json creado y no vacío", meta_path.exists() and meta_path.stat().st_size > 0)

        # Reload and verify
        index2 = faiss.read_index(str(index_path))
        check(
            "índice recargado tiene mismo ntotal",
            index2.ntotal == index.ntotal,
            f"original={index.ntotal}, recargado={index2.ntotal}",
        )
        meta2 = json.loads(meta_path.read_text(encoding="utf-8"))
        check(
            "metadatos recargados: n_chunks coincide",
            meta2["n_chunks"] == len(all_chunks),
        )
    except Exception as e:
        check("persistencia FAISS", False, str(e))


# ── Resumen ───────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
passed = sum(1 for _, ok in results if ok)
failed = sum(1 for _, ok in results if not ok)
print(f"RESULTADO NB02: {passed} passed, {failed} failed  ({passed}/{len(results)})")
if failed:
    print("CHECKS FALLIDOS:")
    for label, ok in results:
        if not ok:
            print(f"  - {label}")
    sys.exit(1)
else:
    print("STATUS: PASS")

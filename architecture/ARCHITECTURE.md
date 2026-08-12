# Arquitectura — Comparador Automatizado de Normativas vs. Manuales Internos

Pipeline RAG de 5 fases que extrae, indexa y compara normativas ecuatorianas contra
manuales internos bancarios para identificar brechas de cumplimiento normativo.

> **Estado:** olas 0 y 1 de la Fase 1 cerradas. El diagrama refleja el código en
> `feature/comparador-v2`. Las fases 2 y 3 del plan (contenedor + frontend, y nube)
> cambian el envoltorio y el sitio donde corre, no el pipeline: ver
> `PLAN_MEJORAS_ANEXO.md` §9 y §10.

## Diagrama General

```mermaid
flowchart TD
    %% ── Entradas ──────────────────────────────────────────────────────
    N_PDF[("PDFs Normativas\nSBS · BCE · SEPS · UAF\nAsamblea Nacional\n5 normativas")]
    M_PDF[("PDFs Manuales\nPolíticas · Procedimientos\n2 manuales")]

    %% ── FASE 1 ────────────────────────────────────────────────────────
    subgraph FASE1["FASE 1 — Tabulación de Documentos   src/document_parser.py"]
        NP["NormativaParser\nDocling Layout ML + macOS OCR\n→ Cache Markdown\n→ Regex: artículos, disposiciones,\n   jerarquía, bloques, referencias"]
        MP["ManualParser\nDocling Layout ML + macOS OCR\n→ HybridChunker\n   chunks semánticos con jerarquía"]
        DF_N[("normativa_df\n270 artículos\norden · element_id · contenido\nencabezado · tipo_bloque · embed_text")]
        DF_M[("manual_df\n135 chunks\nchunk_id · jerarquía · titulo_seccion\ntexto · embed_text")]
        NP --> DF_N
        MP --> DF_M
    end

    %% ── FASE 2 ────────────────────────────────────────────────────────
    subgraph FASE2["FASE 2 — Indexación y Búsqueda Híbrida   src/search_engine.py + src/embeddings.py"]
        EMB["Embedding Backend\ngranite-multilingual 768d  ←  default\nqwen3-embedding 2560d      ←  alta calidad\nbatch=32 · L2-normalizado"]
        FIDX[("FAISS IndexFlatIP\ncosine similarity\n270 vectores")]
        subgraph HYBRID["Búsqueda Híbrida  por cada chunk del manual"]
            LEX["① Léxica\nRegex: Art(ículo)? N\nscore = 1.0 (match exacto)"]
            SEM["② Semántica\nFAISS top-5\nscore ≥ 0.30"]
            RNK["③ Reranker\nqwen3-reranker 0.6B\ntop-3 candidatos finales\n(fallback: orden FAISS)"]
            LEX --> RNK
            SEM --> RNK
        end
        CANDS["Candidatos Rankeados\nsimilarity · reranker_score · rank\n+ metadata del artículo"]
        EMB --> FIDX
        FIDX --> SEM
        HYBRID --> CANDS
    end

    %% ── FASES 3 + 4 ───────────────────────────────────────────────────
    subgraph FASE34["FASES 3+4 — Calificación y Análisis   src/llm_grader.py"]
        GRD["Grade Candidates\ngemma4  CoT  T=0.0  2048 tok\n→ relevante: bool\n→ score: float 0–1\n→ razón: str ≤100 chars"]
        ANA["Analyze Comparison\ngemma4  CoT  T=0.0  4096 tok\n→ tipo_coincidencia\n→ nivel_cumplimiento\n→ análisis léxico y semántico (top 1/2/3)\n→ brechas · recomendaciones"]
        RESULT["ComparisonResult  Pydantic\ntipo_coincidencia: lexica|semantica|ninguna\nnivel_cumplimiento: cumple|parcial|omision|no_aplica\nbrechas · ner_general\nentidades_financieras · entidades_normativas"]
        GRD --> ANA --> RESULT
    end

    %% ── FASE 5 ────────────────────────────────────────────────────────
    subgraph FASE5["FASE 5 — Orquestación   src/comparator.py"]
        ORC["DocumentComparator\nEnvío ACOTADO: ventana de max_workers×2\ntareas en vuelo, no todas encoladas\nfail-fast en cascada + estado_analisis\n~2–4 min/chunk en M1 16GB"]
    end

    %% ── Docker Model Runner ───────────────────────────────────────────
    subgraph DMR["Docker Model Runner — localhost:12434/engines/v1"]
        direction LR
        ME["Embeddings\ngranite-embedding-multilingual\nqwen3-embedding"]
        MG["LLM Principal\ngemma4 latest\nCoT reasoning"]
        MF["LLM Fallback\nsmollm2-vllm 1.7B"]
        MG -.->|"error / timeout"| MF
    end

    %% ── Reranker: LOCAL, no en el backend remoto ──────────────────────
    subgraph RERANK["Reranker — en proceso"]
        MR["CrossEncoder local\nsentence-transformers\nMPS con dtype=float32 + attn eager\n(el backend remoto no soporta\nreranking en Apple Silicon)"]
    end

    %% ── Capa transversal (Ola 1) ──────────────────────────────────────
    subgraph TRANS["Transversal   src/"]
        direction TB
        PROV["providers.py\nÚNICO sitio que construye\nclientes de modelo"]
        SET["settings.py\n.env · precedencia\nredact() de secretos"]
        ERR["errors.py\nabortar vs. degradar"]
        REG["model_registry.py\npreflight + list models"]
        TOK["design_tokens.py\npaleta única UI + Excel"]
        BOOT["bootstrap.py\nworkarounds de proceso"]
    end

    %% ── Caché y Persistencia ──────────────────────────────────────────
    subgraph CACHE["Caché y Persistencia   output/"]
        CM[("output/docling/\n*.md · normativas_docling.json\nTimestamp-based validity")]
        CI[("output/comparador/faiss_index/\nindex.faiss\nnormativa_meta.json")]
    end

    %% ── Salidas ───────────────────────────────────────────────────────
    subgraph OUT["Salidas   output/comparador/"]
        XLSX["reporte_comparacion.xlsx\nHeaders azul oscuro · texto wrap\ncumple → verde\nparcial → amarillo\nomisión → naranja\nno_aplica → gris"]
        RJSON[("reporte_comparacion.json\nDataFrame completo serializado")]
    end

    %% ── Flujo principal ───────────────────────────────────────────────
    N_PDF --> NP
    M_PDF --> MP
    DF_N --> EMB
    DF_M --> ORC
    ORC --> HYBRID
    CANDS --> GRD
    RESULT --> ORC
    ORC --> OUT

    %% ── Caché ─────────────────────────────────────────────────────────
    NP <-->|"lee / escribe"| CM
    FIDX --> CI

    %% ── Llamadas API al DMR ───────────────────────────────────────────
    EMB -.->|"POST /embeddings"| ME
    GRD -.->|"POST /chat/completions"| MG
    ANA -.->|"POST /chat/completions"| MG
    RNK --> MR

    %% ── La capa transversal gobierna las llamadas ─────────────────────
    PROV -.->|"construye"| EMB
    PROV -.->|"construye"| GRD
    SET  -.->|"configura"| PROV
    REG  -.->|"valida antes de arrancar"| PROV
    ERR  -.->|"clasifica fallos"| ORC
    TOK  -.->|"colores"| XLSX
```

## Stack Tecnológico

| Capa | Componente | Versión / Modelo |
|------|-----------|-----------------|
| Extracción PDF | Docling + ocrmac | 2.55.1 / ≥1.0.1 |
| Chunking | Docling HybridChunker | — |
| Embeddings | granite-embedding-multilingual | 768d (default) |
| Embeddings HQ | qwen3-embedding | 2560d |
| Vector Search | FAISS IndexFlatIP | 1.14.2 |
| Reranker | CrossEncoder local (sentence-transformers) | Qwen3-Reranker 0.6B |
| LLM Principal | gemma4 | latest (CoT) |
| LLM Fallback | smollm2-vllm | 1.7B |
| Validación salida | Pydantic | ≥2.10.0 |
| Export Excel | openpyxl | ≥3.1.0 |
| Aceleración | Apple Silicon MPS | M1/M2+ 16GB+ |

## Módulos Principales

```
src/
│  ── Pipeline ──────────────────────────────────────────────────────────
├── document_parser.py   # Fase 1: NormativaParser + ManualParser
├── embeddings.py        # Backends + LangChainEmbeddingsAdapter genérico
├── search_engine.py     # Fase 2: NormativaIndex (FAISS + léxico + reranker)
├── llm_grader.py        # Fases 3+4: LLMGrader + modelos Pydantic
├── comparator.py        # Fase 5: DocumentComparator (orquestador concurrente)
│
│  ── Transversal (Ola 1) ────────────────────────────────────────────────
├── bootstrap.py         # Preparación del proceso; se aplica al importarse
├── config.py            # Defaults NO sensibles (deja de ser fuente de credenciales)
├── settings.py          # .env, precedencia UI>entorno>.env>config, redact()
├── providers.py         # ProviderSpec + fábricas: ÚNICO constructor de clientes
├── errors.py            # Taxonomía: qué aborta la corrida y qué degrada una fila
├── model_registry.py    # list/validate models + preflight con caché de 15 s
└── design_tokens.py     # Fuente única de paleta y tipografía (UI + Excel)
```

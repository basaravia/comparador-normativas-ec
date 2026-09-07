"""App Streamlit — Comparador de Normativas vs Manuales Internos.

Envuelve el pipeline de 5 fases de ``src/`` (el mismo usado en
``master.ipynb``): tabulación (Docling) → índice FAISS + léxico →
reranking (CrossEncoder, transformers) → grading + análisis comparativo
(LLM vía Vertex AI) → exportación. La barra lateral expone los parámetros
de los modelos fundacionales (embeddings vía Ollama, LLM vía Vertex,
reranker, umbrales de búsqueda). Rama Linux — ver ``src/config.py``.

Ejecutar con:  streamlit run streamlit_app.py
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

# Prepara el proceso al importarse; debe ir antes que faiss/docling/torch. El workaround
# concreto vive en src/bootstrap.py y no aquí: cuando el frontend deje de ser Python
# (Fase 2), este archivo desaparece y con él se iría el arranque del proceso.
import src.bootstrap  # noqa: F401

import altair as alt
import pandas as pd
import streamlit as st

from app.logging_utils import clear_log_lines, get_log_lines, save_run_log, setup_logging
from app.auth import check_auth, render_user_sidebar
from app.theme import NIVEL_COLORS, inject_theme, render_header
from src import config as cfg
from src import scope, service
from app.run_manager import EstadoCorrida, RunHandle, gestor
from src.errors import RunAbortedError
from src.model_registry import modelos_disponibles, preflight
from src.providers import Provider, ProviderSpec

logger = logging.getLogger("app")

NORMATIVA_DIR = Path("Normativa2026")
MANUAL_DIR = Path("document_test")
OUTPUT_DIR = Path("output/comparador")
UPLOAD_NORMATIVA_DIR = Path("output/uploads/normativas")
UPLOAD_MANUAL_DIR = Path("output/uploads/manuales")
NIVEL_ORDER = ["cumple", "parcial", "omision", "no_aplica"]

inject_theme()
setup_logging()

# La autenticación se evalúa antes de renderizar el resto de la aplicación.
# En modo no autenticado, check_auth() muestra únicamente el formulario y
# st.stop() evita cargar documentos, modelos y pestañas.
if not check_auth():
    st.stop()

render_user_sidebar()
render_header(
    "Análisis de cumplimiento normativo (SBS · BCE · SEPS · UAF) sobre manuales internos"
)


# ──────────────────────────────────────────────────────────────────────────
# Barra lateral — configuración de modelos fundacionales
# ──────────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=15, show_spinner=False)
def _modelos_del_backend(base_url: str) -> list[str]:
    """Modelos que el backend ofrece de verdad.

    Antes esto solo comprobaba `status_code == 200` y los desplegables se poblaban con
    constantes escritas a mano: ofrecían modelos que quizá no estaban y ocultaban los
    que sí. Un modelo mal escrito se descubría a mitad de una corrida de horas.
    """
    spec = ProviderSpec(proveedor=Provider.DMR, base_url=base_url)
    return modelos_disponibles(spec, usar_cache=False)


def _opciones_modelo(disponibles: list[str], defecto: str) -> list[str]:
    """Lista real del backend; si no responde, las constantes como último recurso."""
    if disponibles:
        return disponibles + ["Personalizado…"]
    return [defecto, cfg.DMR_LLM_FALLBACK, "Personalizado…"]


def _sidebar_config() -> dict:
    st.sidebar.markdown("## ⚙️ Modelos fundacionales")

    if st.sidebar.button("↺ Restaurar valores por defecto", width="stretch"):
        for key in list(st.session_state.keys()):
            if key.startswith("cfg_"):
                del st.session_state[key]
        st.rerun()

    st.sidebar.markdown("#### Conexión (embeddings — Ollama)")
    dmr_base_url = st.sidebar.text_input("Ollama base URL", value=cfg.DMR_BASE_URL, key="cfg_dmr_url")
    modelos_backend = _modelos_del_backend(dmr_base_url)
    dmr_ok = bool(modelos_backend)
    st.sidebar.caption(
        f"🟢 Ollama conectado · {len(modelos_backend)} modelos disponibles"
        if dmr_ok else "🔴 Ollama no responde en esa URL"
    )

    st.sidebar.markdown("#### Embeddings")
    embed_backend_kind = st.sidebar.radio(
        "Backend de embeddings",
        ["Docker Model Runner", "Local (sentence-transformers)"],
        key="cfg_embed_backend",
    )
    embed_model = st.sidebar.selectbox(
        "Modelo de embedding",
        options=_opciones_modelo(modelos_backend, cfg.DMR_EMBED_MODEL),
        index=0,
        key="cfg_embed_model_select",
        disabled=embed_backend_kind != "Docker Model Runner",
    )
    if embed_model == "Personalizado…":
        embed_model = st.sidebar.text_input(
            "Modelo de embedding (custom)", value=cfg.DMR_EMBED_MODEL, key="cfg_embed_model_custom"
        )
    embed_batch_size = st.sidebar.number_input(
        "Batch size", min_value=1, max_value=128, value=cfg.EMBED_BATCH_SIZE, key="cfg_embed_batch"
    )

    st.sidebar.markdown("#### LLM (grading + análisis — Vertex AI)")
    # A diferencia de embeddings, el LLM no vive en Ollama: es texto libre, no un
    # desplegable poblado desde `modelos_backend` (eso listaría modelos de Ollama, que
    # no son los que Vertex sirve). Vertex no expone un endpoint de listado homogéneo
    # (ver Provider.VERTEX en providers.py, listado_modelos=False) — igual que ya pasaba
    # con RERANK_HTTP/DOCLING_LOCAL, el preflight se salta esa validación sin inventar
    # un error donde no hay evidencia.
    llm_model = st.sidebar.text_input(
        "Modelo Vertex (Gemini)", value=cfg.VERTEX_LLM_MODEL, key="cfg_llm_model",
    )
    st.sidebar.caption(
        f"Proyecto: `{cfg.VERTEX_PROJECT_ID}` · región: `{cfg.VERTEX_LOCATION}` — "
        "requiere GOOGLE_APPLICATION_CREDENTIALS en el entorno."
    )
    temperature = st.sidebar.slider("Temperatura", 0.0, 1.0, cfg.LLM_TEMPERATURE, 0.05, key="cfg_temperature")
    llm_max_tokens = st.sidebar.number_input(
        "Max tokens (análisis)", min_value=512, max_value=16384, value=cfg.LLM_MAX_TOKENS, step=256, key="cfg_llm_max_tokens"
    )
    grader_max_tokens = st.sidebar.number_input(
        "Max tokens (grading)", min_value=256, max_value=8192, value=cfg.LLM_GRADER_MAX_TOKENS, step=256, key="cfg_grader_max_tokens"
    )

    st.sidebar.markdown("#### Búsqueda + reranking")
    use_reranker = st.sidebar.checkbox("Usar reranker (CrossEncoder local)", value=True, key="cfg_use_reranker")
    reranker_model = st.sidebar.text_input(
        "Modelo reranker", value=cfg.RERANKER_MODEL, key="cfg_reranker_model", disabled=not use_reranker
    )
    faiss_top_k = st.sidebar.slider("FAISS top-k", 1, 20, cfg.FAISS_TOP_K, key="cfg_faiss_top_k")
    reranker_top_n = st.sidebar.slider("Reranker top-n", 1, 20, cfg.RERANKER_TOP_N, key="cfg_reranker_top_n")
    min_semantic_score = st.sidebar.slider(
        "Score semántico mínimo", 0.0, 1.0, cfg.MIN_SEMANTIC_SCORE, 0.01, key="cfg_min_score"
    )

    st.sidebar.markdown("#### Procesamiento")
    device = st.sidebar.selectbox("Device (Docling)", ["cpu", "auto", "mps", "cuda"], index=0, key="cfg_device")
    st.sidebar.caption(
        "⚠️ MPS puede causar segfault al convertir manuales sin caché en Apple Silicon "
        "(ver hardening en el historial del proyecto). Usa 'cpu' salvo que sepas que es estable."
    )
    do_ocr = st.sidebar.checkbox("OCR nativo (documentos escaneados)", value=True, key="cfg_do_ocr")
    docling_max_tokens = st.sidebar.number_input(
        "Max tokens por chunk (manual)", min_value=128, max_value=2048, value=cfg.DOCLING_MAX_TOKENS, step=64, key="cfg_docling_max_tokens"
    )
    max_workers = st.sidebar.number_input(
        "Hilos concurrentes (LLM)", min_value=1, max_value=8, value=cfg.MAX_WORKERS, key="cfg_max_workers"
    )

    return dict(
        dmr_base_url=dmr_base_url,
        dmr_ok=dmr_ok,
        embed_backend_kind=embed_backend_kind,
        embed_model=embed_model,
        embed_batch_size=int(embed_batch_size),
        llm_model=llm_model,
        temperature=temperature,
        llm_max_tokens=int(llm_max_tokens),
        grader_max_tokens=int(grader_max_tokens),
        use_reranker=use_reranker,
        reranker_model=reranker_model,
        faiss_top_k=int(faiss_top_k),
        reranker_top_n=min(int(reranker_top_n), int(faiss_top_k)),
        min_semantic_score=min_semantic_score,
        device=device,
        do_ocr=do_ocr,
        docling_max_tokens=int(docling_max_tokens),
        max_workers=int(max_workers),
    )


config = _sidebar_config()


# ──────────────────────────────────────────────────────────────────────────
# Helpers de carga de documentos
# ──────────────────────────────────────────────────────────────────────────

def _pdf_picker(label: str, existing_dir: Path, upload_dir: Path, key: str, exclude_prefix: str = "") -> list[Path]:
    existing = sorted(existing_dir.glob("*.pdf")) if existing_dir.exists() else []
    default = [p for p in existing if not (exclude_prefix and p.name.startswith(exclude_prefix))]

    selected = st.multiselect(
        f"{label} existentes en `{existing_dir}/`",
        options=existing,
        default=default,
        format_func=lambda p: p.name,
        key=f"{key}_existing",
    )
    if exclude_prefix and len(default) < len(existing):
        st.caption(
            f"Los PDFs `{exclude_prefix}*` no vienen preseleccionados: no tienen caché Docling "
            "y su conversión en vivo ha causado segfault en Apple Silicon."
        )

    uploaded = st.file_uploader(f"Subir nuevo(s) PDF de {label.lower()}", type=["pdf"], accept_multiple_files=True, key=f"{key}_upload")
    saved_paths: list[Path] = list(selected)
    if uploaded:
        upload_dir.mkdir(parents=True, exist_ok=True)
        for f in uploaded:
            dest = upload_dir / f.name
            dest.write_bytes(f.getbuffer())
            if dest not in saved_paths:
                saved_paths.append(dest)
            logger.info("Archivo subido: %s (%d bytes)", dest, dest.stat().st_size)
    return saved_paths


# La construcción de backends vivía aquí. Ahora es del servicio: esta capa es vista.


# ──────────────────────────────────────────────────────────────────────────
# Pestañas principales
# ──────────────────────────────────────────────────────────────────────────

tab_docs, tab_index, tab_compare, tab_results = st.tabs(
    ["📄 1. Documentos", "🧭 2. Índice", "⚡ 3. Comparación", "📊 4. Resultados"]
)

with tab_docs:
    st.subheader("Carga y tabulación de documentos")
    col_norm, col_man = st.columns(2)
    with col_norm:
        st.markdown("**Normativa(s)**")
        normativa_files = _pdf_picker("Normativa", NORMATIVA_DIR, UPLOAD_NORMATIVA_DIR, "normativa", exclude_prefix="L1-XVI")
    with col_man:
        st.markdown("**Manual(es) interno(s)**")
        manual_files = _pdf_picker("Manual", MANUAL_DIR, UPLOAD_MANUAL_DIR, "manual")

    if st.button(
        "📑 Tabular documentos", type="primary", disabled=not (normativa_files and manual_files), width="stretch"
    ):
        with st.status("Tabulando documentos…", expanded=True) as status:
            t0 = time.time()
            logger.info(
                "Iniciando tabulación: %d normativa(s), %d manual(es) — device=%s, ocr=%s",
                len(normativa_files), len(manual_files), config["device"], config["do_ocr"],
            )

            normativa_df, manual_df = service.tabular(
                normativa_files, manual_files, service.ServiceConfig.desde_dict(config),
                on_file=lambda tipo, nombre: st.write(f"Parseando {tipo}: `{nombre}`"),
            )

            st.session_state["normativa_df"] = normativa_df
            st.session_state["manual_df"] = manual_df
            for key in ("normativa_index", "results_df", "excel_bytes", "json_bytes"):
                st.session_state.pop(key, None)

            elapsed = time.time() - t0
            logger.info(
                "Tabulación completa en %.1fs: %d elementos normativos, %d secciones de manual",
                elapsed, len(normativa_df), len(manual_df),
            )
            status.update(label=f"Tabulación completa ({elapsed:.1f}s)", state="complete")

    if "normativa_df" in st.session_state:
        n_df, m_df = st.session_state["normativa_df"], st.session_state["manual_df"]
        st.success(f"Normativa: {len(n_df)} elementos · Manual: {len(m_df)} secciones")
        c1, c2 = st.columns(2)
        c1.dataframe(n_df.head(20), width="stretch", height=250)
        c2.dataframe(m_df.head(20), width="stretch", height=250)

with tab_index:
    st.subheader("Índice semántico FAISS")
    docs_ready = "normativa_df" in st.session_state and not st.session_state["normativa_df"].empty
    if not docs_ready:
        st.info("Tabula primero los documentos en la pestaña **1. Documentos**.")
    else:
        if st.button("🧭 Construir índice FAISS", type="primary"):
            with st.status("Construyendo índice…", expanded=True) as status:
                t0 = time.time()
                st.write("Indexando artículos normativos…")
                index = service.construir_indice(
                    st.session_state["normativa_df"], service.ServiceConfig.desde_dict(config),
                )
                st.session_state["normativa_index"] = index
                elapsed = time.time() - t0
                logger.info("Índice FAISS listo en %.1fs (%d elementos)", elapsed, len(st.session_state["normativa_df"]))
                status.update(label=f"Índice listo ({elapsed:.1f}s)", state="complete")

        if "normativa_index" in st.session_state:
            st.success("Índice FAISS construido.")
            if st.button("💾 Persistir índice en `output/comparador/faiss_index/`"):
                st.session_state["normativa_index"].save(OUTPUT_DIR / "faiss_index")
                logger.info("Índice guardado en %s", OUTPUT_DIR / "faiss_index")
                st.toast("Índice guardado")

            st.markdown("#### Probar búsqueda semántica")
            query = st.text_input("Consulta de prueba", value="política de crédito y evaluación de riesgo crediticio")
            if query:
                results = st.session_state["normativa_index"].semantic_search(
                    query, top_k=config["faiss_top_k"], min_score=config["min_semantic_score"]
                )
                results = st.session_state["normativa_index"].rerank(query, results, top_n=config["reranker_top_n"])
                if not results:
                    st.warning("Sin resultados por encima del score mínimo configurado.")
                for r in results:
                    score = r.get("reranker_score", r.get("similarity"))
                    st.write(f"**Art. {r.get('numero', '?')}** — {r.get('encabezado', '')[:90]}  ·  score={score}")

with tab_compare:
    st.subheader("Comparación normativa vs manual")
    index_ready = "normativa_index" in st.session_state
    if not index_ready:
        st.info("Construye el índice en la pestaña **2. Índice** antes de comparar.")
    else:
        if not config["dmr_ok"] and config["embed_backend_kind"] == "Docker Model Runner":
            st.warning("DMR no responde en la URL configurada; la comparación fallará al llamar al LLM.")

        manual_df = st.session_state["manual_df"]
        normativa_df = st.session_state["normativa_df"]

        st.markdown("#### 🎯 Selector de alcance (Ítem 7)")
        col_alcance_norm, col_alcance_man = st.columns(2)
        with col_alcance_norm:
            st.markdown("**Alcance normativo**")
            docs_norm_disp = sorted(normativa_df["doc_id"].dropna().unique().tolist()) if "doc_id" in normativa_df.columns else []
            sel_docs_norm = st.multiselect("Documentos normativos", docs_norm_disp, default=docs_norm_disp, key="scope_docs_norm")
            preset_art = st.selectbox(
                "Preset de artículos",
                ["Todo el articulado", "Excluir referencias", "Solo disposiciones"],
                key="scope_preset_norm",
            )
            busqueda_art = st.text_input("Filtrar por número / texto (opcional)", key="scope_busqueda_art")

        with col_alcance_man:
            st.markdown("**Alcance del manual**")
            modo_manual = st.radio(
                "Selección de secciones",
                ["Muestra rápida", "Todo el manual", "Filtro por jerarquía"],
                horizontal=True,
                key="scope_modo_manual",
            )
            n_sample = 5
            filtro_jerarquia = ""
            if modo_manual == "Muestra rápida":
                n_sample = st.number_input(
                    "Número de secciones a analizar", min_value=1, max_value=len(manual_df),
                    value=min(5, len(manual_df)), key="cfg_sample_n",
                )
            elif modo_manual == "Filtro por jerarquía":
                filtro_jerarquia = st.text_input("Texto de jerarquía (ej. 4.1 o Crédito)", key="scope_jerarquia_txt")

        tipos_elem = ["disposicion"] if preset_art == "Solo disposiciones" else (["articulo"] if preset_art != "Todo el articulado" else ())
        selected_normativa_df = scope.filtrar_articulos(
            normativa_df,
            doc_ids=sel_docs_norm if sel_docs_norm else None,
            secciones=[busqueda_art] if busqueda_art else None,
            incluir_referencias=(preset_art == "Todo el articulado"),
            tipos_elemento=tipos_elem,
        )

        if modo_manual == "Muestra rápida":
            selected_manual_df = scope.muestra_rapida(manual_df, int(n_sample))
            mode = "Muestra rápida"
        elif modo_manual == "Filtro por jerarquía" and filtro_jerarquia:
            selected_manual_df = scope.filtrar_secciones(manual_df, jerarquias=[filtro_jerarquia])
            mode = f"Filtro ({filtro_jerarquia})"
        else:
            selected_manual_df = manual_df
            mode = "Pipeline completo"

        current_run_scope = scope.RunScope.desde_dataframes(
            selected_normativa_df,
            selected_manual_df,
            doc_ids_normativa=sel_docs_norm,
            incluir_referencias=(preset_art == "Todo el articulado"),
            preset_articulos=preset_art,
            muestra_n=int(n_sample) if modo_manual == "Muestra rápida" else None,
        )

        st.info(
            f"📌 **Alcance configurado:** {len(selected_normativa_df)} artículos/elementos normativos × "
            f"{len(selected_manual_df)} secciones de manual"
        )

        dual_mode = st.checkbox(
            "🔄 **Análisis en doble vía (Ítem 6)** — Vía 1 (manual → norma) + Vía 2 (norma → manual) y cobertura global",
            value=True,
            key="cfg_dual_mode",
        )

        # Preflight: valida modelo LLM y de embeddings CONTRA LA LISTA REAL antes de
        # dejar arrancar. Sin esto, un modelo mal escrito se descubría a mitad de una
        # corrida de horas — y con el ítem 1 ya no produce filas falsas, pero sigue
        # costando el tiempo (ítem 4).
        # Dos specs porque LLM y embeddings ya no comparten backend (rama Linux): el LLM
        # va a Vertex (sin listado; preflight se salta esa validación) y los embeddings
        # a Ollama vía openai-compat (sí lista, y sí se valida contra la lista real).
        _spec_llm = ProviderSpec(proveedor=Provider.VERTEX)
        _spec_embed = ProviderSpec(proveedor=Provider.DMR, base_url=config["dmr_base_url"])
        chequeo = preflight(
            _spec_llm, config["llm_model"],
            _spec_embed if config["embed_backend_kind"] == "Docker Model Runner" else None,
            config["embed_model"] if config["embed_backend_kind"] == "Docker Model Runner" else None,
        )
        if not chequeo.ok:
            st.error(
                "**No se puede ejecutar con esta configuración.**\n\n"
                + "\n\n".join(f"- {m}" for m in chequeo.mensajes)
            )

        # Una corrida viva con la misma configuración bloquea el botón. Antes, pulsar
        # "Ejecutar" tras refrescar lanzaba una segunda corrida sobre lo mismo y
        # duplicaba el gasto de LLM sin que nadie lo notara (ítem 2).
        import hashlib

        cfg_hash = hashlib.sha256(
            f"{config['llm_model']}|{config['embed_model']}|{mode}|{n_sample}".encode()
        ).hexdigest()[:12]
        en_curso = gestor().activa_con_config(cfg_hash)

        if en_curso is not None:
            st.info(
                f"Corrida `{en_curso.run_id}` en marcha — "
                f"{en_curso.progreso}/{en_curso.total} secciones."
            )
            st.progress(en_curso.porcentaje, text=en_curso.etiqueta_actual or "Procesando…")
            if st.button("⏹ Cancelar corrida", type="secondary"):
                gestor().cancelar(en_curso.run_id)
                st.rerun()
            with st.expander("📜 Registro de esta corrida", expanded=True):
                st.code("\n".join(en_curso.lineas(30)) or "…", language="text")

        run_clicked = st.button(
            "🚀 Ejecutar comparación", type="primary",
            disabled=not chequeo.ok or en_curso is not None,
        )
        progress_bar = st.progress(0.0, text="En espera…")
        log_box = st.empty()

        if run_clicked:
            clear_log_lines()
            total = len(selected_manual_df)

            cfg = service.ServiceConfig.desde_dict(config)
            rutas = service.RunPaths(run_id=service.nuevo_run_id())
            st.session_state["run_id"] = rutas.run_id
            handle = RunHandle(run_id=rutas.run_id, total=total, config_hash=cfg_hash)

            def _on_progress(done: int, total_: int, row: dict) -> None:
                label = str(row.get("jerarquia") or row.get("titulo_seccion") or "")[:60]
                handle.progreso = done
                handle.etiqueta_actual = f"{done}/{total_} · {label}"
                gestor()._espejar(handle)
                progress_bar.progress(done / total_, text=f"{done}/{total_} secciones · última: {label}")
                log_box.code("\n".join(handle.lineas(12)) or "…", language="text")

            t0 = time.time()
            logger.info("Iniciando comparación (%s, %d secciones, %d hilos)", mode, total, config["max_workers"])
            try:
                gestor().registrar(handle)
                handle.estado = EstadoCorrida.CORRIENDO
                if dual_mode:
                    manual_idx = service.construir_indice_manual(selected_manual_df, cfg)
                    bundle = service.comparar_dual(
                        indice_normativa=st.session_state["normativa_index"],
                        indice_manual=manual_idx,
                        manual_df=selected_manual_df,
                        normativa_df=selected_normativa_df,
                        config=cfg,
                        min_score=config.get("min_semantic_score", 0.30),
                        top_k=config.get("faiss_top_k", 5),
                        incluir_referencias=(preset_art == "Todo el articulado"),
                        progress_callback=lambda via, h, t: _on_progress(h, t, {"jerarquia": f"Vía {via} ({h}/{t})"}),
                    )
                    st.session_state["bundle"] = bundle
                    results_df = bundle.vista_manual
                else:
                    results_df = service.comparar(
                        st.session_state["normativa_index"],
                        selected_manual_df,
                        selected_normativa_df,
                        cfg,
                        progress_callback=_on_progress,
                        desc=mode,
                        cancelar=handle.cancelar,
                    )
                    st.session_state.pop("bundle", None)

                handle.estado = EstadoCorrida.COMPLETADO
                st.session_state["results_df"] = results_df
                st.session_state["run_scope"] = current_run_scope
                st.session_state.pop("run_parcial", None)

                generados = service.exportar(results_df, rutas)
                st.session_state["excel_bytes"] = generados["excel"].read_bytes()
                st.session_state["excel_name"] = generados["excel"].name
                st.session_state["json_bytes"] = generados["json"].read_bytes()
                st.caption(f"Corrida `{rutas.run_id}` — artefactos en `{rutas.directorio}`")

                elapsed = time.time() - t0
                logger.info("Comparación completa en %.1fs: %d secciones analizadas", elapsed, len(results_df))
                progress_bar.progress(1.0, text=f"✅ Completado en {elapsed:.1f}s")
            except RunAbortedError as e:
                # La corrida se detuvo a propósito: el backend dejó de responder. El
                # mensaje tiene que ser accionable —qué modelo, qué endpoint, cuánto
                # quedó sin analizar— porque antes esto se presentaba como un resultado
                # completo lleno de "no aplica" (ítem 1).
                logger.error("Comparación abortada: %s", e)
                st.error(
                    f"**Corrida detenida.** {e.completadas} de {e.total} secciones "
                    f"analizadas; **{e.omitidas} quedaron sin procesar**.\n\n"
                    f"Modelo: `{config['llm_model']}` (Vertex AI, proyecto `{cfg.VERTEX_PROJECT_ID}`)\n\n"
                    f"Causa: {e.causa}"
                )
                if e.parciales is not None and len(e.parciales):
                    st.warning(
                        "Los resultados parciales se conservan abajo, **etiquetados como "
                        "incompletos**. No constituyen un papel de trabajo: las secciones "
                        "omitidas no se analizaron, no es que no les aplique norma."
                    )
                    st.session_state["results_df"] = e.parciales
                    st.session_state["run_parcial"] = True
            except Exception as e:
                logger.error("Comparación interrumpida: %s", e)
                st.error(f"Error durante la comparación: {e}")
            finally:
                log_path = save_run_log()
                st.success(f"Log de esta ejecución guardado en `{log_path}`")

        if get_log_lines():
            with st.expander("📜 Registro de ejecución", expanded=False):
                st.code("\n".join(get_log_lines()), language="text")

with tab_results:
    st.subheader("Resultados")
    if "results_df" not in st.session_state:
        st.info("Ejecuta una comparación en la pestaña **3. Comparación** para ver resultados.")
    else:
        results_df = st.session_state["results_df"]

        if st.session_state.get("run_parcial"):
            st.error(
                "⚠️ **Resultados parciales de una corrida interrumpida.** No usar como "
                "papel de trabajo: las secciones sin analizar aparecen abajo como "
                "*omitido*, que no es un veredicto de cumplimiento."
            )

        # Filas sin veredicto por fallo técnico. Se cuentan aparte y se muestran: si se
        # filtraran por nivel_cumplimiento (que ahora es None) desaparecerían de la tabla
        # sin que nadie lo notara — el mismo fallo silencioso que corrige el ítem 1.
        if "estado_analisis" in results_df.columns:
            sin_analizar = results_df[results_df["estado_analisis"] != "ok"]
            if len(sin_analizar):
                st.warning(
                    f"**{len(sin_analizar)} de {len(results_df)} secciones sin análisis "
                    f"utilizable** — "
                    + " · ".join(
                        f"{n}: {c}"
                        for n, c in sin_analizar["estado_analisis"].value_counts().items()
                    )
                )

        bundle = st.session_state.get("bundle")
        if bundle is not None:
            st.markdown("### 🧭 Análisis en Doble Vía (Ítem 6)")
            c1, c2, c3, c4 = st.columns(4)
            pct = bundle.cobertura.porcentaje * 100
            c1.metric("🎯 Cobertura Global", f"{pct:.1f}%")
            c2.metric("Artículos en alcance", bundle.cobertura.total_articulos)
            c3.metric("Artículos cubiertos", len(bundle.cobertura.cubiertos))
            c4.metric("Artículos sin cobertura", len(bundle.cobertura.sin_cobertura))

            if bundle.alerta_cobertura:
                st.warning(f"⚠️ **Alerta de Cobertura:** {bundle.alerta_cobertura}")
                if bundle.cobertura.sin_cobertura:
                    with st.expander("Listado de artículos sin cobertura (huérfanos)", expanded=False):
                        for doc, num in bundle.cobertura.sin_cobertura:
                            st.write(f"- `{doc}` — **Art. {num}**")

            # Filtro de revisión manual (Ítem 10)
            st.markdown("#### 🔍 Filtro de Calidad y Revisión Manual (Ítem 10)")
            solo_revision = st.checkbox(
                "Filtrar únicamente filas marcadas para revisión manual",
                key="cfg_filter_review",
            )

            tab_v1, tab_v2 = st.tabs(["📋 Por sección (Vía 1)", "📜 Por artículo (Vía 2)"])
            with tab_v1:
                df_v1 = bundle.vista_manual
                if solo_revision and "requiere_revision_manual" in df_v1.columns:
                    df_v1 = df_v1[df_v1["requiere_revision_manual"]]
                st.caption(f"{len(df_v1)} secciones mostradas")
                st.dataframe(df_v1, width="stretch", height=380)

            with tab_v2:
                df_v2 = bundle.vista_normativa
                if solo_revision and "requiere_revision_manual" in df_v2.columns:
                    df_v2 = df_v2[df_v2["requiere_revision_manual"]]
                st.caption(f"{len(df_v2)} artículos mostrados")
                st.dataframe(df_v2, width="stretch", height=380)

        else:
            counts = results_df["nivel_cumplimiento"].value_counts()
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("✅ Cumple", int(counts.get("cumple", 0)))
            m2.metric("🟡 Parcial", int(counts.get("parcial", 0)))
            m3.metric("🔴 Omisión", int(counts.get("omision", 0)))
            m4.metric("⚪ No aplica", int(counts.get("no_aplica", 0)))

            chart_df = counts.reindex(NIVEL_ORDER, fill_value=0).rename_axis("nivel").reset_index(name="secciones")
            color_scale = alt.Scale(domain=NIVEL_ORDER, range=[NIVEL_COLORS[k]["fg"] for k in NIVEL_ORDER])
            base = alt.Chart(chart_df).encode(
                x=alt.X("nivel:N", sort=NIVEL_ORDER, title=None, axis=alt.Axis(labelAngle=0)),
                y=alt.Y("secciones:Q", title="Secciones"),
            )
            bars = base.mark_bar(size=48, cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
                color=alt.Color("nivel:N", scale=color_scale, legend=None),
                tooltip=["nivel", "secciones"],
            )
            labels = base.mark_text(dy=-8, fontWeight="bold").encode(text="secciones:Q")
            st.altair_chart((bars + labels).properties(height=280), width="stretch")

            st.markdown("#### Detalle por sección")
            niveles_filtro = st.multiselect("Filtrar por nivel de cumplimiento", NIVEL_ORDER, default=NIVEL_ORDER)
            display_cols = [
                c for c in ["jerarquia", "titulo_seccion", "tipo_coincidencia", "nivel_cumplimiento", "analisis_general"]
                if c in results_df.columns
            ]
            filtered = results_df[results_df["nivel_cumplimiento"].isin(niveles_filtro)]

            def _row_style(row: pd.Series) -> list[str]:
                bg = NIVEL_COLORS.get(row["nivel_cumplimiento"], {}).get("bg", "")
                return [f"background-color: {bg}"] * len(row)

            st.dataframe(
                filtered[display_cols].style.apply(_row_style, axis=1), width="stretch", height=420
            )

        st.markdown("#### Exportar")
        c1, c2, c3 = st.columns(3)
        with c1:
            if "excel_bytes" in st.session_state:
                st.download_button(
                    "⬇️ Reporte Excel", data=st.session_state["excel_bytes"],
                    file_name=st.session_state["excel_name"],
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
        with c2:
            if "json_bytes" in st.session_state:
                st.download_button(
                    "⬇️ Reporte JSON", data=st.session_state["json_bytes"],
                    file_name="reporte_comparacion.json", mime="application/json",
                )
        with c3:
            log_text = "\n".join(get_log_lines())
            st.download_button("⬇️ Log de sesión", data=log_text.encode("utf-8"), file_name="sesion.log", mime="text/plain")

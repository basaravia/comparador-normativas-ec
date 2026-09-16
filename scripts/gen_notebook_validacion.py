#!/usr/bin/env python3
"""Genera VALIDACION-FUNCIONAL.ipynb en el worktree de validación."""
from pathlib import Path

import nbformat as nbf

DESTINO = Path.home() / "proyectos_documentos_normativos/comparador-normativas-ec-validacion/VALIDACION-FUNCIONAL.ipynb"

nb = nbf.v4.new_notebook()
C = []  # celdas


def md(texto: str) -> None:
    C.append(nbf.v4.new_markdown_cell(texto.strip()))


def code(texto: str) -> None:
    C.append(nbf.v4.new_code_cell(texto.strip()))


# ─────────────────────────────────────────────────────────────────────────────
md("""
# Validación funcional del comparador normativo

Valida **punto por punto** las capacidades del plan usando **solo los módulos del motor**
(`src/`), sin levantar Streamlit ni la API. Cada sección deja su salida impresa para
revisión humana.

**Orden de costo:** las secciones 1 a 5 no gastan un solo token de LLM (son estructurales
o usan embeddings locales en GPU). La sección 6 sí llama al LLM y está detrás de un
interruptor explícito.

| Sección | Qué valida | Costo |
|---|---|---|
| 1 | **Separación back / front / API** (la prueba clave) | — |
| 2 | Costuras de proveedor: cambiar backend sin tocar el pipeline | — |
| 3 | Ítem 1 — fail-fast y taxonomía de errores | — |
| 4 | Ítem 7 — selector de alcance · Ítem 8 — chunking parent-child | embeddings locales |
| 5 | Motor headless extremo a extremo: PDF → índice → recuperación | embeddings locales |
| 6 | Ítems 5, 6, 9, 10 — doble vía, cobertura, papel de trabajo, revisión manual | **LLM (Vertex)** |
""")

code("""
import sys, os, ast, json, warnings
from pathlib import Path

warnings.filterwarnings("ignore")
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

RAIZ = Path.cwd()
sys.path.insert(0, str(RAIZ))
print("Worktree:", RAIZ)
print("Rama:", os.popen("git branch --show-current").read().strip())
print("Commit:", os.popen("git rev-parse --short HEAD").read().strip())
""")

# ── 1 · separación de capas ───────────────────────────────────────────────────
md("""
---
## 1 · Separación entre backend, frontend y capa de API

**Por qué importa:** si el motor (`src/`) no depende de Streamlit ni de FastAPI, se puede
cambiar la lógica del backend sin que el front o la API se enteren. Si la dependencia
existiera —aunque sea un `import`— el motor dejaría de ser reutilizable y cada cambio
obligaría a tocar las tres capas.

La prueba es estática (se lee el AST de cada módulo, no hace falta ejecutar nada) y se
verifica en las dos direcciones.
""")

code('''
PROHIBIDOS_EN_MOTOR = {"streamlit", "fastapi", "uvicorn", "starlette", "app", "api"}

def imports_de(path: Path) -> set[str]:
    """Módulos de primer nivel que importa un archivo (absolutos; ignora los relativos)."""
    arbol = ast.parse(path.read_text(encoding="utf-8"))
    encontrados = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            for alias in nodo.names:
                encontrados.add(alias.name.split(".")[0])
        elif isinstance(nodo, ast.ImportFrom) and nodo.level == 0 and nodo.module:
            encontrados.add(nodo.module.split(".")[0])
    return encontrados

modulos_motor = sorted(p for p in (RAIZ / "src").glob("*.py") if p.name != "__init__.py")
violaciones = []
for m in modulos_motor:
    malos = imports_de(m) & PROHIBIDOS_EN_MOTOR
    if malos:
        violaciones.append((m.name, sorted(malos)))

print(f"Módulos del motor analizados: {len(modulos_motor)}")
for nombre, malos in violaciones:
    print(f"  ✗ src/{nombre} importa {malos}")
if not violaciones:
    print("  ✓ Ningún módulo de src/ importa Streamlit, FastAPI ni las capas app/ o api/")
''')

md("""
### 1.2 · La dependencia va en un solo sentido

El motor no conoce a sus consumidores, pero los consumidores sí conocen al motor. Eso es
lo que hace que el backend sea intercambiable por debajo.
""")

code('''
def usa_motor(carpeta: str) -> list[str]:
    archivos = sorted(Path(RAIZ / carpeta).rglob("*.py"))
    return [p.relative_to(RAIZ).as_posix() for p in archivos if "src" in imports_de(p)]

for capa in ("app", "api"):
    consumidores = usa_motor(capa)
    print(f"{capa}/ → importa src/ en {len(consumidores)} archivo(s):")
    for c in consumidores[:6]:
        print("   ", c)
    if len(consumidores) > 6:
        print(f"    … y {len(consumidores) - 6} más")
    print()

print("Sentido de la dependencia:  app/ ─┐")
print("                                  ├─→ src/   (nunca al revés)")
print("                            api/ ─┘")
''')

md("""
### 1.3 · El motor arranca sin el frontend en memoria

Prueba dinámica: se importa todo el motor y se comprueba que ni Streamlit ni FastAPI
llegaron a cargarse. Si el motor los arrastrara, un despliegue headless (un worker, un
cron, un notebook como este) pagaría el costo de importarlos sin usarlos.
""")

code('''
import importlib

for nombre in ("src.service", "src.comparator", "src.dual", "src.coverage",
               "src.search_engine", "src.providers", "src.scope", "src.papel_trabajo"):
    importlib.import_module(nombre)

colados = [m for m in ("streamlit", "fastapi", "uvicorn", "starlette") if m in sys.modules]
print("Motor importado por completo.")
print("Frameworks de UI/API cargados en memoria:", colados or "ninguno  ✓")
''')

# ── 2 · costuras de proveedor ────────────────────────────────────────────────
md("""
---
## 2 · Costuras de proveedor — cambiar de backend sin tocar el pipeline

El pipeline nunca instancia un cliente de modelo: se lo pide a las fábricas de
`src/providers.py`. Cambiar de proveedor es cambiar un `ProviderSpec`, no editar el motor.
Acá se resuelven specs distintos **sin ejecutar ninguna llamada de red**.
""")

code('''
from src.providers import Provider, ProviderSpec, CAPACIDADES, resolve_device
from src import config as cfg

print("Proveedores declarados y qué sabe hacer cada uno:")
print(f"{'proveedor':<16} {'chat':>5} {'embeddings':>11} {'lista modelos':>14}")
for prov, cap in CAPACIDADES.items():
    print(f"{prov.value:<16} {str(cap.chat):>5} {str(cap.embeddings):>11} {str(cap.listado_modelos):>14}")

print("\\nResolución de specs (sin llamar a la red):")
for spec in (ProviderSpec(proveedor=Provider.VERTEX),
             ProviderSpec(proveedor=Provider.DMR)):
    r = spec.resuelto()
    print(f"  {r.proveedor.value:<16} modelo={r.modelo!r:<28} timeout={r.timeout_efectivo}s reintentos={r.reintentos_efectivos}")

print("\\nConfiguración activa de esta rama Linux:")
print(f"  LLM        : {cfg.VERTEX_LLM_MODEL}  (Vertex, región {cfg.VERTEX_LOCATION})")
print(f"  Embeddings : {cfg.OLLAMA_EMBED_MODEL}  ({cfg.OLLAMA_BASE_URL})")
print(f"  Reranker   : {cfg.RERANKER_MODEL}")
print(f"  Device resuelto para torch: {resolve_device('auto')}")
''')

# ── 3 · fail-fast ─────────────────────────────────────────────────────────────
md("""
---
## 3 · Ítem 1 — fail-fast: un fallo técnico nunca se disfraza de veredicto

La regla del ítem: un problema de **infraestructura** aborta la corrida; uno de
**contenido** degrada solo esa fila. Lo que nunca puede pasar es que un error se escriba
en el papel de trabajo como si fuera un juicio de cumplimiento.
""")

code('''
from src.errors import (ComparadorError, LLMUnavailableError, ModelNotFoundError,
                        ProviderConfigError, GradingParseError, AnalysisParseError,
                        classify_llm_exception, es_error_de_infraestructura)

print("Jerarquía — lo que hereda de LLMUnavailableError aborta la corrida:")
for clase in (ModelNotFoundError, ProviderConfigError, GradingParseError, AnalysisParseError):
    aborta = issubclass(clase, LLMUnavailableError)
    print(f"  {clase.__name__:<22} aborta={aborta}")

print("\\nClasificación de excepciones reales:")
class AuthenticationError(Exception): pass
class APIConnectionError(Exception): pass
class OutputParserException(Exception): pass

casos = [
    AuthenticationError("401 credenciales rechazadas"),
    APIConnectionError("connection refused"),
    OutputParserException("no se pudo parsear el JSON"),
    RuntimeError('error while getting model "gemini"'),
]
for exc in casos:
    clasificado = classify_llm_exception(exc)
    print(f"  {type(exc).__name__:<24} → {type(clasificado).__name__:<22} "
          f"infraestructura={es_error_de_infraestructura(exc)}")
''')

# ── 4 · alcance + chunking ────────────────────────────────────────────────────
md("""
---
## 4 · Ítem 7 (alcance) e Ítem 8 (chunking parent-child)

Se tabula la normativa real de `Normativa2026/` y se ejercita el selector de alcance y el
chunking semántico. **El chunking es el que tuvo un bug corregido**: la búsqueda debía
devolver *k artículos*, no *k fragmentos del mismo artículo*.
""")

code('''
from src.document_parser import NormativaParser
from src import scope

NORMA = RAIZ / "Normativa2026" / "Proyecto-de-Ley-Organica-Organica-para-Reprimir-y-Prevenir-el-Lavado-de-Activos-y-la-Financiacion-del-Terrorismo.pdf"

parser = NormativaParser(device="cpu", do_ocr=False, cache_dir="output/docling")
normativa_df = parser.parse_pdf(NORMA)
print(f"Elementos tabulados: {len(normativa_df)}")
print("Columnas:", list(normativa_df.columns))
if "tipo_elemento" in normativa_df.columns:
    print("\\nPor tipo de elemento:")
    print(normativa_df["tipo_elemento"].value_counts().to_string())
''')

code('''
# Ítem 7 — el selector de alcance recorta el universo a analizar
solo_articulos = scope.filtrar_articulos(normativa_df, incluir_referencias=False)
con_referencias = scope.filtrar_articulos(normativa_df, incluir_referencias=True)
print(f"Artículos sustantivos (sin referencias del preámbulo): {len(solo_articulos)}")
print(f"Incluyendo referencias                               : {len(con_referencias)}")
print(f"→ el alcance descarta {len(con_referencias) - len(solo_articulos)} elementos que nadie tiene que cumplir")
''')

code('''
# Ítem 8 — chunking parent-child: los sub-chunks conservan el artículo padre
from src.chunking import chunk_normativa_df, detectar_columna_padre

chunks_df = chunk_normativa_df(solo_articulos)
col_padre = detectar_columna_padre(chunks_df)
largos = solo_articulos["embed_text"].fillna("").str.len()
print(f"Artículos: {len(solo_articulos)}  →  sub-chunks: {len(chunks_df)}")
print(f"Columna que apunta al artículo padre: {col_padre!r}")
print(f"Longitud de artículo — mediana {largos.median():.0f} / máxima {largos.max():.0f} caracteres")
if col_padre:
    por_padre = chunks_df.groupby(col_padre).size()
    print(f"Artículos con más de un fragmento: {(por_padre > 1).sum()}")
''')

md("""
> **Ojo con este resultado.** El artículo más largo de esta ley no llega al umbral del
> chunker, así que **no se subdividió nada** y la agrupación padre-hijo quedó sin
> ejercitar: cualquier prueba de "top-k trae k artículos distintos" pasaría de forma
> trivial, porque solo hay un fragmento por artículo. Para validar de verdad el ítem 8
> hace falta un artículo que sí se parta — se construye uno sintético.
""")

code('''
import pandas as pd

ARTICULO_SINTETICO = "ART-LARGO-SINTETICO"
largo = solo_articulos.iloc[0].copy()
largo["element_id"] = ARTICULO_SINTETICO
largo["numero"] = "999"
largo["encabezado"] = "Artículo extenso de prueba"
largo["contenido"] = largo["embed_text"] = " ".join(
    f"Numeral {i}. El sujeto obligado conservará la documentación de respaldo de cada "
    f"operación, registrará su trazabilidad y la mantendrá disponible para la autoridad "
    f"competente durante el plazo legal aplicable, bajo responsabilidad del oficial de "
    f"cumplimiento." for i in range(1, 41)
)

df_con_largo = pd.concat([solo_articulos, pd.DataFrame([largo])], ignore_index=True)
chunks2 = chunk_normativa_df(df_con_largo)
col2 = detectar_columna_padre(chunks2)
fragmentos = chunks2[chunks2[col2] == ARTICULO_SINTETICO]
print(f"Artículo sintético: {len(largo['embed_text'])} caracteres")
print(f"  → se subdividió en {len(fragmentos)} fragmentos")
print(f"Total de sub-chunks del corpus: {len(chunks2)} (antes {len(chunks_df)})")
''')

md("""
Ahora sí la prueba tiene sentido: se indexan los fragmentos y se consulta con el texto
del artículo largo. **Sin agrupación, sus propios fragmentos coparían el top-k y
desplazarían a los demás artículos.**
""")

code('''
from src.service import ServiceConfig, construir_indice as _construir_indice

_cfg_chunk = ServiceConfig(embed_backend_kind="remoto", embed_model=cfg.OLLAMA_EMBED_MODEL,
                           base_url=cfg.OLLAMA_BASE_URL, use_reranker=False)
indice_chunk = _construir_indice(chunks2, _cfg_chunk)

consulta = "conservar la documentación de respaldo y su trazabilidad para la autoridad competente"
res = indice_chunk.semantic_search(consulta, top_k=5, min_score=0.0)

ids = [r.get("element_id") for r in res]
veces_sintetico = ids.count(ARTICULO_SINTETICO)
print(f"Top-5 → artículos: {[str(r.get('numero')) for r in res]}")
print(f"Artículos distintos: {len(set(ids))}/5")
print(f"El artículo subdividido aparece {veces_sintetico} vez/veces "
      f"(debe ser 1: sus {len(fragmentos)} fragmentos se agrupan en el padre)")
print()
if veces_sintetico == 1 and len(set(ids)) == len(ids):
    print("✓ La agrupación padre-hijo funciona: top_k devuelve k ARTÍCULOS, no k fragmentos.")
else:
    print("✗ Regresión: los fragmentos de un mismo artículo están ocupando varios puestos del top-k.")

devuelto = next((r for r in res if r.get("element_id") == ARTICULO_SINTETICO), None)
if devuelto is not None:
    tiene_procedencia = "chunk_id_match" in devuelto or "chunk_text_match" in devuelto
    print(f"El resultado viaja como artículo padre (sin chunk_id propio): {'chunk_id' not in devuelto}")
    print(f"Conserva la procedencia del fragmento que hizo match: {tiene_procedencia}")
''')

# ── 5 · motor headless ────────────────────────────────────────────────────────
md("""
---
## 5 · Motor headless de extremo a extremo (sin LLM)

PDF → tabulación → índice vectorial → recuperación semántica, corriendo entero desde este
notebook. Es la demostración práctica de la sección 1: el mismo motor que usa el front
funciona sin front.

Los embeddings salen de Ollama en GPU local (gratis). **La agrupación por artículo padre
se verifica acá**: si un artículo largo copara el top-k con sus propios fragmentos, el
resultado estaría mal.
""")

code('''
from src.service import ServiceConfig, construir_indice, construir_backend_embeddings

config = ServiceConfig(embed_backend_kind="remoto",
                       embed_model=cfg.OLLAMA_EMBED_MODEL,
                       base_url=cfg.OLLAMA_BASE_URL,
                       use_reranker=False)   # el reranker se prueba aparte; acá interesa el índice

backend = construir_backend_embeddings(config)
print("Backend de embeddings:", type(backend).__name__, "· modelo:", backend.nombre_modelo)
print("Dimensión del espacio vectorial:", backend.dim)
''')

code('''
indice = construir_indice(chunks_df, config)
print(f"Índice construido sobre {len(chunks_df)} fragmentos.")

CONSULTAS = [
    "conservación de registros de clientes por diez años",
    "identificación del beneficiario final de una persona jurídica",
    "reporte de operaciones inusuales a la unidad de análisis financiero",
]
for q in CONSULTAS:
    res = indice.semantic_search(q, top_k=3, min_score=0.0)
    ids_padre = [r.get("element_id") for r in res]
    print(f"\\n· {q}")
    for r in res:
        print(f"    art. {str(r.get('numero','?')):<5} sim={r.get('similarity'):.3f}  {str(r.get('encabezado',''))[:62]}")
    print(f"    artículos distintos en el top-3: {len(set(ids_padre))}/3  "
          f"{'✓' if len(set(ids_padre)) == len(ids_padre) else '✗ hay fragmentos repetidos del mismo artículo'}")
''')

# ── 6 · doble vía con LLM ─────────────────────────────────────────────────────
md("""
---
## 6 · Ítems 5, 6, 9 y 10 — doble vía, cobertura, papel de trabajo y revisión manual

Esta sección **sí llama al LLM de Vertex** y por eso está apagada por defecto. Corre la
comparación en doble vía de los tres manuales mock contra la ley, que es la prueba de que
el sistema distingue `cumple` / `parcial` / `omision`.

Para ejecutarla, poné `EJECUTAR_LLM = True` y volvé a correr la celda. Conviene empezar con
`MAX_SECCIONES` y `MAX_ARTICULOS` bajos: el costo crece con el producto de ambos.

> El mapeo de qué manual debería dar qué veredicto está en
> `document_test/LEEME-MANUALES-MOCK.md`. Está aparte a propósito, para que la revisión
> pueda hacerse a ciegas.
""")

code('''
EJECUTAR_LLM = True             # ← apagalo para saltar la sección sin gastar tokens
BACKEND_LLM  = "groq"           # "vertex" | "groq" | "openrouter"
MAX_SECCIONES = 3               # secciones del manual a analizar (Vía 1)
MAX_ARTICULOS = 4               # artículos de la norma a analizar (Vía 2)
MANUAL = "MOCK-DEMO-01.pdf"     # perfil esperado: "parcial" (ver LEEME-MANUALES-MOCK.md)

from src.settings import get as get_setting

def config_llm(backend: str) -> ServiceConfig:
    """ServiceConfig para el backend pedido, con el modelo SIEMPRE explícito.

    `llm_model` no se puede omitir con groq/openrouter: `ProviderSpec.resuelto()`
    para `Provider.DMR` cae a `DMR_LLM_MODEL`, que en esta rama vale el modelo de
    Vertex — un llamador que lo omita termina mandando "gemini-..." al endpoint de
    Groq y recibe un error de modelo inexistente que no dice eso.
    """
    base = dict(embed_backend_kind="remoto", embed_model=cfg.OLLAMA_EMBED_MODEL,
                base_url=cfg.OLLAMA_BASE_URL, use_reranker=False, temperature=0.0)
    if backend == "vertex":
        return ServiceConfig(llm_backend_kind="vertex", llm_model=None, **base)
    env = "GROQ_LLM_MODEL" if backend == "groq" else "OPENROUTER_LLM_MODEL"
    return ServiceConfig(llm_backend_kind=backend, llm_model=get_setting(env, default=""), **base)

config_corrida = config_llm(BACKEND_LLM)
print(f"Backend: {BACKEND_LLM} · modelo: {config_corrida.llm_model or cfg.VERTEX_LLM_MODEL}")
''')

code('''
if not EJECUTAR_LLM:
    print("Sección apagada (EJECUTAR_LLM = False). No se hizo ninguna llamada al LLM.")
else:
    from src.document_parser import ManualParser
    from src.service import construir_indice_manual, comparar_dual

    manual_df = ManualParser(max_tokens=512, device="cpu").parse_pdf(RAIZ / "document_test" / MANUAL)
    manual_df = manual_df.head(MAX_SECCIONES)
    norma_df = solo_articulos.head(MAX_ARTICULOS)
    print(f"Manual: {MANUAL} — {len(manual_df)} secciones · Norma — {len(norma_df)} artículos")

    indice_norma = construir_indice(norma_df, config_corrida)
    indice_manual = construir_indice_manual(manual_df, config_corrida)
    bundle = comparar_dual(
        indice_normativa=indice_norma, indice_manual=indice_manual,
        manual_df=manual_df, normativa_df=norma_df, config=config_corrida,
        progress_callback=lambda via, h, t: print(f"   {via}: {h}/{t}", end="\\r"),
    )
    print("\\nCorrida completa.")
''')

code('''
if EJECUTAR_LLM:
    import pandas as pd
    pd.set_option("display.max_colwidth", 70)

    print("── Vía 1 · una fila por sección del manual ──")
    v1 = bundle.vista_manual[["jerarquia", "nivel_cumplimiento", "n_articulos_confirmados",
                              "requiere_revision_manual"]]
    print(v1.to_string(index=False))

    print("\\n── Distribución de veredictos (ítem 6) ──")
    print(bundle.vista_manual["nivel_cumplimiento"].value_counts(dropna=False).to_string())

    print("\\n── Vía 2 · cobertura por artículo (ítem 5) ──")
    v2 = bundle.vista_normativa[["numero", "cubierto", "nivel_adopcion", "n_secciones_confirmadas"]]
    print(v2.to_string(index=False))

    print(f"\\nCobertura global: {bundle.cobertura.porcentaje:.1%}")
    print("Alerta:", bundle.alerta_cobertura or "sin alerta — cobertura completa")

    # Coherencia entre las dos columnas de veredicto de la Vía 2. `cubierto` es
    # booleano y sale de si hay aristas confirmadas (que pueden venir de la Vía 1);
    # `nivel_adopcion` es el veredicto del LLM sobre el artículo completo (Vía 2).
    # Una fila que diga cubierto=True y nivel_adopcion="no_cubierto" es una
    # contradicción visible en el papel de trabajo, y quien lo revise la va a rechazar.
    vn = bundle.vista_normativa
    contradictorias = vn[(vn["cubierto"]) & (vn["nivel_adopcion"] == "no_cubierto")]
    print("\\n── Coherencia entre Vía 1 y Vía 2 ──")
    print(f"Artículos con cubierto=True pero nivel_adopcion='no_cubierto': "
          f"{len(contradictorias)} de {len(vn)}")
    if len(contradictorias):
        print("  ⚠ Las dos vías discrepan en esos artículos y la vista los muestra sin señalarlo.")
        print(contradictorias[["numero", "cubierto", "nivel_adopcion",
                               "n_secciones_confirmadas"]].to_string(index=False))

    print("\\n── Ítem 10 · filas marcadas para revisión manual ──")
    marcadas = bundle.vista_manual[bundle.vista_manual["requiere_revision_manual"]]
    print(f"{len(marcadas)} de {len(bundle.vista_manual)} secciones marcadas")
    motivos = sorted({m for ms in bundle.vista_manual["motivos_revision"] for m in ms})
    print("Motivos disparados:", motivos or "ninguno")
''')

code('''
if EJECUTAR_LLM:
    # Ítem 9 · papel de trabajo en Excel, gobernado por templates/papel_trabajo.yaml
    from src.service import RunPaths, nuevo_run_id, exportar

    rutas = RunPaths(run_id=nuevo_run_id())
    generados = exportar(bundle.vista_manual, rutas, bundle=bundle,
                         metadatos={"run_id": rutas.run_id, "workspace_id": "local"})
    import openpyxl
    hojas = openpyxl.load_workbook(generados["excel"]).sheetnames
    print("Excel generado:", generados["excel"])
    print("Hojas:", hojas)
''')

# ── cierre ────────────────────────────────────────────────────────────────────
md("""
---
## Resumen para revisión

Al terminar la corrida, lo que hay que mirar:

1. **Sección 1** — no debe haber ninguna `✗`. Si `src/` importara Streamlit o FastAPI, la
   separación de capas estaría rota y cambiar el backend dejaría de ser transparente.
2. **Sección 4/5** — en cada consulta, los artículos del top-3 deben ser **distintos**. Si
   se repiten, volvió el bug de agrupación del chunking.
3. **Sección 6** — contrastar la distribución de veredictos contra
   `document_test/LEEME-MANUALES-MOCK.md`: `MOCK-DEMO-03` debería concentrar `cumple`,
   `MOCK-DEMO-01` `parcial`, y `MOCK-DEMO-02` disparar la alerta de cobertura de la Vía 2.
""")

nb["cells"] = C
nb.metadata = {
    "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
    "language_info": {"name": "python", "version": "3.12"},
}
DESTINO.parent.mkdir(parents=True, exist_ok=True)
nbf.write(nb, str(DESTINO))
print(f"{DESTINO}  ({len(C)} celdas)")

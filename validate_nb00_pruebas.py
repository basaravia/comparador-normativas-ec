"""
Validation script for 00_pruebas.ipynb
Tests: import chain only — markitdown, openai, MarkItDown instantiation.
Docker Model Runner (localhost:12434) is NOT running; actual LLM call is skipped.
"""
import sys

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


# ── Test 1: import markitdown ────────────────────────────────────────────────
print("\n=== Test 1: import markitdown ===")
try:
    from markitdown import MarkItDown
    check("markitdown importa sin error", True)
    check("MarkItDown es una clase callable", callable(MarkItDown))
except ImportError as e:
    check("markitdown importa sin error", False, str(e))
    sys.exit(1)


# ── Test 2: import openai ────────────────────────────────────────────────────
print("\n=== Test 2: import openai ===")
try:
    from openai import OpenAI
    check("openai importa sin error", True)
    check("OpenAI es una clase callable", callable(OpenAI))
except ImportError as e:
    check("openai importa sin error", False, str(e))
    sys.exit(1)


# ── Test 3: instanciar MarkItDown sin LLM ────────────────────────────────────
print("\n=== Test 3: instanciar MarkItDown sin LLM backend ===")
try:
    md = MarkItDown()
    check("MarkItDown() instancia sin error (modo texto directo)", True)
except Exception as e:
    check("MarkItDown() instancia sin error", False, str(e))


# ── Test 4: instanciar OpenAI con URL local (sin conectar) ───────────────────
print("\n=== Test 4: instanciar OpenAI client apuntando a Docker Model Runner ===")
try:
    client = OpenAI(
        base_url="http://localhost:12434/engines/llama.cpp/v1/",
        api_key="docker",
    )
    check("OpenAI() instancia con base_url localhost:12434 sin error", True)
    # Verificar que el atributo base_url está configurado
    check(
        "base_url contiene 'localhost:12434'",
        "localhost:12434" in str(client.base_url),
        f"base_url={client.base_url}",
    )
except Exception as e:
    check("OpenAI() instancia con base_url localhost:12434", False, str(e))


# ── Test 5: instanciar MarkItDown con llm_client (objeto solo, sin llamar) ───
print("\n=== Test 5: instanciar MarkItDown con llm_client configurado ===")
LLM_MODEL = "ai/qwen3-vl:4B-UD-Q4_K_XL"
try:
    md_with_llm = MarkItDown(
        llm_client=client,
        llm_model=LLM_MODEL,
    )
    check("MarkItDown(llm_client=..., llm_model=...) instancia sin error", True)
except Exception as e:
    check("MarkItDown(llm_client=..., llm_model=...) instancia sin error", False, str(e))

print("\n  [INFO] Llamadas reales a localhost:12434 omitidas (Docker Model Runner no disponible)")


# ── Test 6: enable_plugins (si markitdown lo soporta) ────────────────────────
print("\n=== Test 6: MarkItDown(enable_plugins=True) ===")
try:
    md_plugins = MarkItDown(enable_plugins=True)
    check("MarkItDown(enable_plugins=True) instancia sin error", True)
except TypeError as e:
    # Versiones antiguas de markitdown no tienen enable_plugins
    check(
        "MarkItDown(enable_plugins=True) [parámetro puede no existir en esta versión]",
        False,
        f"TypeError: {e}",
    )
except Exception as e:
    check("MarkItDown(enable_plugins=True) instancia sin error", False, str(e))


# ── Resumen ───────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
passed = sum(1 for _, ok in results if ok)
failed = sum(1 for _, ok in results if not ok)
print(f"RESULTADO NB00: {passed} passed, {failed} failed  ({passed}/{len(results)})")
if failed:
    # enable_plugins failure is non-fatal (version-dependent), flag but don't exit 1
    # unless a core import/instantiation failed
    core_failures = [
        label for label, ok in results
        if not ok and "enable_plugins" not in label
    ]
    if core_failures:
        print("CHECKS CRÍTICOS FALLIDOS:")
        for label in core_failures:
            print(f"  - {label}")
        sys.exit(1)
    else:
        print("STATUS: PASS (advertencia no crítica en enable_plugins)")
else:
    print("STATUS: PASS")

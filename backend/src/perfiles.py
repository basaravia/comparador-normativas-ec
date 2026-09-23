"""Perfiles de modelos: un parámetro decide el backend de cada pieza del pipeline.

Un perfil es una fila de `config/perfiles.yaml`: `{llm, embeddings}`. Elige QUÉ
backend se usa; no toca credenciales ni nombres de modelo, que siguen en sus variables de
entorno (FOUNDRY_AI_*, GROQ_*, DMR_*, EMBED_*…). Por eso el archivo se versiona y puede tener
todos los proveedores configurados a la vez.

Precedencia, de mayor a menor (la aplica `ServiceConfig`):
    petición de la API  >  LLM_BACKEND / EMBED_BACKEND  >  MODEL_PROFILE  >  `activo` del YAML

Un perfil desconocido o un valor inválido falla al leerlo, nombrando el perfil y el campo:
mejor abortar al arrancar que descubrirlo a mitad de una corrida de horas.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

from .errors import ProviderConfigError
from .settings import get

logger = logging.getLogger(__name__)

PERFILES_PATH = Path(__file__).resolve().parent.parent / "config" / "perfiles.yaml"

# Valores canónicos de `ServiceConfig`. "ollama" es un alias legible de "remoto" (el cliente
# openai-compat apuntando a EMBED_BASE_URL, que por defecto es Ollama en localhost).
LLM_BACKENDS = ("vertex", "openrouter", "groq", "foundry", "local")
EMBED_BACKENDS = ("remoto", "local", "vertex", "foundry")
_ALIAS_EMBED = {"ollama": "remoto"}
# El reranker no es un parámetro: siempre es local (Qwen3-Reranker, multilingüe, sirve para
# español) y no depende del LLM ni de los embeddings elegidos. No hay reranker como servicio.
_CAMPOS = ("llm", "embeddings")


@dataclass(frozen=True)
class Perfil:
    nombre: str
    llm: str
    embeddings: str


# Lo que se usa si no existe el YAML: el comportamiento histórico del proyecto.
PERFIL_POR_DEFECTO = Perfil("default", llm="vertex", embeddings="remoto")


def _validar(nombre: str, datos: object) -> Perfil:
    if not isinstance(datos, dict):
        raise ProviderConfigError(f"Perfil '{nombre}': debe ser un mapa con {', '.join(_CAMPOS)}")
    sobrantes = sorted(set(datos) - set(_CAMPOS))
    if sobrantes:
        raise ProviderConfigError(
            f"Perfil '{nombre}': campo(s) desconocido(s) {', '.join(sobrantes)}; "
            f"los válidos son {', '.join(_CAMPOS)}"
        )
    faltan = [c for c in ("llm", "embeddings") if not datos.get(c)]
    if faltan:
        raise ProviderConfigError(f"Perfil '{nombre}': falta {', '.join(faltan)}")

    embeddings = _ALIAS_EMBED.get(str(datos["embeddings"]).strip().lower(),
                                  str(datos["embeddings"]).strip().lower())
    llm = str(datos["llm"]).strip().lower()
    for campo, valor, validos in (("llm", llm, LLM_BACKENDS),
                                  ("embeddings", embeddings, EMBED_BACKENDS)):
        if valor not in validos:
            extra = ", ".join(validos) + (", ollama" if campo == "embeddings" else "")
            raise ProviderConfigError(
                f"Perfil '{nombre}': {campo}={valor!r} no es válido; usa uno de: {extra}"
            )
    return Perfil(nombre, llm=llm, embeddings=embeddings)


def cargar_perfiles(path: Path | None = None) -> tuple[str | None, dict[str, Perfil]]:
    """Lee el YAML y devuelve `(activo, {nombre: Perfil})`. Sin archivo: `(None, {})`."""
    ruta = path or PERFILES_PATH
    if not ruta.exists():
        return None, {}
    try:
        crudo = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise ProviderConfigError(f"{ruta.name} no es un YAML válido: {e}") from e
    if not isinstance(crudo, dict) or not isinstance(crudo.get("perfiles"), dict):
        raise ProviderConfigError(f"{ruta.name}: falta la sección 'perfiles'")
    perfiles = {str(n): _validar(str(n), d) for n, d in crudo["perfiles"].items()}
    activo = crudo.get("activo")
    return (str(activo) if activo else None), perfiles


def perfil_activo(path: Path | None = None) -> Perfil:
    """El perfil vigente: `MODEL_PROFILE`, o `activo` del YAML, o el histórico por defecto."""
    activo_yaml, perfiles = cargar_perfiles(path)
    elegido = str(get("MODEL_PROFILE", default="") or "").strip() or activo_yaml

    if not elegido:
        return perfiles.get(PERFIL_POR_DEFECTO.nombre, PERFIL_POR_DEFECTO)
    if not perfiles:
        raise ProviderConfigError(
            f"Se pidió el perfil {elegido!r} pero no existe {(path or PERFILES_PATH).name}"
        )
    if elegido not in perfiles:
        raise ProviderConfigError(
            f"Perfil {elegido!r} no definido; los disponibles son: {', '.join(sorted(perfiles))}"
        )
    return perfiles[elegido]

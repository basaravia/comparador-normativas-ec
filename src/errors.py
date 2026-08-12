"""Taxonomía de errores: qué aborta la corrida y qué degrada una fila.

El ítem 1 del anexo nace de una confusión concreta: hoy cualquier excepción —que el
modelo no responda, que el JSON no parsee, que se caiga la red— acaba produciendo
``nivel_cumplimiento="no_aplica"`` con el mensaje de error incrustado en el análisis. El
auditor recibe un papel de trabajo que afirma "no aplica" sobre secciones que el modelo
nunca llegó a leer. Es peor que un fallo ruidoso: es un fallo que se disfraza de resultado.

La distinción que impone este módulo:

  **Infraestructura** — el modelo no está, no responde, o no existe. Ninguna fila posterior
  va a salir mejor que esta. **Aborta** la corrida, conserva lo hecho y lo etiqueta como
  parcial.

  **Contenido** — el modelo respondió pero su salida no encaja en el esquema. Es específico
  de esa fila; la siguiente puede ir bien. **Degrada** esa fila y sigue.

Un fallo técnico nunca vuelve a expresarse como un veredicto de cumplimiento (supuesto S2).
"""
from __future__ import annotations


class ComparadorError(Exception):
    """Raíz de la jerarquía. Permite capturar todo lo del dominio sin tragarse un
    ``KeyboardInterrupt`` ni un ``MemoryError``."""


# ── Infraestructura: abortan ──────────────────────────────────────────────────

class LLMUnavailableError(ComparadorError):
    """El backend de modelos no está disponible: conexión, timeout, 5xx.

    Incluye el caso que dispara el ítem 1: ``error while getting model "…"``, que el
    servidor devuelve cuando el modelo existe en el catálogo pero no se puede cargar.
    """

    def __init__(self, mensaje: str, *, modelo: str | None = None, url: str | None = None,
                 causa: BaseException | None = None) -> None:
        super().__init__(mensaje)
        self.modelo = modelo
        self.url = url
        self.causa = causa

    def __str__(self) -> str:
        partes = [super().__str__()]
        if self.modelo:
            partes.append(f"modelo={self.modelo}")
        if self.url:
            partes.append(f"url={self.url}")
        return " · ".join(partes)


class ModelNotFoundError(LLMUnavailableError):
    """El modelo configurado no existe en el proveedor.

    Hereda de ``LLMUnavailableError`` porque el efecto es el mismo —abortar— pero se
    distingue para que el ítem 4 pueda añadir la lista de modelos disponibles al mensaje.
    """

    def __init__(self, mensaje: str, *, modelo: str | None = None, url: str | None = None,
                 disponibles: list[str] | None = None,
                 causa: BaseException | None = None) -> None:
        super().__init__(mensaje, modelo=modelo, url=url, causa=causa)
        self.disponibles = disponibles or []

    def __str__(self) -> str:
        base = super().__str__()
        if self.disponibles:
            return f"{base}. Disponibles: {', '.join(self.disponibles)}"
        return base


class ProviderConfigError(ComparadorError):
    """Faltan credenciales o parámetros del proveedor. Aborta antes de gastar un token.

    La usa el ítem P-a; vive aquí para que la taxonomía esté en un solo sitio.
    """

    def __init__(self, mensaje: str, *, faltantes: list[str] | None = None) -> None:
        super().__init__(mensaje)
        self.faltantes = faltantes or []


class RunAbortedError(ComparadorError):
    """La corrida se detuvo: por cancelación del usuario o en cascada tras un fallo.

    Lleva el recuento de lo procesado para que la UI pueda decir cuántas secciones
    quedaron sin analizar en vez de mostrar un resultado incompleto sin avisar.
    """

    def __init__(self, mensaje: str, *, completadas: int = 0, total: int = 0,
                 causa: BaseException | None = None) -> None:
        super().__init__(mensaje)
        self.completadas = completadas
        self.total = total
        self.causa = causa
        # Resultados parciales, si los hubo. Los rellena `DocumentComparator.run()`.
        # Van con la excepción y no se descartan: están pagados en tiempo de LLM y la
        # UI puede mostrarlos etiquetados como incompletos.
        self.parciales = None

    @property
    def omitidas(self) -> int:
        return max(self.total - self.completadas, 0)


# ── Contenido: degradan una fila ──────────────────────────────────────────────

class GradingParseError(ComparadorError):
    """La respuesta del modelo no mapea al esquema esperado.

    Degrada solo la fila afectada. **Nunca** debe traducirse en candidatos marcados como
    relevantes por defecto: ese es el fallo del ítem 4, donde un parseo roto dejaba pasar
    falsos positivos de cumplimiento.
    """

    def __init__(self, mensaje: str, *, respuesta_cruda: str | None = None,
                 causa: BaseException | None = None) -> None:
        super().__init__(mensaje)
        self.respuesta_cruda = respuesta_cruda
        self.causa = causa


class AnalysisParseError(GradingParseError):
    """El análisis comparativo no mapea al esquema. Mismo tratamiento que el grading."""


# ── Clasificación ─────────────────────────────────────────────────────────────

# Fragmentos que el backend devuelve cuando el modelo no se puede cargar. Se comparan
# contra el texto de la excepción porque llegan como un 500 genérico, sin tipo propio.
_SENALES_MODELO_CAIDO = (
    "error while getting model",
    "model not found",
    "no such model",
    "failed to load model",
    "model does not exist",
)

_SENALES_CONEXION = (
    "connection refused",
    "connection error",
    "cannot connect",
    "timed out",
    "timeout",
    "max retries exceeded",
)


def _texto(exc: BaseException) -> str:
    return str(exc).lower()


def es_error_de_infraestructura(exc: BaseException) -> bool:
    """True si la excepción indica que el backend no va a responder mejor en la fila
    siguiente. Es el criterio que decide abortar."""
    return isinstance(classify_llm_exception(exc), LLMUnavailableError)


def classify_llm_exception(
    exc: BaseException,
    *,
    modelo: str | None = None,
    url: str | None = None,
) -> ComparadorError:
    """Traduce una excepción de ``openai`` / ``httpx`` / ``langchain`` a esta taxonomía.

    Se clasifica por tipo cuando el tipo es informativo, y por texto cuando no lo es: el
    caso del ítem 1 llega como un 500 corriente cuyo único indicio está en el mensaje.

    Las excepciones que ya son ``ComparadorError`` se devuelven intactas: la clasificación
    es idempotente y se puede llamar en cualquier punto de la pila sin re-envolver.
    """
    if isinstance(exc, ComparadorError):
        return exc

    texto = _texto(exc)
    nombre = type(exc).__name__

    # 1 · El modelo no se puede cargar. Va primero: llega como 500 y si no se mira el
    #     texto acaba clasificado como un error de servidor cualquiera.
    if any(s in texto for s in _SENALES_MODELO_CAIDO):
        return ModelNotFoundError(
            f"El backend no pudo cargar el modelo: {exc}",
            modelo=modelo, url=url, causa=exc,
        )

    # 2 · Fallos de parseo del esquema. Contenido, no infraestructura.
    if nombre in ("OutputParserException", "ValidationError"):
        return GradingParseError(
            f"La respuesta del modelo no encaja en el esquema: {exc}",
            respuesta_cruda=getattr(exc, "llm_output", None), causa=exc,
        )

    # 3 · Conectividad y disponibilidad, por tipo.
    if nombre in (
        "APIConnectionError", "APITimeoutError", "InternalServerError",
        "ConnectError", "ConnectTimeout", "ReadTimeout", "PoolTimeout",
        "NetworkError", "RemoteProtocolError",
    ):
        return LLMUnavailableError(
            f"El backend de modelos no responde: {exc}", modelo=modelo, url=url, causa=exc,
        )

    # 4 · Credenciales y permisos: no se arreglan reintentando.
    if nombre in ("AuthenticationError", "PermissionDeniedError"):
        return ProviderConfigError(f"Credenciales rechazadas por el proveedor: {exc}")

    # 5 · Conectividad por texto, para las envolturas que pierden el tipo original.
    if any(s in texto for s in _SENALES_CONEXION):
        return LLMUnavailableError(
            f"El backend de modelos no responde: {exc}", modelo=modelo, url=url, causa=exc,
        )

    # 6 · 4xx del cliente: petición mal formada. Es un defecto nuestro, no del backend,
    #     y no mejora en la fila siguiente.
    if nombre in ("BadRequestError", "UnprocessableEntityError", "NotFoundError"):
        return LLMUnavailableError(
            f"El backend rechazó la petición ({nombre}): {exc}",
            modelo=modelo, url=url, causa=exc,
        )

    # 7 · Desconocida. Se trata como infraestructura **a propósito**: ante la duda,
    #     detener y avisar. Lo contrario es exactamente el defecto del ítem 1 — seguir
    #     produciendo veredictos sobre secciones que nadie analizó.
    return LLMUnavailableError(
        f"Error no clasificado del backend ({nombre}): {exc}",
        modelo=modelo, url=url, causa=exc,
    )

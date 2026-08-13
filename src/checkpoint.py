"""Persistencia incremental y reanudación de corridas (ítem 3).

Una corrida completa son horas de LLM. Hasta ahora `results_df` solo se materializaba al
terminar `run()` entero: si el proceso moría a mitad —o alguien cerraba la terminal— se
perdía todo lo pagado hasta ese punto.

**Reanudación sin reprocesamiento.** El checkpoint guarda no solo las filas completadas
sino también las entradas: los DataFrames tabulados y el índice FAISS. Reanudar no vuelve
a convertir PDFs con Docling (minutos por archivo) ni a recalcular embeddings. Medido
sobre el corpus real: ~3 MB por corrida, así que la alternativa ligera —guardar solo las
filas y re-tabular al reanudar— habría ahorrado disco irrelevante a cambio del trabajo
más caro del pipeline.

**Invalidación.** Un checkpoint solo es reanudable si el trabajo pendiente sigue siendo el
mismo. Si cambian los documentos, el modelo o el alcance, reanudar mezclaría resultados de
dos configuraciones distintas en un único papel de trabajo — que es exactamente el tipo de
inconsistencia silenciosa que este plan viene corrigiendo. Se detecta por hash y se avisa.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import pandas as pd

logger = logging.getLogger(__name__)

VERSION_ESQUEMA = 1


def hash_documentos(rutas: list[Path]) -> str:
    """Huella del conjunto de documentos de entrada.

    Por tamaño y nombre, no por contenido completo: un PDF de 40 MB tarda en leerse y esto
    corre al arrancar cada corrida. Detecta el caso que importa —cambiar, añadir o quitar
    documentos— sin pagar la lectura entera.
    """
    h = hashlib.sha256()
    for p in sorted(rutas, key=lambda x: x.name):
        try:
            h.update(f"{p.name}:{p.stat().st_size}".encode())
        except OSError:
            h.update(f"{p.name}:?".encode())
    return h.hexdigest()[:16]


@dataclass
class Manifest:
    """Qué corrida es esta y contra qué se puede reanudar."""

    run_id: str
    creado: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    version_esquema: int = VERSION_ESQUEMA

    hash_documentos: str = ""
    modelo_llm: str = ""
    modelo_embeddings: str = ""
    total_unidades: int = 0
    # Identificadores de las unidades en alcance. Sirve para detectar que alguien cambió
    # la selección: reanudar con otro alcance daría un papel de trabajo que dice cubrir
    # unas secciones y en realidad analizó otras.
    unidades: list[str] = field(default_factory=list)
    workspace: str | None = None

    def compatible_con(self, otro: Manifest) -> tuple[bool, list[str]]:
        """¿Se puede reanudar este checkpoint con la configuración de `otro`?"""
        motivos = []
        if self.version_esquema != otro.version_esquema:
            motivos.append(f"versión de esquema: {self.version_esquema} vs {otro.version_esquema}")
        if self.hash_documentos != otro.hash_documentos:
            motivos.append("los documentos de entrada cambiaron")
        if self.modelo_llm != otro.modelo_llm:
            motivos.append(f"modelo LLM: {self.modelo_llm!r} vs {otro.modelo_llm!r}")
        if self.modelo_embeddings != otro.modelo_embeddings:
            motivos.append(f"modelo de embeddings: {self.modelo_embeddings!r} vs {otro.modelo_embeddings!r}")
        if set(self.unidades) != set(otro.unidades):
            motivos.append("el alcance seleccionado cambió")
        return (not motivos, motivos)


class CheckpointStore:
    """Estado de una corrida en disco.

    Escritura incremental: cada unidad completada se anexa a `rows.jsonl` en cuanto
    termina. Un `jsonl` y no un `json` porque anexar una línea es atómico de facto y no
    exige releer ni reescribir lo anterior — si el proceso muere a mitad de la escritura,
    se pierde esa línea, no el archivo.
    """

    def __init__(self, directorio: Path) -> None:
        self.dir = Path(directorio)
        self.dir.mkdir(parents=True, exist_ok=True)

    # ── rutas ─────────────────────────────────────────────────────────────

    @property
    def manifest_path(self) -> Path:
        return self.dir / "manifest.json"

    @property
    def rows_path(self) -> Path:
        return self.dir / "rows.jsonl"

    @property
    def normativa_path(self) -> Path:
        return self.dir / "normativa.parquet"

    @property
    def manual_path(self) -> Path:
        return self.dir / "manual.parquet"

    @property
    def indice_path(self) -> Path:
        return self.dir / "faiss_index"

    # ── manifest ──────────────────────────────────────────────────────────

    def guardar_manifest(self, manifest: Manifest) -> None:
        self.manifest_path.write_text(
            json.dumps(asdict(manifest), ensure_ascii=False, indent=2), encoding="utf-8",
        )

    def cargar_manifest(self) -> Manifest | None:
        if not self.manifest_path.exists():
            return None
        try:
            return Manifest(**json.loads(self.manifest_path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning("Manifest ilegible en %s: %s", self.dir, e)
            return None

    # ── entradas (lo que evita el reprocesamiento) ────────────────────────

    def guardar_entradas(
        self,
        normativa_df: pd.DataFrame,
        manual_df: pd.DataFrame,
        indice: Any | None = None,
    ) -> None:
        """Persiste lo tabulado y lo indexado.

        Es lo que hace que reanudar no vuelva a convertir PDFs ni a recalcular embeddings,
        que es el trabajo caro. Parquet y no JSON: conserva los dtypes —sin él, una columna
        de booleanos vuelve como strings y `es_referencia` deja de filtrar— y ocupa un
        tercio.
        """
        normativa_df.to_parquet(self.normativa_path)
        manual_df.to_parquet(self.manual_path)
        if indice is not None:
            indice.save(self.indice_path)
        logger.info("Entradas del checkpoint guardadas en %s", self.dir)

    def cargar_entradas(self) -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
        n = pd.read_parquet(self.normativa_path) if self.normativa_path.exists() else None
        m = pd.read_parquet(self.manual_path) if self.manual_path.exists() else None
        return n, m

    @property
    def tiene_entradas(self) -> bool:
        return self.normativa_path.exists() and self.manual_path.exists()

    # ── filas completadas ─────────────────────────────────────────────────

    def anexar(self, unidad_id: str, resultado: dict) -> None:
        """Anexa una unidad completada. Se llama en cada `progress_callback`."""
        registro = {"unidad_id": unidad_id, "resultado": _serializable(resultado)}
        with self.rows_path.open("a", encoding="utf-8") as fh:
            # allow_nan=False: si un NaN sobrevive a _serializable, el fallo es aquí y
            # ahora, no dentro de tres horas al intentar reanudar con un archivo ilegible.
            fh.write(json.dumps(registro, ensure_ascii=False, allow_nan=False) + "\n")

    def _leer_filas(self) -> Iterator[dict]:
        """Lee `rows.jsonl` tolerando una última línea truncada.

        Si el proceso murió a mitad de una escritura, la línea final queda incompleta. Se
        descarta esa y se conserva todo lo anterior: perder una unidad de trabajo es
        aceptable, perder la corrida entera por un byte no.
        """
        if not self.rows_path.exists():
            return
        for n, linea in enumerate(self.rows_path.read_text(encoding="utf-8").splitlines(), 1):
            if not linea.strip():
                continue
            try:
                yield json.loads(linea)
            except json.JSONDecodeError:
                logger.warning(
                    "Línea %d de %s truncada (probablemente una escritura interrumpida); "
                    "se descarta y se conserva el resto", n, self.rows_path.name,
                )

    def completadas(self) -> set[str]:
        """IDs ya procesados. `run()` los salta."""
        return {r["unidad_id"] for r in self._leer_filas()}

    def cargar_parcial(self) -> pd.DataFrame:
        """Resultados acumulados hasta ahora."""
        filas = [r["resultado"] for r in self._leer_filas()]
        return pd.DataFrame(filas) if filas else pd.DataFrame()

    # ── reanudación ───────────────────────────────────────────────────────

    def es_reanudable(self, manifest_actual: Manifest) -> tuple[bool, list[str]]:
        """¿Se puede continuar esta corrida con la configuración actual?"""
        guardado = self.cargar_manifest()
        if guardado is None:
            return False, ["el checkpoint no tiene manifest"]
        if not self.completadas():
            return False, ["no hay ninguna unidad completada que reanudar"]
        return guardado.compatible_con(manifest_actual)

    def progreso(self) -> tuple[int, int]:
        """(completadas, total) para mostrar '142/380'."""
        manifest = self.cargar_manifest()
        return len(self.completadas()), (manifest.total_unidades if manifest else 0)


def _serializable(d: dict) -> dict:
    """Convierte lo que `json` no sabe escribir.

    Los resultados traen tipos de numpy y pandas —`np.int64`, `NaN`, `Timestamp`— que
    revientan `json.dumps`. Fallar aquí perdería la fila justo después de haberla pagado
    en tiempo de LLM.
    """
    import numpy as np

    def _conv(v: Any) -> Any:
        if isinstance(v, dict):
            return {k: _conv(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [_conv(x) for x in v]
        if isinstance(v, pd.Timestamp):
            return v.isoformat()
        if isinstance(v, np.generic):
            v = v.item()          # np.int64 → int, np.float64 → float
        # NaN/inf a None. Va DESPUÉS de desenvolver numpy y comprueba el valor, no el
        # tipo: `np.nan` es un `float`, así que un filtro por isinstance lo deja pasar y
        # `json.dumps` escribe el literal `NaN` — que Python relee sin quejarse pero
        # **no es JSON válido**. Un parser estricto, u otro lenguaje, rechazaría el
        # archivo entero, y con él la corrida que se quería reanudar.
        if isinstance(v, float) and (v != v or v in (float("inf"), float("-inf"))):
            return None
        if v is not None and not isinstance(v, (str, int, float, bool, list, dict)):
            return None if pd.isna(v) else v
        return v

    return {k: _conv(v) for k, v in d.items()}


def purgar(raiz: Path, conservar: int = 20) -> list[Path]:
    """Borra las corridas más antiguas, conservando las N últimas.

    Los `run_id` empiezan por fecha, así que ordenar por nombre ordena por antigüedad sin
    tocar el sistema de archivos. Devuelve lo borrado.
    """
    raiz = Path(raiz)
    if not raiz.exists():
        return []
    corridas = sorted((d for d in raiz.iterdir() if d.is_dir()), key=lambda d: d.name)
    sobrantes = corridas[:-conservar] if conservar > 0 else corridas
    for d in sobrantes:
        import shutil

        shutil.rmtree(d, ignore_errors=True)
        logger.info("Corrida purgada: %s", d.name)
    return sobrantes

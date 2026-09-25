"""Documentos desde un volumen de Unity Catalog (src/volumen.py) y su uso en la API.

Sin Databricks ni red: un cliente falso imita `WorkspaceClient().files` (list_directory_contents
y download). Fijan qué se descarga y qué no, que un volumen caído no tumbe la app y que la API
liste y encuentre los PDF que vienen del volumen.
"""
from __future__ import annotations

import io
from dataclasses import dataclass

import pytest

from src import volumen

PDF = b"%PDF-1.4 falso\n"


@dataclass
class _Entrada:
    path: str
    name: str
    file_size: int
    is_directory: bool = False


class _Files:
    def __init__(self, contenido: dict[str, bytes], fallar: Exception | None = None):
        self.contenido = contenido          # ruta completa → bytes
        self.fallar = fallar
        self.descargas: list[str] = []

    def list_directory_contents(self, directorio: str):
        if self.fallar:
            raise self.fallar
        for ruta, datos in self.contenido.items():
            padre, _, nombre = ruta.rpartition("/")
            if padre == directorio:
                yield _Entrada(path=ruta, name=nombre, file_size=len(datos),
                               is_directory=nombre.endswith("/"))

    def download(self, ruta: str):
        self.descargas.append(ruta)
        return type("R", (), {"contents": io.BytesIO(self.contenido[ruta])})()


class _Cliente:
    def __init__(self, files: _Files):
        self.files = files


BASE = "/Volumes/cat/esq/docs"


@pytest.fixture(autouse=True)
def _aislado(monkeypatch, tmp_path):
    monkeypatch.delenv("DOCUMENTOS_VOLUMEN", raising=False)
    monkeypatch.setattr("src.settings.cargar_env", lambda *a, **k: False)
    monkeypatch.setattr(volumen, "CACHE_DIR", tmp_path / "volumen")
    monkeypatch.setattr(volumen, "_ultimo_sync", 0.0)
    monkeypatch.setattr(volumen, "_ultimo_error", None)


@pytest.fixture
def files():
    return _Files({
        f"{BASE}/normativas/Ley-Grande.pdf": PDF * 1000,
        f"{BASE}/normativas/leeme.txt": b"no es pdf",
        f"{BASE}/manuales/Manual-Real.pdf": PDF,
    })


class TestConfiguracion:
    def test_sin_variable_no_hace_nada(self, files):
        assert volumen.ruta_volumen() is None
        assert volumen.sincronizar(_Cliente(files)) == 0 and files.descargas == []

    @pytest.mark.parametrize("valor", [BASE, BASE + "/", "cat.esq.docs"])
    def test_acepta_ruta_o_nombre(self, monkeypatch, valor):
        monkeypatch.setenv("DOCUMENTOS_VOLUMEN", valor)
        assert volumen.ruta_volumen() == BASE

    def test_placeholder_cuenta_como_sin_volumen(self, monkeypatch):
        monkeypatch.setenv("DOCUMENTOS_VOLUMEN", "REEMPLAZAR-/Volumes/c/s/v")
        assert volumen.ruta_volumen() is None

    def test_valor_invalido_se_informa_sin_lanzar(self, monkeypatch, files):
        monkeypatch.setenv("DOCUMENTOS_VOLUMEN", "solo-un-nombre")
        assert volumen.sincronizar(_Cliente(files)) == 0
        assert "DOCUMENTOS_VOLUMEN" in volumen.ultimo_error()


class TestSincronizacion:
    def test_descarga_solo_pdf_y_por_tipo(self, monkeypatch, files):
        monkeypatch.setenv("DOCUMENTOS_VOLUMEN", BASE)
        assert volumen.sincronizar(_Cliente(files)) == 2
        assert (volumen.directorio_local("normativa") / "Ley-Grande.pdf").read_bytes() == PDF * 1000
        assert (volumen.directorio_local("manual") / "Manual-Real.pdf").exists()
        assert not (volumen.directorio_local("normativa") / "leeme.txt").exists()
        assert not list(volumen.CACHE_DIR.rglob("*.part")), "no deben quedar descargas a medias"

    def test_no_vuelve_a_bajar_lo_que_ya_tiene(self, monkeypatch, files):
        monkeypatch.setenv("DOCUMENTOS_VOLUMEN", BASE)
        volumen.sincronizar(_Cliente(files))
        files.descargas.clear()
        assert volumen.sincronizar(_Cliente(files), forzar=True) == 0
        assert files.descargas == []

    def test_si_cambia_el_tamano_se_actualiza(self, monkeypatch, files):
        monkeypatch.setenv("DOCUMENTOS_VOLUMEN", BASE)
        volumen.sincronizar(_Cliente(files))
        files.contenido[f"{BASE}/manuales/Manual-Real.pdf"] = PDF * 3
        assert volumen.sincronizar(_Cliente(files), forzar=True) == 1

    def test_no_relista_antes_del_refresco(self, monkeypatch, files):
        monkeypatch.setenv("DOCUMENTOS_VOLUMEN", BASE)
        volumen.sincronizar(_Cliente(files))
        files.contenido[f"{BASE}/manuales/Otro.pdf"] = PDF
        assert volumen.sincronizar(_Cliente(files)) == 0, "dentro de REFRESCO_S no se vuelve a listar"

    def test_un_nombre_con_ruta_no_escapa_de_la_carpeta(self, monkeypatch, tmp_path):
        monkeypatch.setenv("DOCUMENTOS_VOLUMEN", BASE)
        malo = _Files({})
        malo.list_directory_contents = lambda d: iter(
            [_Entrada(path=f"{d}/x.pdf", name="../../fuera.pdf", file_size=3)] if d.endswith("normativas") else [])
        malo.contenido[f"{BASE}/normativas/x.pdf"] = b"abc"
        volumen.sincronizar(_Cliente(malo))
        assert (volumen.directorio_local("normativa") / "fuera.pdf").exists()
        assert not (tmp_path / "fuera.pdf").exists()

    def test_volumen_caido_no_lanza_y_deja_el_motivo(self, monkeypatch):
        monkeypatch.setenv("DOCUMENTOS_VOLUMEN", BASE)
        caido = _Files({}, fallar=PermissionError("sin READ VOLUME"))
        assert volumen.sincronizar(_Cliente(caido)) == 0
        assert "PermissionError" in volumen.ultimo_error() and BASE in volumen.ultimo_error()


class TestApi:
    def _client(self, monkeypatch, files):
        from fastapi.testclient import TestClient

        from api.main import app
        monkeypatch.setattr(volumen, "_cliente", lambda: _Cliente(files))
        return TestClient(app)

    def test_lista_los_pdf_del_volumen_junto_a_los_del_paquete(self, monkeypatch, files):
        monkeypatch.setenv("DOCUMENTOS_VOLUMEN", BASE)
        d = self._client(monkeypatch, files).get("/api/documents").json()
        normas = {x["id"] for x in d["normativas"]}
        assert "Ley-Grande.pdf" in normas
        assert "Manual-Real.pdf" in {x["id"] for x in d["manuales"]}
        assert d["aviso_volumen"] is None

    def test_el_pdf_del_volumen_se_puede_servir(self, monkeypatch, files):
        monkeypatch.setenv("DOCUMENTOS_VOLUMEN", BASE)
        c = self._client(monkeypatch, files)
        c.get("/api/documents")
        r = c.get("/api/documents/normativa/Ley-Grande.pdf/pdf")
        assert r.status_code == 200 and r.content == PDF * 1000

    def test_un_volumen_caido_se_avisa_sin_romper_la_lista(self, monkeypatch):
        monkeypatch.setenv("DOCUMENTOS_VOLUMEN", BASE)
        d = self._client(monkeypatch, _Files({}, fallar=PermissionError("x"))).get("/api/documents").json()
        assert d["aviso_volumen"] and "PermissionError" in d["aviso_volumen"]
        assert len(d["normativas"]) > 0, "los PDF del paquete siguen listándose"

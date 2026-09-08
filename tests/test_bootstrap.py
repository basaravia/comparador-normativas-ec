"""Pruebas de src/bootstrap.py — materialización de credenciales de GCP.

Databricks Apps inyecta secretos como contenido de variable de entorno, no como
archivo montado (ver el comentario en app.yaml). google-auth/ADC, en cambio, espera
que GOOGLE_APPLICATION_CREDENTIALS apunte a un archivo. `_materializar_credenciales_gcp`
es el puente entre ambos — estas pruebas fijan ese contrato.
"""
from __future__ import annotations

import os
import stat

from src.bootstrap import _materializar_credenciales_gcp

FALSO_JSON = '{"type": "service_account", "project_id": "x"}'


class TestMaterializarCredencialesGcp:
    def test_no_hace_nada_sin_ninguna_variable(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
        monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS_JSON", raising=False)

        _materializar_credenciales_gcp()

        assert os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "") == ""

    def test_respeta_un_archivo_real_ya_configurado(self, monkeypatch, tmp_path):
        """El caso local: no pisar lo explícito aunque también venga el JSON."""
        credencial = tmp_path / "clave-real.json"
        credencial.write_text(FALSO_JSON)
        monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(credencial))
        monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS_JSON", FALSO_JSON)

        _materializar_credenciales_gcp()

        assert os.environ["GOOGLE_APPLICATION_CREDENTIALS"] == str(credencial)

    def test_materializa_archivo_desde_json_databricks_apps(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
        monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS_JSON", FALSO_JSON)

        _materializar_credenciales_gcp()

        ruta = os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
        assert os.path.isfile(ruta)
        assert open(ruta).read() == FALSO_JSON

        permisos = stat.S_IMODE(os.stat(ruta).st_mode)
        assert permisos == stat.S_IRUSR | stat.S_IWUSR, (
            "el archivo lleva una clave de cuenta de servicio: solo el dueño del "
            "proceso debe poder leerlo"
        )

        os.unlink(ruta)

    def test_ruta_configurada_pero_inexistente_tambien_materializa(self, monkeypatch, tmp_path):
        """Una ruta puesta pero sin archivo detrás (typo, volumen no montado) no debe
        bloquear el puente: si hay JSON, se usa igual."""
        ruta_rota = tmp_path / "no-existe.json"
        monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(ruta_rota))
        monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS_JSON", FALSO_JSON)

        _materializar_credenciales_gcp()

        ruta_final = os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
        assert ruta_final != str(ruta_rota)
        assert os.path.isfile(ruta_final)

        os.unlink(ruta_final)

"""Ítem 2 — la corrida sobrevive al refresco del navegador.

El defecto: la corrida bloqueaba el script-run de Streamlit y su estado vivía en
`st.session_state`. Al refrescar, la sesión nueva nacía vacía mientras los hilos seguían
vivos: la terminal avanzaba y la web decía "En espera…". Y pulsar "Ejecutar" otra vez
lanzaba una segunda corrida sobre la misma configuración, duplicando el gasto de LLM.

La causa era dónde vivía el estado: `session_state` es por pestaña, la corrida es del
proceso.
"""
from __future__ import annotations

import json
import threading
import time

import pytest

from app.run_manager import EstadoCorrida, RunHandle, RunManager, gestor, reiniciar_gestor


@pytest.fixture(autouse=True)
def _gestor_limpio():
    reiniciar_gestor()
    yield
    reiniciar_gestor()


@pytest.fixture
def mgr(tmp_path):
    return RunManager(raiz=tmp_path)


class TestElEstadoSobreviveALaSesion:
    """El corazón del ítem 2."""

    def test_el_registro_es_del_proceso_no_de_la_sesion(self, tmp_path):
        """Simula un refresco: la 'sesión' se descarta, la corrida sigue ahí."""
        g1 = gestor(tmp_path)
        g1.registrar(RunHandle(run_id="r1", total=10, estado=EstadoCorrida.CORRIENDO))

        # Un refresco de Streamlit reejecuta el script: se vuelve a pedir el gestor.
        g2 = gestor(tmp_path)
        assert g2 is g1, "cada refresco creó un gestor nuevo y perdió las corridas"
        assert g2.obtener("r1") is not None

    def test_re_adjuntar_por_run_id_devuelve_el_progreso_real(self, mgr):
        """`session_state` guarda solo el run_id; el resto se recupera."""
        h = mgr.registrar(RunHandle(run_id="r1", total=100, estado=EstadoCorrida.CORRIENDO))
        h.progreso = 42

        recuperado = mgr.obtener("r1")
        assert recuperado.progreso == 42
        assert recuperado.porcentaje == 0.42

    def test_una_segunda_pestana_ve_la_misma_corrida(self, mgr):
        h = mgr.registrar(RunHandle(run_id="r1", total=10, estado=EstadoCorrida.CORRIENDO))
        h.progreso = 3
        assert mgr.obtener("r1").progreso == 3


class TestNoDuplicarCorridas:

    def test_no_se_lanza_dos_veces_la_misma_configuracion(self, mgr):
        """Antes, pulsar Ejecutar tras un refresco duplicaba el gasto de LLM."""
        mgr.registrar(RunHandle(run_id="r1", config_hash="abc",
                                estado=EstadoCorrida.CORRIENDO))
        assert mgr.activa_con_config("abc") is not None

    def test_una_configuracion_distinta_si_puede_correr(self, mgr):
        mgr.registrar(RunHandle(run_id="r1", config_hash="abc",
                                estado=EstadoCorrida.CORRIENDO))
        assert mgr.activa_con_config("otra") is None

    def test_una_corrida_terminada_deja_de_bloquear(self, mgr):
        mgr.registrar(RunHandle(run_id="r1", config_hash="abc",
                                estado=EstadoCorrida.COMPLETADO))
        assert mgr.activa_con_config("abc") is None


class TestEjecucionEnSegundoPlano:

    def test_lanzar_devuelve_de_inmediato(self, mgr):
        arrancado = threading.Event()

        def trabajo(h):
            arrancado.set()
            time.sleep(0.3)
            return "listo"

        t0 = time.monotonic()
        mgr.lanzar(RunHandle(run_id="r1"), trabajo)
        assert time.monotonic() - t0 < 0.2, "lanzar() bloqueó; la UI se congelaría"
        assert arrancado.wait(2)

    def test_el_estado_llega_a_completado(self, mgr):
        h = mgr.lanzar(RunHandle(run_id="r1"), lambda handle: "ok")
        for _ in range(50):
            if h.estado.terminal:
                break
            time.sleep(0.05)
        assert h.estado == EstadoCorrida.COMPLETADO
        assert h.resultado == "ok"

    def test_un_fallo_queda_registrado_y_no_mata_el_hilo_en_silencio(self, mgr):
        def revienta(handle):
            raise ValueError("algo salió mal")

        h = mgr.lanzar(RunHandle(run_id="r1"), revienta)
        for _ in range(50):
            if h.estado.terminal:
                break
            time.sleep(0.05)
        assert h.estado == EstadoCorrida.FALLIDO
        assert "algo salió mal" in h.error


class TestCancelacion:

    def test_es_cooperativa_no_mata_el_hilo(self, mgr):
        """Matar el hilo dejaría el checkpoint a medias."""
        unidades = []

        def trabajo(h):
            for i in range(20):
                if h.cancelar.is_set():
                    break
                unidades.append(i)
                time.sleep(0.02)
            return len(unidades)

        h = mgr.lanzar(RunHandle(run_id="r1"), trabajo)
        time.sleep(0.1)
        assert mgr.cancelar("r1") is True

        for _ in range(50):
            if h.estado.terminal:
                break
            time.sleep(0.05)
        assert h.estado == EstadoCorrida.CANCELADO
        assert 0 < len(unidades) < 20, "no se detuvo, o no llegó a empezar"

    def test_cancelar_una_terminada_no_hace_nada(self, mgr):
        mgr.registrar(RunHandle(run_id="r1", estado=EstadoCorrida.COMPLETADO))
        assert mgr.cancelar("r1") is False


class TestEspejoEnDisco:

    def test_el_estado_se_escribe(self, mgr, tmp_path):
        mgr.registrar(RunHandle(run_id="r1", total=10, config_hash="abc"))
        estado = json.loads((tmp_path / "r1" / "state.json").read_text(encoding="utf-8"))
        assert estado["run_id"] == "r1" and estado["total"] == 10

    def test_detecta_corridas_huerfanas_tras_reiniciar(self, tmp_path):
        """Tras reiniciar Streamlit el registro nace vacío, pero el disco recuerda."""
        antes = RunManager(raiz=tmp_path)
        antes.registrar(RunHandle(run_id="r1", estado=EstadoCorrida.CORRIENDO))

        despues = RunManager(raiz=tmp_path)       # proceso nuevo
        huerfanas = despues.huerfanas()
        assert [h["run_id"] for h in huerfanas] == ["r1"]

    def test_una_corrida_terminada_no_es_huerfana(self, tmp_path):
        m = RunManager(raiz=tmp_path)
        m.registrar(RunHandle(run_id="r1", estado=EstadoCorrida.COMPLETADO))
        assert RunManager(raiz=tmp_path).huerfanas() == []

    def test_un_state_json_corrupto_no_rompe_la_deteccion(self, tmp_path):
        (tmp_path / "roto").mkdir()
        (tmp_path / "roto" / "state.json").write_text("{ no es json")
        m = RunManager(raiz=tmp_path)
        m.registrar(RunHandle(run_id="ok", estado=EstadoCorrida.CORRIENDO))
        assert [h["run_id"] for h in RunManager(raiz=tmp_path).huerfanas()] == ["ok"]


class TestLogPorCorrida:
    """El panel quedaba vacío porque los hilos worker no tienen ScriptRunContext."""

    def test_el_buffer_no_depende_de_streamlit(self, mgr):
        h = mgr.registrar(RunHandle(run_id="r1"))
        h.registrar("línea uno")
        h.registrar("línea dos")
        assert h.lineas() == ["línea uno", "línea dos"]

    def test_conserva_solo_las_ultimas(self, mgr):
        h = mgr.registrar(RunHandle(run_id="r1"))
        for i in range(600):
            h.registrar(f"l{i}")
        assert len(h.lineas()) == 500
        assert h.lineas(2) == ["l598", "l599"]

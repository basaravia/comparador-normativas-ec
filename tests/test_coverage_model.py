"""Ítem 5 — modelo de cobertura N:N.

Antes, el resultado era una fila por sección con los artículos aplanados a texto: no se
podía responder "¿qué secciones cubren el Art. 35?" sin re-correr el pipeline. Y esa
pregunta es la mitad del trabajo — el Bloque A exige verificar que el 100 % de la
normativa quede cubierta, lo que se recorre desde el artículo.

Es además el contrato del que saldrán los tipos del frontend (S11), así que estas pruebas
fijan la forma, no solo el comportamiento.
"""
from __future__ import annotations


from src.coverage import (
    ORIGEN_LEXICO,
    ORIGEN_MANUAL,
    ORIGEN_SEMANTICO_V1,
    ORIGEN_SEMANTICO_V2,
    CoverageLink,
    LinkTable,
    cobertura_global,
    vista_manual,
    vista_normativa,
)
from tests.fixtures import COBERTURA_ESPERADA, DOC_LEY, DOC_RES


def _link(art="LEY-A-2026.pdf_0003", sec="MANUAL_0004", **kw) -> CoverageLink:
    base = dict(
        articulo_element_id=art, articulo_doc_id=DOC_LEY, articulo_numero="8",
        seccion_chunk_id=sec, seccion_doc_id="MANUAL-INTERNO.pdf",
        seccion_jerarquia="4.1 Conocimiento del cliente",
        origen=ORIGEN_SEMANTICO_V1, relevante=True,
    )
    base.update(kw)
    return CoverageLink(**base)


class TestWorkspaceIdDesdeElDiseno:
    """§3.3.1 — el campo nace con el modelo, no se retro-fitea."""

    def test_toda_arista_tiene_workspace(self):
        assert _link().workspace_id == "local"

    def test_dos_workspaces_no_mezclan_sus_aristas(self):
        """Sin esto, en Fase 3 dos equipos analizando los mismos documentos verían las
        aristas del otro."""
        t = LinkTable([_link(workspace_id="a"), _link(workspace_id="b")])
        assert len(t) == 2, "las aristas de dos workspaces colapsaron en una"


class TestDedupe:
    """Las dos vías llegan a las mismas parejas por caminos distintos."""

    def test_la_misma_pareja_no_se_cuenta_dos_veces(self):
        t = LinkTable([
            _link(origen=ORIGEN_SEMANTICO_V1),
            _link(origen=ORIGEN_SEMANTICO_V2),
        ])
        assert len(t) == 1, "sin dedupe la cobertura saldría inflada"

    def test_acumula_los_origenes(self):
        """Que las dos vías coincidan es evidencia más fuerte que cualquiera sola."""
        t = LinkTable([
            _link(origen=ORIGEN_SEMANTICO_V1),
            _link(origen=ORIGEN_LEXICO),
        ])
        enlace = next(iter(t))
        assert set(enlace.origenes) == {ORIGEN_SEMANTICO_V1, ORIGEN_LEXICO}

    def test_conserva_el_mejor_score_de_cada_tipo(self):
        t = LinkTable([
            _link(score_semantico=0.6, score_reranker=None),
            _link(score_semantico=0.4, score_reranker=0.9),
        ])
        enlace = next(iter(t))
        assert enlace.score_semantico == 0.6 and enlace.score_reranker == 0.9

    def test_el_resultado_no_depende_del_orden(self):
        """Un papel de trabajo no puede cambiar según en qué orden corrieron las vías."""
        a = LinkTable([_link(origen=ORIGEN_SEMANTICO_V1, score_semantico=0.6),
                       _link(origen=ORIGEN_LEXICO, score_semantico=0.9)])
        b = LinkTable([_link(origen=ORIGEN_LEXICO, score_semantico=0.9),
                       _link(origen=ORIGEN_SEMANTICO_V1, score_semantico=0.6)])
        ea, eb = next(iter(a)), next(iter(b))
        assert (ea.origen, ea.score_semantico) == (eb.origen, eb.score_semantico)

    def test_una_decision_humana_manda_sobre_la_heuristica(self):
        t = LinkTable([_link(origen=ORIGEN_SEMANTICO_V1, razon="por embeddings"),
                       _link(origen=ORIGEN_MANUAL, razon="lo confirmó el auditor")])
        assert next(iter(t)).razon == "lo confirmó el auditor"

    def test_un_veredicto_determinado_gana_al_indeterminado(self):
        """Que una vía no pudiera decidir no borra que la otra sí pudo (ítem 4)."""
        t = LinkTable([_link(relevante=True), _link(relevante=None)])
        assert next(iter(t)).relevante is True


class TestConsultaEnAmbosSentidos:
    """El DoD del ítem: la pregunta que antes exigía re-correr todo."""

    def test_que_secciones_cubren_este_articulo(self):
        t = LinkTable([
            _link(art="LEY_5", sec="S1"),
            _link(art="LEY_5", sec="S2"),
            _link(art="LEY_9", sec="S3"),
        ])
        assert {e.seccion_chunk_id for e in t.por_articulo("LEY_5")} == {"S1", "S2"}

    def test_que_articulos_toca_esta_seccion(self):
        t = LinkTable([_link(art="LEY_5", sec="S1"), _link(art="LEY_9", sec="S1")])
        assert {e.articulo_element_id for e in t.por_seccion("S1")} == {"LEY_5", "LEY_9"}

    def test_relevantes_excluye_los_indeterminados(self):
        t = LinkTable([_link(sec="S1", relevante=True), _link(sec="S2", relevante=None),
                       _link(sec="S3", relevante=False)])
        assert len(t.relevantes()) == 1


class TestVistas:

    def test_la_vista_manual_incluye_secciones_sin_aristas(self, manual_df):
        """Omitirlas las volvería invisibles justo cuando hay que decidir si son una
        omisión o una sección sin norma aplicable."""
        vista = vista_manual(LinkTable(), manual_df)
        assert len(vista) == len(manual_df)
        assert (vista["n_articulos_relacionados"] == 0).all()

    def test_la_vista_normativa_excluye_referencias_por_defecto(self, normativa_df):
        """Contarlas como sin cobertura inflaría la brecha con artículos que nadie cumple."""
        con = vista_normativa(LinkTable(), normativa_df, incluir_referencias=True)
        sin = vista_normativa(LinkTable(), normativa_df, incluir_referencias=False)
        assert len(sin) < len(con)

    def test_una_seccion_que_cubre_dos_normas_las_lista_ambas(self, manual_df):
        t = LinkTable([
            _link(art="LEY_8", sec="MANUAL_0004", articulo_doc_id=DOC_LEY),
            _link(art="RES_3", sec="MANUAL_0004", articulo_doc_id=DOC_RES),
        ])
        fila = vista_manual(t, manual_df[manual_df["chunk_id"] == "MANUAL_0004"])
        if not fila.empty:
            assert set(fila.iloc[0]["normativas"]) == {DOC_LEY, DOC_RES}


class TestCoberturaGlobal:
    """La premisa no negociable del Bloque A."""

    def test_sin_aristas_la_cobertura_es_cero(self, normativa_df):
        c = cobertura_global(LinkTable(), normativa_df)
        assert c.cubiertos == 0 and c.porcentaje == 0.0 and not c.completa

    def test_lista_los_articulos_sin_cobertura(self, normativa_df):
        c = cobertura_global(LinkTable(), normativa_df)
        assert len(c.sin_cobertura) == c.total_articulos
        assert all("numero" in a and "doc_id" in a for a in c.sin_cobertura)

    def test_el_articulo_huerfano_del_corpus_aparece_sin_cobertura(self, normativa_df):
        """El corpus construye a propósito un artículo que nada cubre."""
        doc_huerfano, num_huerfano = COBERTURA_ESPERADA["articulos_sin_cobertura"][0]
        arts = normativa_df[(normativa_df["tipo_elemento"] == "articulo")
                            & (~normativa_df["es_referencia"])]
        t = LinkTable([
            _link(art=r["element_id"], sec=f"S{i}", articulo_doc_id=r["doc_id"])
            for i, (_, r) in enumerate(arts.iterrows())
            if not (r["doc_id"] == doc_huerfano and r["numero"] == num_huerfano)
        ])
        c = cobertura_global(t, normativa_df)
        assert not c.completa
        assert any(a["numero"] == num_huerfano for a in c.sin_cobertura)

    def test_cobertura_total_cuando_todo_esta_cubierto(self, normativa_df):
        arts = normativa_df[(normativa_df["tipo_elemento"] == "articulo")
                            & (~normativa_df["es_referencia"])]
        t = LinkTable([
            _link(art=r["element_id"], sec=f"S{i}", articulo_doc_id=r["doc_id"])
            for i, (_, r) in enumerate(arts.iterrows())
        ])
        c = cobertura_global(t, normativa_df)
        assert c.completa and c.porcentaje == 1.0

    def test_el_porcentaje_cuadra_con_la_vista_que_ve_el_auditor(self, normativa_df):
        """Dos cálculos independientes podrían discrepar, y un porcentaje que no cuadre
        con la tabla de abajo destruye la confianza en el papel de trabajo."""
        t = LinkTable([_link(art=normativa_df.iloc[0]["element_id"], sec="S1")])
        c = cobertura_global(t, normativa_df)
        vista = vista_normativa(t, normativa_df)
        assert c.cubiertos == int(vista["cubierto"].sum())
        assert c.total_articulos == len(vista)


class TestPersistencia:

    def test_round_trip_conserva_todo(self, tmp_path):
        original = LinkTable([
            _link(sec="S1", score_semantico=0.8, score_grade=None, relevante=True,
                  origenes=(ORIGEN_LEXICO, ORIGEN_SEMANTICO_V1),
                  requiere_revision=True, motivos_revision=("cita_ambigua",)),
            _link(sec="S2", relevante=None),
        ])
        original.save(tmp_path / "links.parquet")
        vuelta = LinkTable.load(tmp_path / "links.parquet")

        assert len(vuelta) == len(original)
        por_sec = {e.seccion_chunk_id: e for e in vuelta}
        assert por_sec["S1"].score_semantico == 0.8
        assert por_sec["S1"].score_grade is None, "un None se volvió NaN al ida y vuelta"
        assert set(por_sec["S1"].origenes) == {ORIGEN_LEXICO, ORIGEN_SEMANTICO_V1}
        assert por_sec["S1"].motivos_revision == ("cita_ambigua",)
        assert por_sec["S2"].relevante is None, "indeterminado se confundió con False"

    def test_una_tabla_vacia_no_rompe(self, tmp_path):
        LinkTable().save(tmp_path / "v.parquet")
        assert len(LinkTable.load(tmp_path / "v.parquet")) == 0

    def test_la_cobertura_se_serializa(self, tmp_path, normativa_df):
        import json

        destino = cobertura_global(LinkTable(), normativa_df).guardar(tmp_path / "c.json")
        d = json.loads(destino.read_text(encoding="utf-8"))
        assert "porcentaje" in d and "sin_cobertura" in d and "version_esquema" in d

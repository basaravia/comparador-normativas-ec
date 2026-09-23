"""Ítem 10 — flag de revisión manual.

El flag existe porque el Bloque A prohíbe que la herramienta resuelva sola lo que no puede
resolver: cuando el análisis no alcanza para cerrar un veredicto, la fila se marca y se
explica por qué, y la mira una persona. La forma de fallar que estas pruebas vigilan no es
un crash — es una fila que debería estar marcada y sale limpia, o que sale marcada sin
motivo legible. Las dos destruyen la utilidad del papel de trabajo por caminos distintos:
la primera cuela un veredicto que nadie verificó, la segunda hace que el auditor deje de
mirar el filtro.

Un caso por disparador (los cinco del plan), su combinación, la agregación en las dos
vistas y el umbral configurable de la banda de indecisión.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src import config as cfg
from src.coverage import (
    MOTIVO_ARTICULO_SIN_COBERTURA,
    MOTIVO_BANDA_INDECISION,
    MOTIVO_CITA_AMBIGUA,
    MOTIVO_CONFLICTO_LEXICO_SEMANTICO,
    MOTIVO_PARCIAL_CON_BRECHAS,
    MOTIVO_VEREDICTO_INDETERMINADO,
    ORIGEN_LEXICO,
    ORIGEN_LEXICO_AMBIGUO,
    ORIGEN_MANUAL,
    ORIGEN_SEMANTICO_V1,
    ORIGEN_SEMANTICO_V2,
    CoverageLink,
    LinkTable,
    evaluar_revision_manual,
    vista_manual,
    vista_normativa,
)
from tests.fixtures import DOC_LEY, DOC_MANUAL

UMBRAL = cfg.MIN_SEMANTIC_SCORE


def _link(**kw) -> CoverageLink:
    """Arista mínima con veredicto cerrado y score holgado: sin disparadores.

    La base tiene que salir *limpia* — si no, cualquier prueba de un disparador concreto
    pasaría por el motivo equivocado.
    """
    base = dict(
        articulo_element_id=f"{DOC_LEY}_0003", articulo_doc_id=DOC_LEY,
        articulo_numero="8",
        seccion_chunk_id="MANUAL-INTERNO_0004", seccion_doc_id=DOC_MANUAL,
        seccion_jerarquia="4.1 Conocimiento del cliente",
        origen=ORIGEN_SEMANTICO_V1,
        score_semantico=UMBRAL + 0.40,
        relevante=True,
    )
    base.update(kw)
    return CoverageLink(**base)


class TestLineaBase:
    """Sin esto, un disparador roto podría pasar porque *todo* sale marcado."""

    def test_una_arista_sana_no_se_marca(self):
        marcada = evaluar_revision_manual(_link())
        assert marcada.requiere_revision_manual is False
        assert marcada.motivos_revision == ()

    def test_los_cinco_motivos_son_cadenas_distintas(self):
        """Dos motivos con el mismo valor colapsarían en el `set` de las vistas y uno de
        los dos desaparecería del papel de trabajo sin avisar."""
        motivos = {
            MOTIVO_BANDA_INDECISION,
            MOTIVO_VEREDICTO_INDETERMINADO,
            MOTIVO_CONFLICTO_LEXICO_SEMANTICO,
            MOTIVO_ARTICULO_SIN_COBERTURA,
            MOTIVO_PARCIAL_CON_BRECHAS,
        }
        assert len(motivos) == 5


class TestDisparadorBandaDeIndecision:
    """1 · El umbral no es una frontera real: 0.299 y 0.301 no se distinguen en nada."""

    @pytest.mark.parametrize("score", [UMBRAL - 0.05, UMBRAL, UMBRAL + 0.05, UMBRAL + 0.01])
    def test_dentro_de_la_banda_marca(self, score):
        marcada = evaluar_revision_manual(_link(score_semantico=score))
        assert marcada.requiere_revision_manual is True
        assert MOTIVO_BANDA_INDECISION in marcada.motivos_revision

    @pytest.mark.parametrize("score", [UMBRAL - 0.051, UMBRAL + 0.051, 0.99, 0.0])
    def test_fuera_de_la_banda_no_marca(self, score):
        marcada = evaluar_revision_manual(_link(score_semantico=score))
        assert MOTIVO_BANDA_INDECISION not in marcada.motivos_revision

    def test_sin_score_semantico_no_dispara(self):
        """Una arista puramente léxica no trae score. Ausencia de score no es score en la
        banda, y marcarla ahí inundaría el filtro de citas explícitas perfectamente
        claras."""
        marcada = evaluar_revision_manual(
            _link(origen=ORIGEN_LEXICO, score_semantico=None)
        )
        assert MOTIVO_BANDA_INDECISION not in marcada.motivos_revision

    def test_la_banda_es_simetrica_alrededor_del_umbral(self):
        """Las dos aristas solo se diferencian en el score, y en nada más.

        Con `relevante=True` —el valor por omisión del helper— el lado de abajo
        dispararía además `conflicto_lexico_semantico` (relevancia afirmada con el score
        bajo el umbral) y la comparación mediría ese disparador en vez de la banda.
        `relevante=False` es un veredicto igual de cerrado y no dispara nada en un origen
        semántico, así que aísla la simetría que esta prueba vigila."""
        arriba = evaluar_revision_manual(
            _link(score_semantico=UMBRAL + 0.04, relevante=False)
        )
        abajo = evaluar_revision_manual(
            _link(score_semantico=UMBRAL - 0.04, relevante=False)
        )
        assert arriba.motivos_revision == abajo.motivos_revision == (
            MOTIVO_BANDA_INDECISION,
        )


class TestUmbralDeLaBandaConfigurable:
    """El semi-ancho es configuración, no una constante enterrada: cuánto revisar a mano
    es una decisión del encargo, no del código."""

    def test_el_default_sale_de_config(self):
        assert cfg.DELTA_INDECISION == 0.05

    def test_delta_mayor_ensancha_la_banda(self):
        score = UMBRAL + 0.09
        assert MOTIVO_BANDA_INDECISION not in evaluar_revision_manual(
            _link(score_semantico=score)
        ).motivos_revision
        assert MOTIVO_BANDA_INDECISION in evaluar_revision_manual(
            _link(score_semantico=score), delta_indecision=0.10
        ).motivos_revision

    def test_delta_cero_deja_solo_el_empate_exacto(self):
        assert MOTIVO_BANDA_INDECISION in evaluar_revision_manual(
            _link(score_semantico=UMBRAL), delta_indecision=0.0
        ).motivos_revision
        assert MOTIVO_BANDA_INDECISION not in evaluar_revision_manual(
            _link(score_semantico=UMBRAL + 0.001), delta_indecision=0.0
        ).motivos_revision

    def test_delta_negativo_se_lee_como_semi_ancho(self):
        """Un -0.05 en la configuración es un error de tipeo, no una banda invertida que
        no marcaría nada."""
        marcada = evaluar_revision_manual(
            _link(score_semantico=UMBRAL + 0.04), delta_indecision=-0.05
        )
        assert MOTIVO_BANDA_INDECISION in marcada.motivos_revision

    def test_min_score_de_la_corrida_manda_sobre_el_de_config(self):
        """La banda se define alrededor del umbral que realmente se usó: si la corrida
        subió el corte a 0.60, la franja dudosa se mueve con él."""
        marcada = evaluar_revision_manual(_link(score_semantico=0.62), min_score=0.60)
        assert MOTIVO_BANDA_INDECISION in marcada.motivos_revision

        # Y el score que era dudoso con el umbral por defecto deja de serlo.
        movida = evaluar_revision_manual(_link(score_semantico=UMBRAL), min_score=0.60)
        assert MOTIVO_BANDA_INDECISION not in movida.motivos_revision


class TestDisparadorVeredictoIndeterminado:
    """2 · `relevante is None` (ítem 4): el grading no pudo decidir.

    None no es False. Tratarlos igual es lo que colaba falsos positivos de cumplimiento:
    "no se pudo verificar" se convertía en "verificado y no aplica"."""

    def test_relevante_none_marca(self):
        marcada = evaluar_revision_manual(_link(relevante=None))
        assert marcada.requiere_revision_manual is True
        assert MOTIVO_VEREDICTO_INDETERMINADO in marcada.motivos_revision

    @pytest.mark.parametrize("veredicto", [True, False])
    def test_un_veredicto_cerrado_no_dispara_este_motivo(self, veredicto):
        marcada = evaluar_revision_manual(_link(relevante=veredicto))
        assert MOTIVO_VEREDICTO_INDETERMINADO not in marcada.motivos_revision

    def test_no_confunde_false_con_indeterminado(self):
        """`relevante=False` es un juicio emitido: la sección se miró y no le aplica."""
        marcada = evaluar_revision_manual(_link(relevante=False))
        assert marcada.requiere_revision_manual is False


class TestDisparadorConflictoLexicoSemantico:
    """3 · Las dos evidencias se contradicen y ninguna heurística puede decir cuál manda."""

    @pytest.mark.parametrize("origen", [ORIGEN_LEXICO, ORIGEN_LEXICO_AMBIGUO])
    def test_cita_explicita_con_veredicto_irrelevante_marca(self, origen):
        """El manual cita el artículo por número y el grading dice que no le aplica: una
        de las dos lecturas está mal."""
        marcada = evaluar_revision_manual(_link(origen=origen, relevante=False))
        assert marcada.requiere_revision_manual is True
        assert MOTIVO_CONFLICTO_LEXICO_SEMANTICO in marcada.motivos_revision

    def test_detecta_el_lexico_en_los_origenes_acumulados(self):
        """Tras la fusión de las dos vías, `origen` puede ser el semántico y la evidencia
        léxica vivir solo en `origenes`. Mirar únicamente `origen` perdería el conflicto."""
        marcada = evaluar_revision_manual(_link(
            origen=ORIGEN_SEMANTICO_V1,
            origenes=(ORIGEN_LEXICO, ORIGEN_SEMANTICO_V1),
            relevante=False,
        ))
        assert MOTIVO_CONFLICTO_LEXICO_SEMANTICO in marcada.motivos_revision

    def test_cita_explicita_confirmada_no_es_conflicto(self):
        """Que las dos evidencias coincidan es el caso fuerte, no uno dudoso."""
        marcada = evaluar_revision_manual(_link(origen=ORIGEN_LEXICO, relevante=True))
        assert MOTIVO_CONFLICTO_LEXICO_SEMANTICO not in marcada.motivos_revision

    def test_relevancia_afirmada_sin_evidencia_que_la_sostenga_marca(self):
        """El recíproco, acotado: relevante=True sin cita léxica y con el score por debajo
        del umbral. El caso literal —cualquier relevancia semántica sin cita— es el flujo
        normal del pipeline y marcarlo entero dejaría el flag inservible."""
        marcada = evaluar_revision_manual(
            _link(origen=ORIGEN_SEMANTICO_V2, relevante=True, score_semantico=0.10)
        )
        assert MOTIVO_CONFLICTO_LEXICO_SEMANTICO in marcada.motivos_revision

    def test_relevancia_semantica_con_score_holgado_no_es_conflicto(self):
        """El caso normal del pipeline: la mayoría de las aristas son esto y marcarlas
        vaciaría de sentido el filtro."""
        marcada = evaluar_revision_manual(
            _link(origen=ORIGEN_SEMANTICO_V2, relevante=True, score_semantico=0.90)
        )
        assert marcada.motivos_revision == ()

    def test_un_veredicto_indeterminado_no_cuenta_como_conflicto(self):
        """No hay contradicción sin dos afirmaciones: `None` no afirma nada. Se marca —por
        el disparador 2— pero el motivo tiene que ser el correcto, porque el motivo es lo
        que el auditor lee para saber qué mirar."""
        marcada = evaluar_revision_manual(_link(origen=ORIGEN_LEXICO, relevante=None))
        assert MOTIVO_CONFLICTO_LEXICO_SEMANTICO not in marcada.motivos_revision
        assert MOTIVO_VEREDICTO_INDETERMINADO in marcada.motivos_revision


class TestDisparadorParcialConBrechas:
    """5 · "Parcial con brechas declaradas": el modelo ya dijo qué falta; si eso basta o
    no lo decide el auditor."""

    def test_parcial_con_brechas_marca(self):
        marcada = evaluar_revision_manual(_link(
            nivel_cumplimiento="parcial",
            brechas=("no fija el plazo de conservación de diez años",),
        ))
        assert marcada.requiere_revision_manual is True
        assert MOTIVO_PARCIAL_CON_BRECHAS in marcada.motivos_revision

    def test_parcial_sin_brechas_no_marca(self):
        """Sin brechas declaradas es un veredicto cerrado; marcarlo mandaría a revisión a
        mano todo lo que no sea un cumplimiento perfecto."""
        marcada = evaluar_revision_manual(_link(nivel_cumplimiento="parcial", brechas=()))
        assert MOTIVO_PARCIAL_CON_BRECHAS not in marcada.motivos_revision

    @pytest.mark.parametrize("nivel", ["cumple", "omision", "no_aplica", None])
    def test_otros_niveles_con_brechas_no_disparan_este_motivo(self, nivel):
        marcada = evaluar_revision_manual(
            _link(nivel_cumplimiento=nivel, brechas=("algo",))
        )
        assert MOTIVO_PARCIAL_CON_BRECHAS not in marcada.motivos_revision


class TestVariosMotivosALaVez:
    """Los motivos se acumulan: el auditor tiene que ver *todas* las razones, no la
    primera que se encontró."""

    def test_una_arista_puede_acumular_tres_motivos(self):
        marcada = evaluar_revision_manual(_link(
            origen=ORIGEN_LEXICO,
            score_semantico=UMBRAL + 0.02,   # banda
            relevante=None,                  # indeterminado
            nivel_cumplimiento="parcial",
            brechas=("falta el plazo",),     # parcial con brechas
        ))
        assert set(marcada.motivos_revision) == {
            MOTIVO_BANDA_INDECISION,
            MOTIVO_VEREDICTO_INDETERMINADO,
            MOTIVO_PARCIAL_CON_BRECHAS,
        }

    def test_los_motivos_salen_ordenados_y_sin_duplicados(self):
        """Orden estable: el papel de trabajo se compara entre corridas y un `set` sin
        ordenar produciría diffs falsos."""
        marcada = evaluar_revision_manual(_link(
            relevante=None,
            motivos_revision=(MOTIVO_VEREDICTO_INDETERMINADO, MOTIVO_CITA_AMBIGUA),
        ))
        assert marcada.motivos_revision == tuple(sorted(set(marcada.motivos_revision)))
        assert marcada.motivos_revision.count(MOTIVO_VEREDICTO_INDETERMINADO) == 1

    def test_conserva_los_motivos_de_aguas_arriba(self):
        """`cita_ambigua` y `grading_no_parseable` los escriben `dual` y `llm_grader`: la
        evaluación posterior no puede borrar lo que ellos vieron y la arista ya no
        recuerda."""
        marcada = evaluar_revision_manual(_link(
            origen=ORIGEN_LEXICO_AMBIGUO,
            relevante=None,
            requiere_revision=True,
            motivos_revision=(MOTIVO_CITA_AMBIGUA,),
        ))
        assert MOTIVO_CITA_AMBIGUA in marcada.motivos_revision
        assert MOTIVO_VEREDICTO_INDETERMINADO in marcada.motivos_revision

    def test_no_desmarca_lo_marcado_a_mano(self):
        """Una persona marcó la arista por algo que ningún disparador ve. Desmarcarla al
        re-evaluar sería perder una decisión humana."""
        marcada = evaluar_revision_manual(_link(requiere_revision_manual=True))
        assert marcada.requiere_revision_manual is True

    def test_es_idempotente(self):
        """El pipeline puede re-evaluar tras cargar un checkpoint; dos pasadas tienen que
        dar exactamente lo mismo."""
        una = evaluar_revision_manual(_link(relevante=None, score_semantico=UMBRAL))
        dos = evaluar_revision_manual(una)
        assert una == dos

    def test_no_muta_la_arista_de_entrada(self):
        original = _link(relevante=None)
        evaluar_revision_manual(original)
        assert original.requiere_revision_manual is False
        assert original.motivos_revision == ()


class TestLosDosAliasDelFlag:
    """`requiere_revision` (nombre que ya escribían `dual`/`llm_grader` y los checkpoints)
    y `requiere_revision_manual` (nombre del ítem 10) son el mismo hecho."""

    @pytest.mark.parametrize(
        "campo", ["requiere_revision", "requiere_revision_manual"]
    )
    def test_marcar_cualquiera_marca_el_otro(self, campo):
        enlace = _link(**{campo: True})
        assert enlace.requiere_revision is True
        assert enlace.requiere_revision_manual is True

    def test_tras_evaluar_siguen_sincronizados(self):
        marcada = evaluar_revision_manual(_link(relevante=None))
        assert marcada.requiere_revision == marcada.requiere_revision_manual is True


class TestEvaluarListasYTablas:
    """La función pública acepta lo que traen los tres sitios que la llaman."""

    def test_evalua_una_lista_de_aristas(self):
        aristas = [
            _link(seccion_chunk_id="s1", relevante=None),
            _link(seccion_chunk_id="s2"),
        ]
        marcadas = evaluar_revision_manual(aristas)
        assert [x.requiere_revision_manual for x in marcadas] == [True, False]

    def test_la_tabla_evalua_todas_sus_aristas(self):
        tabla = LinkTable([
            _link(seccion_chunk_id="s1", relevante=None),
            _link(seccion_chunk_id="s2", score_semantico=UMBRAL),
            _link(seccion_chunk_id="s3"),
        ])
        assert tabla.evaluar_revision_manual() is tabla, "debe devolver self para encadenar"
        assert len(tabla.para_revision()) == 2
        assert len(tabla) == 3, "evaluar no puede perder ni duplicar aristas"

    def test_la_tabla_sigue_indexada_por_clave_tras_evaluar(self):
        """Si la re-inserción usara otra clave, `por_articulo` dejaría de encontrar la
        arista y la cobertura se calcularía sobre una tabla rota."""
        tabla = LinkTable([_link(relevante=None)]).evaluar_revision_manual()
        assert len(tabla.por_articulo(f"{DOC_LEY}_0003")) == 1

    def test_la_fusion_une_los_motivos_de_las_dos_vias(self):
        """Que una vía no viera motivo para revisar no borra el que encontró la otra."""
        tabla = LinkTable([
            _link(origen=ORIGEN_SEMANTICO_V1, relevante=True),
            _link(origen=ORIGEN_SEMANTICO_V2, relevante=True,
                  requiere_revision=True, motivos_revision=(MOTIVO_CITA_AMBIGUA,)),
        ])
        enlace = next(iter(tabla))
        assert enlace.requiere_revision_manual is True
        assert MOTIVO_CITA_AMBIGUA in enlace.motivos_revision


# ── Agregación en las dos vistas (ítem 6) ─────────────────────────────────────

@pytest.fixture
def manual_mini() -> pd.DataFrame:
    return pd.DataFrame([
        {"chunk_id": "sec_dudosa", "doc_id": DOC_MANUAL, "jerarquia": "2.2 Registro",
         "titulo_seccion": "Registro y conservación"},
        {"chunk_id": "sec_limpia", "doc_id": DOC_MANUAL, "jerarquia": "4.1 Cliente",
         "titulo_seccion": "Conocimiento del cliente"},
        {"chunk_id": "sec_huerfana", "doc_id": DOC_MANUAL, "jerarquia": "7.1 Vestimenta",
         "titulo_seccion": "Código de vestimenta"},
    ])


@pytest.fixture
def normativa_mini() -> pd.DataFrame:
    return pd.DataFrame([
        {"element_id": "art_dudoso", "doc_id": DOC_LEY, "numero": "5",
         "encabezado": "Registro de operaciones", "tipo_elemento": "articulo",
         "es_referencia": False},
        {"element_id": "art_limpio", "doc_id": DOC_LEY, "numero": "8",
         "encabezado": "Debida diligencia", "tipo_elemento": "articulo",
         "es_referencia": False},
        {"element_id": "art_huerfano", "doc_id": DOC_LEY, "numero": "12",
         "encabezado": "Continuidad del negocio", "tipo_elemento": "articulo",
         "es_referencia": False},
    ])


@pytest.fixture
def tabla_mixta() -> LinkTable:
    """Una arista dudosa (dos motivos), una limpia, y un artículo sin ninguna arista."""
    return LinkTable([
        _link(articulo_element_id="art_dudoso", seccion_chunk_id="sec_dudosa",
              origen=ORIGEN_LEXICO, relevante=None, score_semantico=UMBRAL),
        _link(articulo_element_id="art_limpio", seccion_chunk_id="sec_limpia",
              relevante=True),
    ]).evaluar_revision_manual()


class TestAgregacionEnVistaManual:
    def test_la_seccion_dudosa_queda_marcada_con_sus_motivos(self, tabla_mixta, manual_mini):
        fila = vista_manual(tabla_mixta, manual_mini).set_index("chunk_id").loc["sec_dudosa"]
        assert bool(fila["requiere_revision_manual"]) is True
        assert set(fila["motivos_revision"]) == {
            MOTIVO_BANDA_INDECISION, MOTIVO_VEREDICTO_INDETERMINADO,
        }

    def test_la_seccion_limpia_no_se_marca(self, tabla_mixta, manual_mini):
        fila = vista_manual(tabla_mixta, manual_mini).set_index("chunk_id").loc["sec_limpia"]
        assert bool(fila["requiere_revision_manual"]) is False
        assert list(fila["motivos_revision"]) == []

    def test_los_dos_alias_coinciden_en_la_vista(self, tabla_mixta, manual_mini):
        """Excel, API e interfaz pueden haberse escrito contra cualquiera de los dos
        nombres; que discrepen daría dos recuentos distintos del mismo hecho."""
        vista = vista_manual(tabla_mixta, manual_mini)
        assert (vista["requiere_revision"] == vista["requiere_revision_manual"]).all()

    def test_basta_una_arista_marcada_para_marcar_la_seccion(self, manual_mini):
        """La sección hereda la duda de cualquiera de sus artículos: es la unidad que el
        auditor abre."""
        tabla = LinkTable([
            _link(articulo_element_id="a1", seccion_chunk_id="sec_limpia", relevante=True),
            _link(articulo_element_id="a2", seccion_chunk_id="sec_limpia", relevante=None),
        ]).evaluar_revision_manual()
        fila = vista_manual(tabla, manual_mini).set_index("chunk_id").loc["sec_limpia"]
        assert bool(fila["requiere_revision_manual"]) is True
        assert MOTIVO_VEREDICTO_INDETERMINADO in fila["motivos_revision"]

    def test_una_seccion_sin_norma_aplicable_no_se_marca(self, tabla_mixta, manual_mini):
        """`no_aplica` legítimo (§ corpus, 7.1 Código de vestimenta): no toda sección del
        manual desarrolla una norma, y marcarlas todas ahogaría el filtro. El disparador
        de "sin cobertura" es de la Vía 2, donde sí es una brecha."""
        fila = vista_manual(tabla_mixta, manual_mini).set_index("chunk_id").loc["sec_huerfana"]
        assert bool(fila["requiere_revision_manual"]) is False


class TestAgregacionEnVistaNormativa:
    """4 · `articulo_sin_cobertura` — el disparador que solo existe en la Vía 2."""

    def test_articulo_sin_ninguna_arista_se_marca(self, tabla_mixta, normativa_mini):
        """No tener candidatos no es haber comprobado que no le aplica nada. Es el
        artículo huérfano del corpus y la premisa del Bloque A: cobertura < 100 %."""
        fila = vista_normativa(tabla_mixta, normativa_mini).set_index("element_id").loc[
            "art_huerfano"
        ]
        assert bool(fila["cubierto"]) is False
        assert bool(fila["requiere_revision_manual"]) is True
        assert fila["motivos_revision"] == [MOTIVO_ARTICULO_SIN_COBERTURA]

    def test_articulo_con_aristas_pero_ninguna_confirmada_se_marca(self, normativa_mini):
        """El caso que se cuela: hay candidatos, el grading los descartó a todos y el
        artículo queda igual de descubierto que el huérfano. El flag y el motivo tienen
        que ir juntos — un motivo sin flag no aparece en el filtro."""
        tabla = LinkTable([
            _link(articulo_element_id="art_dudoso", seccion_chunk_id="sec_limpia",
                  relevante=False, score_semantico=0.95),
        ]).evaluar_revision_manual()
        fila = vista_normativa(tabla, normativa_mini).set_index("element_id").loc["art_dudoso"]
        assert bool(fila["cubierto"]) is False
        assert bool(fila["requiere_revision_manual"]) is True
        assert MOTIVO_ARTICULO_SIN_COBERTURA in fila["motivos_revision"]

    def test_articulo_cubierto_y_sin_dudas_no_se_marca(self, tabla_mixta, normativa_mini):
        fila = vista_normativa(tabla_mixta, normativa_mini).set_index("element_id").loc[
            "art_limpio"
        ]
        assert bool(fila["cubierto"]) is True
        assert bool(fila["requiere_revision_manual"]) is False
        assert list(fila["motivos_revision"]) == []

    def test_acumula_los_motivos_de_la_arista_y_el_de_la_vista(self, tabla_mixta,
                                                               normativa_mini):
        """`art_dudoso` tiene una arista indeterminada: ni confirma cobertura ni la
        descarta. El auditor tiene que ver las tres razones a la vez."""
        fila = vista_normativa(tabla_mixta, normativa_mini).set_index("element_id").loc[
            "art_dudoso"
        ]
        assert set(fila["motivos_revision"]) == {
            MOTIVO_ARTICULO_SIN_COBERTURA,
            MOTIVO_BANDA_INDECISION,
            MOTIVO_VEREDICTO_INDETERMINADO,
        }

    def test_los_dos_alias_coinciden_en_la_vista(self, tabla_mixta, normativa_mini):
        vista = vista_normativa(tabla_mixta, normativa_mini)
        assert (vista["requiere_revision"] == vista["requiere_revision_manual"]).all()

    def test_ninguna_fila_marcada_aparece_como_veredicto_cerrado(self, tabla_mixta,
                                                                 normativa_mini):
        """DoD del ítem 10, en su forma verificable: si algo está marcado para revisión,
        no puede figurar a la vez como cobertura confirmada y sin motivo que lo explique."""
        vista = vista_normativa(tabla_mixta, normativa_mini)
        marcadas = vista[vista["requiere_revision_manual"]]
        assert not marcadas.empty
        for _, fila in marcadas.iterrows():
            assert fila["motivos_revision"], "marcada sin motivo: el auditor no sabe qué mirar"

    def test_las_referencias_excluidas_no_inflan_la_revision(self, normativa_mini):
        """Un artículo `es_referencia` no es una obligación sustantiva: contarlo como
        "sin cobertura" mandaría a revisión manual algo que nadie tiene que cumplir."""
        df = pd.concat([normativa_mini, pd.DataFrame([{
            "element_id": "art_remision", "doc_id": DOC_LEY, "numero": "20",
            "encabezado": "Remisión normativa", "tipo_elemento": "articulo",
            "es_referencia": True,
        }])], ignore_index=True)
        vista = vista_normativa(LinkTable(), df)
        assert "art_remision" not in set(vista["element_id"])


class TestPersistenciaDelFlag:
    """El flag tiene que sobrevivir al checkpoint: si se pierde al guardar, la corrida
    reanudada da un papel de trabajo sin marcas y nadie lo nota."""

    def test_ida_y_vuelta_por_parquet(self, tmp_path):
        tabla = LinkTable([
            _link(relevante=None, nivel_cumplimiento="parcial", brechas=("falta el plazo",)),
        ]).evaluar_revision_manual()
        original = next(iter(tabla))

        recargada = next(iter(LinkTable.load(tabla.save(tmp_path / "links.parquet"))))
        assert recargada.requiere_revision_manual is True
        assert recargada.motivos_revision == original.motivos_revision
        assert recargada.brechas == original.brechas

    def test_una_arista_manual_marcada_sobrevive(self, tmp_path):
        tabla = LinkTable([_link(origen=ORIGEN_MANUAL, requiere_revision_manual=True)])
        recargada = next(iter(LinkTable.load(tabla.save(tmp_path / "links.parquet"))))
        assert recargada.requiere_revision is True

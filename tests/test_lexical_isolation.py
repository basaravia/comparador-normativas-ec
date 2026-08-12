"""Pruebas de aislamiento léxico entre normativas (defecto 2 de §2.2 del plan).

`NormativaIndex.lexical_scan()` comparaba solo por `numero` sobre el
`normativa_df` completo: con dos normativas cargadas a la vez, una cita como
"Art. 5" en el manual matcheaba el Art. 5 de *todas* las normativas que lo
tuvieran, generando aristas de cobertura falsas.

El corpus sintético (`tests/fixtures/corpus.py`) construye ese caso a
propósito: LEY-A y RES-B tienen cada una un artículo 5, y la sección "2.2
Registro y conservación" del manual cita "Art. 5" sin decir de cuál
(`COBERTURA_ESPERADA["numero_ambiguo"]`).

Criterio adoptado (documentado también en el docstring de
`NormativaIndex.lexical_scan`): ante un número de artículo compartido por
normativas distintas y sin nada en el texto que lo desambigüe, no se
devuelven los artículos de las dos normativas (arista falsa hacia la que el
manual no citó) ni se elige uno de forma arbitraria (fabricaría una cita que
el texto no respalda). Se descarta el match léxico para ese número; la
sección sigue evaluándose por la vía semántica, que sí tiene el contenido del
artículo para decidir con evidencia.

Estas pruebas usan `FakeIndex.lexical_scan()`, que delega en la
implementación real de `NormativaIndex.lexical_scan` (ver
`tests/fixtures/dobles.py`) — así se ejercita el código de producción, no una
reimplementación paralela.
"""
from __future__ import annotations

import pandas as pd

from src.search_engine import NormativaIndex
from tests.fixtures import COBERTURA_ESPERADA, DOC_LEY, DOC_RES, FakeEmbeddingBackend


def _seccion(manual_df: pd.DataFrame, jerarquia: str) -> dict:
    fila = manual_df[manual_df["jerarquia"] == jerarquia]
    assert not fila.empty, f"el corpus sintético ya no tiene una sección '{jerarquia}'"
    return fila.iloc[0].to_dict()


class TestNumeroNoAmbiguoSigueFuncionando:
    """Caso base: sin colisión entre normativas, el comportamiento no cambia."""

    def test_numero_exclusivo_de_una_normativa_matchea_solo_esa_normativa(self, fake_index, normativa_df):
        # El artículo 8 solo existe en LEY-A (RES-B no tiene artículo 8).
        matches = fake_index.lexical_scan("Ver Art. 8 para más detalle.", normativa_df=normativa_df)

        assert len(matches) == 1
        assert matches[0]["doc_id"] == DOC_LEY
        assert matches[0]["numero"] == "8"

    def test_dos_numeros_no_ambiguos_de_normativas_distintas_matchean_cada_uno_lo_suyo(
        self, fake_index, normativa_df
    ):
        # Art. 8 (solo LEY-A) y Art. 3 (solo RES-B): no colisionan entre sí,
        # cada uno tiene un único dueño.
        matches = fake_index.lexical_scan(
            "Conforme al Art. 8 y al Art. 3 del marco aplicable.", normativa_df=normativa_df
        )

        por_doc = {m["doc_id"]: m["numero"] for m in matches}
        assert por_doc == {DOC_LEY: "8", DOC_RES: "3"}

    def test_con_una_sola_normativa_cargada_no_hay_ambiguedad_posible(self, fake_index):
        from tests.fixtures import normativa_ley

        solo_ley = normativa_ley()
        matches = fake_index.lexical_scan("Conforme al Art. 5, ...", normativa_df=solo_ley)

        assert len(matches) == 1
        assert matches[0]["doc_id"] == DOC_LEY
        assert matches[0]["numero"] == "5"


class TestAislamientoEntreNormativasDistintas:
    """El caso del defecto 2: el mismo número existe en dos normativas."""

    def test_numero_ambiguo_no_genera_ninguna_cita_firme(self, fake_index, normativa_df):
        """Ni ambas como ciertas, ni una elegida a dedo.

        Se emiten etiquetados: descartarlos borraría el hecho de que el manual sí cita
        un artículo, y ese hecho lo necesitan el modelo N:N, la cobertura de la Vía 2 y
        el flag de revisión manual.
        """
        numero = COBERTURA_ESPERADA["numero_ambiguo"]
        assert numero == "5"

        matches = fake_index.lexical_scan(
            f"Conforme al Art. {numero}, se hace tal cosa.", normativa_df=normativa_df
        )

        assert matches, "descartar el match borra el dato de que el manual cita un artículo"
        assert all(m["match_type"] == "ambiguo" for m in matches), (
            f"el Art. {numero} existe en LEY-A y en RES-B y el manual no dice de cuál: "
            "ninguno puede presentarse como cita exacta"
        )
        assert all(m["similarity"] < 1.0 for m in matches), (
            "un match ambiguo no puede puntuar como una cita inequívoca"
        )
        assert all(m["razon_match"] for m in matches), (
            "la ambigüedad debe venir explicada, no solo señalada"
        )

    def test_la_seccion_real_del_corpus_marca_su_cita_como_ambigua(
        self, fake_index, normativa_df, manual_df
    ):
        seccion = _seccion(manual_df, "2.2 Registro y conservación")

        matches = fake_index.lexical_scan(seccion["texto"], normativa_df=normativa_df)

        assert {m["match_type"] for m in matches} == {"ambiguo"}

    def test_ningun_articulo_queda_ligado_como_cita_firme_a_esa_seccion(
        self, fake_index, normativa_df, manual_df
    ):
        """DoD del plan: con dos normativas cargadas, ningún artículo de la norma A
        aparece ligado *por vía léxica firme* a una sección cuyo número también
        pertenece a la norma B (y viceversa).

        La arista existe, pero declarada como ambigua: es la diferencia entre afirmar
        una cobertura y registrar un indicio.
        """
        seccion = _seccion(manual_df, "2.2 Registro y conservación")

        matches = fake_index.lexical_scan(seccion["texto"], normativa_df=normativa_df)

        firmes = [m for m in matches if m["match_type"] == "exacto"]
        assert not firmes, (
            f"estos artículos se presentan como cita firme sin que el texto lo respalde: "
            f"{[(m['doc_id'], m['numero']) for m in firmes]}"
        )
        # Y las dos normativas están representadas, no una elegida arbitrariamente.
        assert {m["doc_id"] for m in matches} == {DOC_LEY, DOC_RES}

    def test_otras_secciones_del_manual_no_se_ven_afectadas_por_la_ambiguedad_de_otra(
        self, fake_index, normativa_df, manual_df
    ):
        """La corrección es por número de artículo, no un apagado global del
        escaneo léxico: una sección que cita un número no ambiguo debe seguir
        matcheando con normalidad aunque el corpus tenga OTRO número ambiguo."""
        seccion_reporte = _seccion(manual_df, "3.1 Reporte de inusualidades")
        # Esta sección no cita ningún artículo por número en el corpus; se arma
        # un texto de prueba que sí lo hace, para aislar el comportamiento.
        texto = seccion_reporte["texto"] + " Ver Art. 8."

        matches = fake_index.lexical_scan(texto, normativa_df=normativa_df)

        assert len(matches) == 1
        assert matches[0]["doc_id"] == DOC_LEY
        assert matches[0]["numero"] == "8"


class TestFallbacksYCompatibilidad:
    def test_sin_columna_doc_id_no_hay_forma_de_desambiguar_y_se_preserva_el_comportamiento_previo(
        self, fake_index, normativa_df
    ):
        """Si el llamador no provee `doc_id`, no hay información para agrupar por
        normativa: se documenta como el límite del criterio, no se inventa una."""
        sin_doc_id = normativa_df.drop(columns=["doc_id"])

        matches = fake_index.lexical_scan("Conforme al Art. 5, ...", normativa_df=sin_doc_id)

        assert len(matches) == 2, "sin doc_id no se puede agrupar por normativa; no se filtra nada"

    def test_lexical_scan_usa_el_df_interno_cuando_no_se_pasa_normativa_df(self, normativa_df):
        """Firma pública (ver docstring de NormativaIndex): `lexical_scan(text)`
        sin segundo argumento debe seguir funcionando contra el índice ya
        construido con build()."""
        backend = FakeEmbeddingBackend()
        indice = NormativaIndex(backend, use_reranker=False)
        indice.build(normativa_df)

        matches = indice.lexical_scan("Conforme al Art. 8, ...")

        assert len(matches) == 1
        assert matches[0]["doc_id"] == DOC_LEY

    def test_numero_sin_ningun_articulo_correspondiente_no_rompe(self, fake_index, normativa_df):
        matches = fake_index.lexical_scan("Ver Art. 999.", normativa_df=normativa_df)
        assert matches == []

    def test_texto_sin_referencias_devuelve_lista_vacia(self, fake_index, normativa_df):
        matches = fake_index.lexical_scan("Texto sin ninguna cita normativa.", normativa_df=normativa_df)
        assert matches == []

"""Ítem 7 — el alcance por lista, no por cantidad.

Hasta ahora una corrida se elegía con un número ("muestra rápida de N secciones", además
al azar sin semilla). El encargo real es "Art. 35 y 36 de la Ley X contra el capítulo 5
del manual", y estas pruebas fijan que eso se pueda expresar y —sobre todo— que no se
ejecute *más* de lo pedido sin que nadie se entere.

Las tres cosas que la suite vigila, porque son las que ensucian un papel de trabajo:

  · Un filtro que no se puede aplicar **falla**, no devuelve todo en silencio: un alcance
    ignorado analiza de más y lo registra como si fuera lo pedido.
  · El alcance es un **dato serializable y comparable** (`RunScope`): reanudar un
    checkpoint con otro alcance produce un informe que dice cubrir unos artículos y
    analizó otros. La `huella()` es lo que hace verificable esa continuidad.
  · La muestra rápida es **reproducible**: dos corridas de prueba con el mismo N (y la
    misma semilla, si es aleatoria) analizan lo mismo.
"""
from __future__ import annotations

import dataclasses
import json
import logging

import pandas as pd
import pytest

from src.scope import (
    PRESET_EXCLUIR_REFERENCIAS,
    PRESET_SOLO_DISPOSICIONES,
    PRESET_TODO_EL_ARTICULADO,
    VERSION_ESQUEMA,
    RunScope,
    aplicar_preset,
    filtrar_articulos,
    filtrar_secciones,
    muestra_rapida,
    normalizar_numero,
)
from tests.fixtures import COBERTURA_ESPERADA, DOC_LEY, DOC_MANUAL, DOC_RES

ART_20_REFERENCIA = f"{DOC_LEY}_0006"
SEC_CONOCIMIENTO = "MANUAL-INTERNO_0004"
SEC_FORMACION = "MANUAL-INTERNO_0005"


def _numeros(df: pd.DataFrame) -> list[tuple[str, str]]:
    """(doc_id, numero) de cada fila — el par que identifica un artículo sin ambigüedad."""
    return list(zip(df["doc_id"], df["numero"]))


def _df_con_disposiciones() -> pd.DataFrame:
    """Corpus mínimo con los tres `tipo_elemento` del parser.

    El mini-corpus compartido es todo `articulo` (su artículo 20 es una *referencia*, que
    es otro eje), así que el filtro por tipo necesita material propio.
    """
    return pd.DataFrame([
        {"element_id": "X_0001", "doc_id": "X", "numero": "1", "seccion": "Título I",
         "tipo_elemento": "articulo", "es_referencia": False},
        {"element_id": "X_0002", "doc_id": "X", "numero": "2", "seccion": "Título I",
         "tipo_elemento": "articulo", "es_referencia": True},
        {"element_id": "X_0003", "doc_id": "X", "numero": "Primera", "seccion": "Disposiciones",
         "tipo_elemento": "disposicion", "es_referencia": True},
        {"element_id": "X_0004", "doc_id": "X", "numero": "1", "seccion": "Anexo 1",
         "tipo_elemento": "anexo", "es_referencia": False},
    ])


# ── normalizar_numero ─────────────────────────────────────────────────────────

class TestNormalizarNumero:
    """Quien escribe el alcance copia el número del documento, con su prefijo y su punto."""

    @pytest.mark.parametrize("crudo", [
        "35", "35.", "Art. 35", "art 35.", "ART 35", "Artículo 35", "artículo 35",
        "Articulo 35", "arts. 35", "Art.35", "  Art. 35  ", "035", "0035", 35,
    ])
    def test_todas_las_formas_de_escribir_el_mismo_articulo(self, crudo):
        assert normalizar_numero(crudo) == "35"

    def test_no_colapsa_los_sufijos(self):
        """"5 bis" es otro artículo: colapsarlo metería en el alcance uno que nadie pidió."""
        assert normalizar_numero("Art. 5 bis") == "5 bis"
        assert normalizar_numero("Art. 5") != normalizar_numero("Art. 5 bis")

    def test_el_cero_sobrevive(self):
        """El recorte de ceros a la izquierda no puede dejar el número vacío."""
        assert normalizar_numero("0") == "0"
        assert normalizar_numero("00") == "0"

    def test_vacio(self):
        assert normalizar_numero("") == ""


# ── filtrar_articulos ─────────────────────────────────────────────────────────

class TestFiltrarArticulosDefectos:
    """Lo que devuelve sin pedirle nada: el articulado sustantivo."""

    def test_sin_filtros_excluye_las_referencias(self, normativa_df):
        """Contar las remisiones a otras normas hunde la cobertura con artículos que
        nadie debe cumplir (mismo criterio que `coverage.vista_normativa`)."""
        assert len(filtrar_articulos(normativa_df)) == COBERTURA_ESPERADA["articulos_sustantivos"]

    def test_incluir_referencias_las_recupera(self, normativa_df):
        r = filtrar_articulos(normativa_df, incluir_referencias=True)
        assert len(r) == len(normativa_df)
        assert ART_20_REFERENCIA in set(r["element_id"])

    def test_es_referencia_nulo_cuenta_como_sustantivo(self):
        """Un parser que no marcó la fila no debe hacerla desaparecer del alcance."""
        df = pd.DataFrame([
            {"element_id": "X_0001", "numero": "1", "tipo_elemento": "articulo",
             "es_referencia": None},
        ])
        assert len(filtrar_articulos(df)) == 1

    def test_sin_columna_es_referencia_no_filtra(self):
        df = pd.DataFrame([{"element_id": "X_0001", "numero": "1", "tipo_elemento": "articulo"}])
        assert len(filtrar_articulos(df)) == 1

    def test_no_muta_la_entrada(self, normativa_df):
        antes = normativa_df.copy()
        filtrar_articulos(normativa_df, doc_ids=[DOC_LEY], numeros=["8"])
        pd.testing.assert_frame_equal(normativa_df, antes)

    def test_reinicia_el_indice(self, normativa_df):
        r = filtrar_articulos(normativa_df, doc_ids=[DOC_RES])
        assert list(r.index) == list(range(len(r)))

    def test_dataframe_vacio(self):
        r = filtrar_articulos(pd.DataFrame(columns=["element_id", "numero"]))
        assert r.empty and list(r.columns) == ["element_id", "numero"]


class TestFiltrarArticulosEjes:
    """`None`/vacío = sin restricción; los ejes se combinan con AND."""

    def test_por_doc_id(self, normativa_df):
        r = filtrar_articulos(normativa_df, doc_ids=[DOC_RES])
        assert set(r["doc_id"]) == {DOC_RES} and len(r) == 4

    def test_doc_id_acepta_un_string_suelto(self, normativa_df):
        """Un `doc_id` sin envolver en lista no debe interpretarse como sus letras."""
        r = filtrar_articulos(normativa_df, doc_ids=DOC_RES)
        assert set(r["doc_id"]) == {DOC_RES}

    def test_por_numero_normalizado(self, normativa_df):
        """El encargo dice "Art. 8", el DataFrame dice "8"."""
        r = filtrar_articulos(normativa_df, numeros=["Art. 8", "artículo 9"])
        assert _numeros(r) == [(DOC_LEY, "8"), (DOC_LEY, "9")]

    def test_un_numero_ambiguo_trae_las_dos_normas(self, normativa_df):
        """El "5" existe en LEY-A y en RES-B: el filtro por número solo no desambigua,
        y eso es visible en el resultado en vez de resolverse a escondidas."""
        r = filtrar_articulos(normativa_df, numeros=[COBERTURA_ESPERADA["numero_ambiguo"]])
        assert _numeros(r) == [(DOC_LEY, "5"), (DOC_RES, "5")]

    def test_doc_id_y_numero_se_combinan_con_and(self, normativa_df):
        """"El artículo 5 **de la Ley A**" — el encargo real."""
        r = filtrar_articulos(normativa_df, doc_ids=[DOC_LEY], numeros=["Art. 5"])
        assert _numeros(r) == [(DOC_LEY, "5")]

    def test_numero_inexistente_devuelve_vacio(self, normativa_df):
        assert filtrar_articulos(normativa_df, numeros=["999"]).empty

    def test_por_seccion_es_subcadena_sin_acentos(self, normativa_df):
        """"titulo ii > obligaciones" tiene que encontrar "Título II > Obligaciones": es
        un cuadro de búsqueda, no un identificador."""
        esperado = [(DOC_LEY, "8"), (DOC_LEY, "9")]
        for escrito in ("Título II > Obligaciones", "titulo ii > obligaciones",
                        "TÍTULO II > OBLIGACIONES", "obligaciones"):
            assert _numeros(filtrar_articulos(normativa_df, secciones=[escrito])) == esperado

    def test_un_numeral_romano_corto_arrastra_a_los_largos(self, normativa_df):
        """Trampa de la subcadena: "Título II" también cae en "Título III". Se deja fijado
        porque es lo que ve quien escribe el alcance —el resultado lo delata y estrecha—,
        no un cribado silencioso que analizaría de menos."""
        r = filtrar_articulos(normativa_df, secciones=["Título II"])
        assert _numeros(r) == [(DOC_LEY, "8"), (DOC_LEY, "9"), (DOC_LEY, "12")]

    def test_varias_secciones_se_suman(self, normativa_df):
        r = filtrar_articulos(normativa_df, secciones=["Título III", "Capítulo II"])
        assert _numeros(r) == [(DOC_LEY, "12"), (DOC_RES, "7"), (DOC_RES, "11")]

    def test_la_subcadena_no_es_un_prefijo(self, normativa_df):
        """"disposiciones" cae tanto en "Título I > Disposiciones generales" como en
        "Disposiciones finales": el que escribe el alcance ve el resultado y estrecha."""
        r = filtrar_articulos(normativa_df, secciones=["disposiciones"], incluir_referencias=True)
        assert _numeros(r) == [(DOC_LEY, "1"), (DOC_LEY, "5"), (DOC_LEY, "20")]

    def test_seccion_y_doc_id_se_combinan(self, normativa_df):
        r = filtrar_articulos(normativa_df, doc_ids=[DOC_RES], secciones=["capítulo ii"])
        assert _numeros(r) == [(DOC_RES, "7"), (DOC_RES, "11")]

    def test_ejes_vacios_no_restringen(self, normativa_df):
        completo = filtrar_articulos(normativa_df)
        r = filtrar_articulos(normativa_df, doc_ids=[], numeros=(), secciones=None)
        pd.testing.assert_frame_equal(r, completo)


class TestFiltrarArticulosTiposElemento:
    """`None`, `()` y `("x",)` son tres cosas distintas a propósito."""

    def test_por_defecto_solo_articulos(self):
        r = filtrar_articulos(_df_con_disposiciones(), incluir_referencias=True)
        assert set(r["tipo_elemento"]) == {"articulo"}

    def test_coleccion_vacia_es_sin_filtro_por_tipo(self):
        """"Todo", explícito: disposiciones y anexos incluidos."""
        r = filtrar_articulos(_df_con_disposiciones(), tipos_elemento=(), incluir_referencias=True)
        assert len(r) == 4

    def test_tipos_concretos(self):
        r = filtrar_articulos(
            _df_con_disposiciones(),
            tipos_elemento=["disposicion", "anexo"],
            incluir_referencias=True,
        )
        assert set(r["element_id"]) == {"X_0003", "X_0004"}

    def test_el_defecto_se_salta_si_no_hay_columna(self):
        """No todo corpus trae `tipo_elemento`; el defecto no puede vaciar el alcance."""
        df = pd.DataFrame([{"element_id": "X_0001", "numero": "1"}])
        assert len(filtrar_articulos(df)) == 1

    def test_un_tipo_pedido_a_mano_sin_columna_falla(self):
        df = pd.DataFrame([{"element_id": "X_0001", "numero": "1"}])
        with pytest.raises(ValueError, match="tipo_elemento"):
            filtrar_articulos(df, tipos_elemento=["disposicion"])


class TestFiltrarArticulosColumnaAusente:
    """Un filtro que no se puede aplicar es un error, no un no-op."""

    @pytest.mark.parametrize("kwargs, columna", [
        ({"doc_ids": ["X"]}, "doc_id"),
        ({"numeros": ["1"]}, "numero"),
        ({"secciones": ["Título I"]}, "seccion"),
    ])
    def test_falla_en_vez_de_devolver_todo(self, kwargs, columna):
        df = pd.DataFrame([{"element_id": "X_0001", "otra": "cosa"}])
        with pytest.raises(ValueError, match=columna):
            filtrar_articulos(df, **kwargs)

    def test_el_mensaje_dice_qué_columnas_hay(self):
        df = pd.DataFrame([{"element_id": "X_0001", "otra": "cosa"}])
        with pytest.raises(ValueError, match="element_id"):
            filtrar_articulos(df, doc_ids=["X"])


class TestPresets:
    """Los presets son kwargs, no ramas: el preset y la selección a mano no divergen."""

    def test_todo_el_articulado_incluye_las_referencias(self, normativa_df):
        r = aplicar_preset(normativa_df, PRESET_TODO_EL_ARTICULADO)
        assert ART_20_REFERENCIA in set(r["element_id"])

    def test_excluir_referencias_es_el_defecto_de_trabajo(self, normativa_df):
        pd.testing.assert_frame_equal(
            aplicar_preset(normativa_df, PRESET_EXCLUIR_REFERENCIAS),
            filtrar_articulos(normativa_df),
        )

    def test_solo_disposiciones_no_les_aplica_el_filtro_de_referencias(self):
        """Casi todas las disposiciones son remisiones; excluirlas dejaría el preset vacío."""
        r = aplicar_preset(_df_con_disposiciones(), PRESET_SOLO_DISPOSICIONES)
        assert set(r["element_id"]) == {"X_0003"}

    def test_un_preset_se_puede_estrechar_con_otro_eje(self, normativa_df):
        """"Todo el articulado **de la Ley A**" es un preset más un eje, no otro preset."""
        r = aplicar_preset(normativa_df, PRESET_TODO_EL_ARTICULADO, doc_ids=[DOC_LEY])
        assert set(r["doc_id"]) == {DOC_LEY} and len(r) == 6

    def test_preset_desconocido(self, normativa_df):
        with pytest.raises(ValueError, match="Preset desconocido"):
            aplicar_preset(normativa_df, "muestra_rapida")


# ── filtrar_secciones ─────────────────────────────────────────────────────────

class TestFiltrarSecciones:
    def test_sin_filtros_devuelve_todo(self, manual_df):
        assert len(filtrar_secciones(manual_df)) == len(manual_df)

    def test_por_doc_id(self, manual_df):
        assert len(filtrar_secciones(manual_df, doc_ids=[DOC_MANUAL])) == len(manual_df)
        assert filtrar_secciones(manual_df, doc_ids=["OTRO.pdf"]).empty

    def test_jerarquia_toma_el_capitulo_entero(self, manual_df):
        """"el capítulo 5 del manual" sin enumerar sus secciones una a una."""
        r = filtrar_secciones(manual_df, jerarquias=["5."])
        assert list(r["chunk_id"]) == [SEC_FORMACION]

    def test_varias_jerarquias_se_suman(self, manual_df):
        r = filtrar_secciones(manual_df, jerarquias=["4", "5"])
        assert list(r["chunk_id"]) == [SEC_CONOCIMIENTO, SEC_FORMACION]

    def test_jerarquia_sin_acentos_ni_mayusculas(self, manual_df):
        r = filtrar_secciones(manual_df, jerarquias=["CODIGO DE VESTIMENTA"])
        assert list(r["jerarquia"]) == COBERTURA_ESPERADA["secciones_sin_norma"]

    def test_chunk_ids_es_seleccion_exacta(self, manual_df):
        r = filtrar_secciones(manual_df, chunk_ids=[SEC_CONOCIMIENTO])
        assert list(r["chunk_id"]) == [SEC_CONOCIMIENTO]

    def test_chunk_ids_no_reordena(self, manual_df):
        """El papel de trabajo se lee en el orden del documento, no en el de los clics."""
        r = filtrar_secciones(manual_df, chunk_ids=[SEC_FORMACION, SEC_CONOCIMIENTO])
        assert list(r["chunk_id"]) == [SEC_CONOCIMIENTO, SEC_FORMACION]

    def test_chunk_id_repetido_no_duplica_la_fila(self, manual_df):
        r = filtrar_secciones(manual_df, chunk_ids=[SEC_CONOCIMIENTO, SEC_CONOCIMIENTO])
        assert len(r) == 1

    def test_jerarquia_y_chunk_ids_se_combinan_con_and(self, manual_df):
        r = filtrar_secciones(
            manual_df, jerarquias=["4"], chunk_ids=[SEC_CONOCIMIENTO, SEC_FORMACION],
        )
        assert list(r["chunk_id"]) == [SEC_CONOCIMIENTO]

    def test_no_muta_la_entrada(self, manual_df):
        antes = manual_df.copy()
        filtrar_secciones(manual_df, jerarquias=["4"])
        pd.testing.assert_frame_equal(manual_df, antes)

    def test_reinicia_el_indice(self, manual_df):
        r = filtrar_secciones(manual_df, jerarquias=["6", "7", "8"])
        assert list(r.index) == [0, 1, 2]

    def test_dataframe_vacio(self):
        assert filtrar_secciones(pd.DataFrame(columns=["chunk_id"])).empty

    @pytest.mark.parametrize("kwargs, columna", [
        ({"doc_ids": ["X"]}, "doc_id"),
        ({"jerarquias": ["4"]}, "jerarquia"),
        ({"chunk_ids": ["c1"]}, "chunk_id"),
    ])
    def test_columna_ausente_falla(self, kwargs, columna):
        df = pd.DataFrame([{"otra": "cosa"}])
        with pytest.raises(ValueError, match=columna):
            filtrar_secciones(df, **kwargs)


# ── muestra_rapida ────────────────────────────────────────────────────────────

class TestMuestraRapida:
    def test_por_defecto_son_las_primeras_n(self, manual_df):
        """No una muestra al azar como hacía `streamlit_app.py`: es lo que espera quien
        revisa por encima, y dos corridas con el mismo N analizan lo mismo."""
        r = muestra_rapida(manual_df, 3)
        assert list(r["chunk_id"]) == list(manual_df["chunk_id"])[:3]

    def test_n_mayor_que_el_alcance_devuelve_todo(self, manual_df):
        pd.testing.assert_frame_equal(muestra_rapida(manual_df, 999), manual_df)

    @pytest.mark.parametrize("n", [0, -1])
    def test_n_no_positivo_vacia_el_alcance_conservando_columnas(self, manual_df, n):
        r = muestra_rapida(manual_df, n)
        assert r.empty and list(r.columns) == list(manual_df.columns)

    def test_aleatoria_con_la_misma_semilla_es_reproducible(self, manual_df):
        a = muestra_rapida(manual_df, 3, aleatoria=True, semilla=42)
        b = muestra_rapida(manual_df, 3, aleatoria=True, semilla=42)
        pd.testing.assert_frame_equal(a, b)

    def test_la_semilla_manda(self, manual_df):
        a = muestra_rapida(manual_df, 3, aleatoria=True, semilla=42)
        b = muestra_rapida(manual_df, 3, aleatoria=True, semilla=0)
        assert list(a["chunk_id"]) != list(b["chunk_id"])

    def test_aleatoria_devuelve_n_filas_del_alcance(self, manual_df):
        r = muestra_rapida(manual_df, 3, aleatoria=True, semilla=7)
        assert len(r) == 3
        assert set(r["chunk_id"]) <= set(manual_df["chunk_id"])

    def test_aleatoria_conserva_el_orden_del_documento(self, manual_df):
        """Se muestrea al azar *qué* entra, no en qué orden se lee."""
        r = muestra_rapida(manual_df, 4, aleatoria=True, semilla=42)
        orden = list(manual_df["chunk_id"])
        assert list(r["chunk_id"]) == sorted(r["chunk_id"], key=orden.index)

    def test_se_aplica_sobre_el_alcance_ya_filtrado(self, normativa_df):
        """El orden es filtrar y luego recortar: "las 2 primeras **de la Ley A**"."""
        r = muestra_rapida(filtrar_articulos(normativa_df, doc_ids=[DOC_LEY]), 2)
        assert _numeros(r) == [(DOC_LEY, "1"), (DOC_LEY, "5")]


# ── RunScope ──────────────────────────────────────────────────────────────────

def _scope_de_ejemplo() -> RunScope:
    return RunScope(
        articulos=[f"{DOC_LEY}_0003", f"{DOC_LEY}_0004"],
        secciones=[SEC_CONOCIMIENTO],
        doc_ids_normativa=[DOC_LEY],
        numeros=["8", "9"],
        preset_articulos=PRESET_EXCLUIR_REFERENCIAS,
        etiqueta="Título II de la Ley A contra el capítulo 4",
    )


class TestRunScopeDesdeDataframes:
    """Se le pasan los DataFrames **ya filtrados**: el alcance registrado y el que se
    ejecuta son el mismo objeto y no pueden discrepar."""

    def test_captura_los_ids_y_los_criterios(self, normativa_df, manual_df):
        normativa = filtrar_articulos(normativa_df, doc_ids=[DOC_LEY], secciones=["Obligaciones"])
        manual = filtrar_secciones(manual_df, jerarquias=["4"])
        scope = RunScope.desde_dataframes(
            normativa, manual,
            doc_ids_normativa=[DOC_LEY], secciones_normativa=["Obligaciones"], jerarquias=["4"],
        )
        assert scope.articulos == (f"{DOC_LEY}_0003", f"{DOC_LEY}_0004")
        assert scope.secciones == (SEC_CONOCIMIENTO,)
        assert scope.secciones_normativa == ("Obligaciones",)
        assert scope.doc_ids_normativa == (DOC_LEY,)
        assert scope.jerarquias == ("4",)

    def test_conserva_el_orden_del_documento(self, normativa_df, manual_df):
        scope = RunScope.desde_dataframes(filtrar_articulos(normativa_df), manual_df)
        assert scope.articulos == tuple(filtrar_articulos(normativa_df)["element_id"])
        assert scope.secciones == tuple(manual_df["chunk_id"])

    def test_sin_las_columnas_de_id_no_revienta(self):
        scope = RunScope.desde_dataframes(pd.DataFrame([{"a": 1}]), pd.DataFrame([{"b": 2}]))
        assert scope.articulos == () and scope.secciones == ()

    def test_dataframes_vacios_dan_un_alcance_vacio(self, normativa_df, manual_df):
        scope = RunScope.desde_dataframes(
            filtrar_articulos(normativa_df, numeros=["999"]),
            filtrar_secciones(manual_df, chunk_ids=["no-existe"]),
        )
        assert scope.vacio


class TestRunScopeLectura:
    def test_cuentas(self):
        scope = _scope_de_ejemplo()
        assert (scope.n_articulos, scope.n_secciones) == (2, 1)
        assert not scope.vacio

    def test_las_llamadas_llm_se_suman_no_se_multiplican(self):
        """Cada vía recorre su lado una vez y la caché de grading comparte los veredictos:
        el contador en vivo de la pestaña 3 tiene que decir lo mismo que el DoD verifica."""
        assert _scope_de_ejemplo().llamadas_llm_estimadas == 3

    def test_el_alcance_vacio_no_cuesta_nada(self):
        assert RunScope().vacio and RunScope().llamadas_llm_estimadas == 0

    def test_resumen(self):
        assert _scope_de_ejemplo().resumen() == (
            "2 artículos × 1 secciones · ~3 llamadas LLM"
        )


class TestRunScopeNormalizacionDeEntradas:
    """Quien construye esto viene de un multiselect, no de un literal."""

    def test_las_listas_entran_como_tuplas(self):
        assert RunScope(articulos=["a", "b"]).articulos == ("a", "b")

    def test_un_string_suelto_no_se_desarma_en_letras(self):
        assert RunScope(articulos="a1").articulos == ("a1",)

    def test_los_generadores_y_los_no_strings_se_materializan(self):
        scope = RunScope(articulos=(f"x{i}" for i in range(2)), numeros=[8, 9])
        assert scope.articulos == ("x0", "x1") and scope.numeros == ("8", "9")

    def test_lista_y_tupla_producen_el_mismo_alcance(self):
        assert RunScope(articulos=["a", "b"]) == RunScope(articulos=("a", "b"))


class TestRunScopeInmutabilidad:
    """El alcance de una corrida es un hecho registrado, no un objeto que se ajusta a
    mitad de camino (mismo motivo que `CoverageLink`)."""

    def test_no_se_puede_reasignar_un_campo(self):
        scope = _scope_de_ejemplo()
        with pytest.raises(dataclasses.FrozenInstanceError):
            scope.articulos = ("otro",)

    def test_no_se_puede_reasignar_la_etiqueta(self):
        with pytest.raises(dataclasses.FrozenInstanceError):
            RunScope().etiqueta = "otra cosa"

    def test_los_ejes_no_son_mutables_en_sitio(self):
        scope = RunScope(articulos=["a"])
        assert isinstance(scope.articulos, tuple)
        with pytest.raises(AttributeError):
            scope.articulos.append("b")

    def test_es_hashable(self):
        """Comparar dos corridas exige poder meterlas en un set."""
        assert len({_scope_de_ejemplo(), _scope_de_ejemplo()}) == 1

    def test_to_dict_devuelve_una_copia_desconectada(self):
        scope = _scope_de_ejemplo()
        datos = scope.to_dict()
        datos["articulos"].append("colado")
        assert scope.articulos == (f"{DOC_LEY}_0003", f"{DOC_LEY}_0004")


class TestRunScopeSerializacion:
    """Lo que entra en `manifest.json` del checkpoint y en la hoja de trazabilidad."""

    def test_to_dict_es_json_serializable(self):
        datos = _scope_de_ejemplo().to_dict()
        assert all(not isinstance(v, tuple) for v in datos.values())
        json.dumps(datos)  # no debe levantar

    def test_to_dict_lleva_la_version_del_esquema(self):
        assert _scope_de_ejemplo().to_dict()["version_esquema"] == VERSION_ESQUEMA

    def test_ida_y_vuelta_por_dict(self):
        scope = _scope_de_ejemplo()
        assert RunScope.from_dict(scope.to_dict()) == scope

    def test_ida_y_vuelta_por_json(self):
        scope = _scope_de_ejemplo()
        assert RunScope.from_json(scope.to_json()) == scope

    def test_from_dict_vacio_o_nulo_da_los_defectos(self):
        assert RunScope.from_dict(None) == RunScope()
        assert RunScope.from_dict({}) == RunScope()

    def test_un_checkpoint_viejo_sin_los_campos_nuevos_se_lee(self):
        """Faltar campos no justifica reventar al reanudar."""
        scope = RunScope.from_dict({"articulos": ["a1"], "secciones": ["s1"]})
        assert scope.articulos == ("a1",) and scope.workspace_id == "local"

    def test_un_checkpoint_nuevo_leido_por_una_version_vieja_tampoco(self, caplog):
        with caplog.at_level(logging.WARNING, logger="src.scope"):
            scope = RunScope.from_dict({"articulos": ["a1"], "campo_del_futuro": 7})
        assert scope.articulos == ("a1",)
        assert "campo_del_futuro" in caplog.text

    def test_una_clave_conocida_no_dispara_el_aviso(self, caplog):
        with caplog.at_level(logging.WARNING, logger="src.scope"):
            RunScope.from_dict({"articulos": ["a1"]})
        assert caplog.text == ""


class TestRunScopeHuella:
    """El hash es lo que hace verificable que una reanudación cubre lo mismo."""

    def test_es_estable_entre_instancias_iguales(self):
        assert _scope_de_ejemplo().huella() == _scope_de_ejemplo().huella()

    def test_sobrevive_a_la_serializacion(self):
        scope = _scope_de_ejemplo()
        assert RunScope.from_json(scope.to_json()).huella() == scope.huella()

    def test_es_corto_y_hexadecimal(self):
        h = _scope_de_ejemplo().huella()
        assert len(h) == 16 and int(h, 16) >= 0

    def test_renombrar_el_encargo_no_invalida_el_checkpoint(self):
        """La etiqueta es descripción libre: no cambia *qué* se analiza."""
        a = RunScope(articulos=["a1"], etiqueta="revisión de marzo")
        b = RunScope(articulos=["a1"], etiqueta="revisión de abril")
        assert a != b and a.huella() == b.huella()

    @pytest.mark.parametrize("cambio", [
        {"articulos": ["a1", "a2"]},
        {"secciones": ["s9"]},
        {"doc_ids_normativa": [DOC_RES]},
        {"incluir_referencias": True},
        {"tipos_elemento": ["disposicion"]},
        {"muestra_n": 5},
        {"muestra_aleatoria": True},
        {"semilla": 7},
        {"workspace_id": "otro"},
    ])
    def test_cualquier_cambio_de_alcance_cambia_la_huella(self, cambio):
        base = RunScope(articulos=["a1"], secciones=["s1"])
        assert base.huella() != dataclasses.replace(base, **cambio).huella()

    def test_el_orden_de_los_ids_importa(self):
        """Dos alcances con los mismos artículos en otro orden no son el mismo registro:
        el papel de trabajo se lee en el orden del documento."""
        a = RunScope(articulos=["a1", "a2"])
        b = RunScope(articulos=["a2", "a1"])
        assert a.huella() != b.huella()


class TestRunScopeAplicarA:
    """Reconstruir el alcance sobre el corpus completo, al reanudar."""

    def test_manda_la_lista_de_ids_registrada(self, normativa_df, manual_df):
        """Un corpus reprocesado puede haber cambiado; vale lo que se analizó, no lo que
        el filtro devolvería hoy."""
        scope = RunScope(
            articulos=[f"{DOC_LEY}_0003"],
            secciones=[SEC_CONOCIMIENTO],
            doc_ids_normativa=[DOC_RES],   # contradice a los ids: los ids ganan
        )
        normativa, manual = scope.aplicar_a(normativa_df, manual_df)
        assert list(normativa["element_id"]) == [f"{DOC_LEY}_0003"]
        assert list(manual["chunk_id"]) == [SEC_CONOCIMIENTO]

    def test_sin_ids_vuelve_a_aplicar_los_criterios(self, normativa_df, manual_df):
        scope = RunScope(doc_ids_normativa=[DOC_LEY], numeros=["Art. 8"], jerarquias=["4"])
        normativa, manual = scope.aplicar_a(normativa_df, manual_df)
        assert _numeros(normativa) == [(DOC_LEY, "8")]
        assert list(manual["chunk_id"]) == [SEC_CONOCIMIENTO]

    def test_un_alcance_vacio_no_restringe_nada(self, normativa_df, manual_df):
        normativa, manual = RunScope().aplicar_a(normativa_df, manual_df)
        assert len(normativa) == COBERTURA_ESPERADA["articulos_sustantivos"]
        assert len(manual) == len(manual_df)

    def test_el_ciclo_completo_reproduce_el_alcance(self, normativa_df, manual_df):
        """filtrar → registrar → serializar → reanudar tiene que dar lo mismo."""
        normativa = filtrar_articulos(normativa_df, doc_ids=[DOC_LEY], secciones=["Título II"])
        manual = filtrar_secciones(manual_df, jerarquias=["4", "5"])
        scope = RunScope.desde_dataframes(normativa, manual)

        reanudado = RunScope.from_json(scope.to_json())
        n2, m2 = reanudado.aplicar_a(normativa_df, manual_df)
        pd.testing.assert_frame_equal(n2, normativa)
        pd.testing.assert_frame_equal(m2, manual)
        assert reanudado.huella() == scope.huella()

    def test_sin_element_id_falla_al_reanudar_por_ids(self, manual_df):
        scope = RunScope(articulos=["a1"])
        with pytest.raises(ValueError, match="element_id"):
            scope.aplicar_a(pd.DataFrame([{"otra": "cosa"}]), manual_df)

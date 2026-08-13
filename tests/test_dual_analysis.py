"""Ítem 6 — análisis en doble vía.

La Vía 1 sola no puede detectar un artículo huérfano: si ninguna sección lo recupera,
simplemente no aparece, y un artículo que nadie analizó es indistinguible de uno que no
existe. La brecha se ve desde el otro lado — ese es el punto del ítem, y la premisa no
negociable del Bloque A.
"""
from __future__ import annotations


from src.dual import CacheGrading, ComparisonBundle, run_dual
from src.llm_grader import AdopcionResult
from tests.fixtures import COBERTURA_ESPERADA, FakeGrader, FakeIndex


class _ManualIndexFalso:
    """Índice inverso de prueba: devuelve las secciones que se le programen por artículo."""

    def __init__(self, manual_df, plan=None):
        self.manual_df = manual_df
        self.plan = plan or {}
        self.llamadas = 0

    def buscar_secciones(self, texto, top_k=5, min_score=0.30):
        self.llamadas += 1
        ids = self.plan.get(texto, [])
        filas = self.manual_df[self.manual_df["chunk_id"].isin(ids)]
        return [{**r, "similarity": 0.8} for r in filas.to_dict("records")]


class _GraderDual(FakeGrader):
    """FakeGrader + la Vía 2, con contador propio."""

    def __init__(self, adopcion=None, **kw):
        super().__init__(**kw)
        self.adopcion = adopcion or {}
        self.llamadas_adopcion = 0

    def analizar_adopcion(self, articulo, secciones):
        self.llamadas_adopcion += 1
        if not secciones:
            return AdopcionResult(
                nivel_adopcion="no_cubierto",
                analisis_adopcion="ninguna sección lo aborda",
                brechas=["no cubierto"],
            )
        nivel = self.adopcion.get(articulo.get("numero"), "cubierto")
        return AdopcionResult(
            nivel_adopcion=nivel,
            analisis_adopcion="determinista",
            secciones_relevantes=[s.get("jerarquia", "") for s in secciones],
        )


def _correr(normativa_df, manual_df, plan_v1=None, plan_v2=None, adopcion=None):
    from src.comparator import DocumentComparator

    indice = FakeIndex(normativa_df=normativa_df, plan=plan_v1 or {})
    grader = _GraderDual(adopcion=adopcion)
    comparador = DocumentComparator(normativa_index=indice, llm_grader=grader)
    manual_index = _ManualIndexFalso(manual_df, plan_v2 or {})
    bundle = run_dual(
        comparador=comparador, manual_index=manual_index,
        manual_df=manual_df, normativa_df=normativa_df,
    )
    return bundle, grader, manual_index


class TestLasDosVistas:

    def test_produce_ambas_vistas_y_la_cobertura(self, normativa_df, manual_df):
        bundle, _, _ = _correr(normativa_df, manual_df)
        assert isinstance(bundle, ComparisonBundle)
        assert len(bundle.vista_manual) == len(manual_df)
        assert not bundle.vista_normativa.empty
        assert 0.0 <= bundle.cobertura.porcentaje <= 1.0

    def test_la_via_2_recorre_los_articulos_no_las_secciones(self, normativa_df, manual_df):
        """Su unidad de resultado es el artículo: si recorriera secciones, un artículo
        huérfano nunca aparecería."""
        _, grader, _ = _correr(normativa_df, manual_df)
        sustantivos = normativa_df[(normativa_df["tipo_elemento"] == "articulo")
                                   & (~normativa_df["es_referencia"])]
        assert grader.llamadas_adopcion == len(sustantivos)

    def test_excluye_las_referencias_del_preambulo(self, normativa_df, manual_df):
        """Contarlas como sin cobertura inflaría la brecha con artículos que nadie cumple."""
        bundle, _, _ = _correr(normativa_df, manual_df)
        assert bundle.cobertura.total_articulos == COBERTURA_ESPERADA["articulos_sustantivos"]


class TestArticuloHuerfano:
    """El caso que la Vía 1 sola no puede ver."""

    def test_un_articulo_sin_secciones_sale_no_cubierto(self, normativa_df, manual_df):
        bundle, _, _ = _correr(normativa_df, manual_df)   # sin plan: nada recupera nada
        assert not bundle.cobertura.completa
        assert len(bundle.cobertura.sin_cobertura) == bundle.cobertura.total_articulos

    def test_dispara_la_alerta_de_cobertura(self, normativa_df, manual_df):
        bundle, _, _ = _correr(normativa_df, manual_df)
        alerta = bundle.alerta_cobertura
        assert alerta is not None
        assert "no están cubiertos" in alerta and "%" in alerta

    def test_sin_alerta_cuando_la_cobertura_es_total(self, normativa_df, manual_df):
        arts = normativa_df[(normativa_df["tipo_elemento"] == "articulo")
                            & (~normativa_df["es_referencia"])]
        plan_v2 = {r["embed_text"]: [manual_df.iloc[0]["chunk_id"]]
                   for _, r in arts.iterrows()}
        bundle, _, _ = _correr(normativa_df, manual_df, plan_v2=plan_v2)
        assert bundle.cobertura.completa
        assert bundle.alerta_cobertura is None


class TestCosteDeLLM:
    """DoD: las llamadas deben ser |secciones| + |artículos|, no el producto (S3)."""

    def test_el_coste_es_la_suma_no_el_producto(self, normativa_df, manual_df):
        _, grader, _ = _correr(normativa_df, manual_df)
        sustantivos = len(normativa_df[(normativa_df["tipo_elemento"] == "articulo")
                                       & (~normativa_df["es_referencia"])])
        total = grader.llamadas_grade + grader.llamadas_adopcion
        assert total == len(manual_df) + sustantivos, (
            f"{total} llamadas cuando debían ser {len(manual_df)} + {sustantivos}"
        )
        assert total < len(manual_df) * sustantivos

    def test_la_cache_registra_los_aciertos(self, normativa_df, manual_df):
        art = normativa_df.iloc[0]
        plan_v1 = {r["embed_text"]: [art["element_id"]] for _, r in manual_df.iterrows()}
        plan_v2 = {art["embed_text"]: [manual_df.iloc[0]["chunk_id"]]}
        bundle, _, _ = _correr(normativa_df, manual_df, plan_v1=plan_v1, plan_v2=plan_v2)
        assert bundle.metadatos["cache_tamano"] > 0


class TestSeccionQueCubreDosNormas:
    """El caso N:N que el corpus construye a propósito."""

    def test_las_aristas_conservan_las_dos_normativas(self, normativa_df, manual_df):
        jerarquia, esperados = COBERTURA_ESPERADA["seccion_multinorma"]
        seccion = manual_df[manual_df["jerarquia"] == jerarquia].iloc[0]
        ids = [normativa_df[(normativa_df["doc_id"] == d)
                            & (normativa_df["numero"] == n)].iloc[0]["element_id"]
               for d, n in esperados]

        bundle, _, _ = _correr(
            normativa_df, manual_df, plan_v1={seccion["embed_text"]: ids},
        )
        docs = {e.articulo_doc_id for e in bundle.links.por_seccion(seccion["chunk_id"])}
        assert {d for d, _ in esperados} <= docs


class TestConsolidacionEntreVias:

    def test_las_dos_vias_escriben_en_la_misma_tabla(self, normativa_df, manual_df):
        """Si cada vía llevara su tabla, la cobertura de una no vería las aristas de la
        otra y el porcentaje saldría mal."""
        art = normativa_df.iloc[0]
        sec = manual_df.iloc[0]
        bundle, _, _ = _correr(
            normativa_df, manual_df,
            plan_v1={sec["embed_text"]: [art["element_id"]]},
            plan_v2={art["embed_text"]: [sec["chunk_id"]]},
        )
        enlaces = bundle.links.por_articulo(art["element_id"])
        combinados = [e for e in enlaces if len(e.origenes) > 1]
        assert combinados, "las dos vías no fusionaron su arista común"


class TestCacheGrading:

    def test_cuenta_aciertos_y_fallos(self):
        c = CacheGrading()
        assert c.obtener("a", "s") is None and c.fallos == 1
        c.guardar("a", "s", {"relevante": True})
        assert c.obtener("a", "s") is not None and c.aciertos == 1

    def test_no_sobrescribe_un_veredicto_ya_guardado(self):
        """El primero gana: re-graduar la misma pareja daría un resultado dependiente
        del orden de las vías."""
        c = CacheGrading()
        c.guardar("a", "s", {"v": 1})
        c.guardar("a", "s", {"v": 2})
        assert c.obtener("a", "s")["v"] == 1

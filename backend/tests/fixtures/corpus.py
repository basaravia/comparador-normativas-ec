"""Mini-corpus sintético: dos normativas y un manual, con los casos límite del plan.

Es material **inventado**. No procede de ningún documento real ni de ningún cliente, y esa
es la razón de que exista: la suite tiene que poder correr en cualquier máquina y en CI sin
depender de `document_test/`, que está fuera de git por confidencialidad.

Casos límite que el corpus construye a propósito (§ Ola 0 del plan):

  · **Artículo huérfano** — `LEY-A` art. 12 (continuidad del negocio) no lo cubre ninguna
    sección del manual. Es el caso que la Vía 2 debe marcar como `no_cubierto` y que dispara
    la alerta de cobertura < 100 %.

  · **Sección que satisface artículos de dos normas** — la sección 4.1 del manual habla de
    debida diligencia, que regulan a la vez `LEY-A` art. 8 y `RES-B` art. 3. Es el caso que
    obliga a que la relación sea N:N y no 1:N.

  · **Referencia léxica cruzada** — ambas normativas tienen un **artículo 5**, y la sección
    2.2 del manual cita "Art. 5" sin decir de cuál. Con `lexical_scan()` tal como está hoy
    (`src/search_engine.py`, defecto 2 de §2.2), esa cita matchea los dos y genera una arista
    falsa. Es la prueba de regresión de esa corrección.

  · **Sección sin norma aplicable** — la sección 7.1 (código de vestimenta) no tiene norma
    que le aplique. Distinto de "incumple": es `no_aplica` legítimo, y no debe confundirse
    con el `no_aplica` que hoy produce un fallo técnico (ítem 1).
"""
from __future__ import annotations

import pandas as pd

DOC_LEY = "LEY-A-2026.pdf"
DOC_RES = "RES-B-2026.pdf"
DOC_MANUAL = "MANUAL-INTERNO.pdf"


def _articulo(
    doc_id: str,
    orden: int,
    numero: str,
    encabezado: str,
    contenido: str,
    seccion: str = "",
    tipo_elemento: str = "articulo",
    tipo_bloque: str = "articulado",
    es_referencia: bool = False,
) -> dict:
    return {
        "element_id": f"{doc_id}_{orden:04d}",
        "doc_id": doc_id,
        "fuente": doc_id,
        "orden": orden,
        "numero": numero,
        "encabezado": encabezado,
        "contenido": contenido,
        "texto": f"{encabezado}. {contenido}",
        "seccion": seccion,
        "tipo_elemento": tipo_elemento,
        "tipo_bloque": tipo_bloque,
        "es_referencia": es_referencia,
        "posicion": orden * 1000,
        "embed_text": f"Artículo {numero}. {encabezado}. {contenido}",
        "titulo_norma": "Ley A de prevención y control" if doc_id == DOC_LEY
                        else "Resolución B sobre debida diligencia",
        "tipo_norma": "ley" if doc_id == DOC_LEY else "resolucion",
        "fecha": "2026-01-15",
    }


def normativa_ley() -> pd.DataFrame:
    """LEY-A: seis artículos. El 12 queda deliberadamente sin cobertura."""
    filas = [
        _articulo(DOC_LEY, 1, "1", "Ámbito de aplicación",
                  "Las disposiciones de esta ley aplican a las entidades del sistema "
                  "financiero nacional que capten recursos del público.",
                  seccion="Título I > Disposiciones generales"),
        _articulo(DOC_LEY, 2, "5", "Registro de operaciones",
                  "Las entidades mantendrán un registro de las operaciones que superen "
                  "los umbrales establecidos, conservándolo por diez años.",
                  seccion="Título I > Disposiciones generales"),
        _articulo(DOC_LEY, 3, "8", "Debida diligencia del cliente",
                  "Las entidades aplicarán procedimientos de debida diligencia para "
                  "identificar y verificar la identidad de sus clientes antes de "
                  "iniciar la relación comercial.",
                  seccion="Título II > Obligaciones"),
        _articulo(DOC_LEY, 4, "9", "Capacitación del personal",
                  "Las entidades capacitarán anualmente a su personal en las materias "
                  "reguladas por esta ley, dejando constancia documental.",
                  seccion="Título II > Obligaciones"),
        # ── artículo huérfano: ninguna sección del manual lo cubre ──
        _articulo(DOC_LEY, 5, "12", "Continuidad del negocio",
                  "Las entidades contarán con un plan de continuidad que garantice la "
                  "prestación de servicios críticos ante eventos de interrupción, "
                  "sometido a pruebas anuales.",
                  seccion="Título III > Gestión de riesgos"),
        # ── referencia, no obligación sustantiva: el filtro es_referencia debe excluirla ──
        _articulo(DOC_LEY, 6, "20", "Remisión normativa",
                  "En lo no previsto se aplicará lo dispuesto en el artículo 5 de la "
                  "Resolución B y demás normas conexas.",
                  seccion="Disposiciones finales",
                  tipo_bloque="disposiciones", es_referencia=True),
    ]
    return pd.DataFrame(filas)


def normativa_resolucion() -> pd.DataFrame:
    """RES-B: cuatro artículos. Su artículo 5 colisiona con el de LEY-A."""
    filas = [
        _articulo(DOC_RES, 1, "3", "Procedimientos de identificación",
                  "El sujeto obligado documentará los procedimientos de identificación "
                  "del cliente y del beneficiario final, actualizándolos periódicamente.",
                  seccion="Capítulo I"),
        # ── colisión léxica: LEY-A también tiene un artículo 5 ──
        _articulo(DOC_RES, 2, "5", "Reporte de operaciones inusuales",
                  "El sujeto obligado reportará las operaciones inusuales e "
                  "injustificadas dentro de los plazos establecidos por el organismo "
                  "de control.",
                  seccion="Capítulo I"),
        _articulo(DOC_RES, 3, "7", "Conservación de expedientes",
                  "Los expedientes de debida diligencia se conservarán por un plazo "
                  "mínimo de diez años contados desde el fin de la relación comercial.",
                  seccion="Capítulo II"),
        _articulo(DOC_RES, 4, "11", "Auditoría interna",
                  "La auditoría interna evaluará anualmente la eficacia del sistema de "
                  "prevención y remitirá sus conclusiones al directorio.",
                  seccion="Capítulo II"),
    ]
    return pd.DataFrame(filas)


def normativa_df() -> pd.DataFrame:
    """Las dos normativas concatenadas — el escenario multi-norma del ítem 5."""
    return pd.concat([normativa_ley(), normativa_resolucion()], ignore_index=True)


def _seccion(orden: int, jerarquia: str, titulo: str, texto: str) -> dict:
    return {
        "chunk_id": f"{DOC_MANUAL.replace('.pdf', '')}_{orden:04d}",
        "doc_id": DOC_MANUAL,
        "fuente": DOC_MANUAL,
        "pagina_inicio": orden,
        "pagina_fin": orden,
        "jerarquia": jerarquia,
        "titulo_seccion": titulo,
        "texto": texto,
        "embed_text": f"{jerarquia}. {texto}",
    }


def manual_df() -> pd.DataFrame:
    """Ocho secciones del manual interno."""
    filas = [
        _seccion(1, "1. Objeto y alcance", "Objeto y alcance",
                 "Este manual establece los lineamientos aplicables a las operaciones "
                 "de la entidad y al personal que interviene en ellas."),
        # ── cita "Art. 5" sin decir de qué norma: colisión léxica entre LEY-A y RES-B ──
        _seccion(2, "2.2 Registro y conservación", "Registro y conservación",
                 "Conforme al Art. 5, se mantiene el registro de operaciones por un "
                 "período de diez años en el repositorio documental."),
        _seccion(3, "3.1 Reporte de inusualidades", "Reporte de inusualidades",
                 "Las operaciones que presenten señales de alerta se reportan al área "
                 "de cumplimiento dentro de las 48 horas siguientes a su detección."),
        # ── cubre a la vez LEY-A art. 8 y RES-B art. 3: obliga a N:N ──
        _seccion(4, "4.1 Conocimiento del cliente", "Conocimiento del cliente",
                 "Antes de iniciar la relación comercial se verifica la identidad del "
                 "cliente y se identifica al beneficiario final, documentando el "
                 "procedimiento en el expediente."),
        _seccion(5, "5.1 Formación anual", "Formación anual",
                 "El personal recibe formación anual en materia de prevención, con "
                 "registro de asistencia y evaluación de aprovechamiento."),
        _seccion(6, "6.1 Revisión independiente", "Revisión independiente",
                 "La función de auditoría interna revisa periódicamente la eficacia de "
                 "los controles descritos en este manual."),
        # ── sin norma aplicable: no_aplica legítimo, no un fallo técnico ──
        _seccion(7, "7.1 Código de vestimenta", "Código de vestimenta",
                 "El personal que atiende público mantiene una presentación acorde a "
                 "los lineamientos de imagen institucional."),
        # ── cumplimiento parcial: menciona el expediente pero no el plazo de diez años ──
        _seccion(8, "8.1 Expedientes de clientes", "Expedientes de clientes",
                 "Los expedientes de clientes se archivan en el sistema de gestión "
                 "documental al cierre de la relación comercial."),
    ]
    return pd.DataFrame(filas)


# Cobertura esperada, para que las pruebas afirmen contra un valor conocido en vez de
# recalcularlo con la misma lógica que están probando.
COBERTURA_ESPERADA = {
    "articulos_sustantivos": 9,          # 10 menos el art. 20 de LEY-A, que es referencia
    "articulos_sin_cobertura": [(DOC_LEY, "12")],
    "secciones_sin_norma": ["7.1 Código de vestimenta"],
    "seccion_multinorma": ("4.1 Conocimiento del cliente", [(DOC_LEY, "8"), (DOC_RES, "3")]),
    "numero_ambiguo": "5",               # existe en las dos normativas
}

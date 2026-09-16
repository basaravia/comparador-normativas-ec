#!/usr/bin/env python3
"""Genera tres manuales de control interno MOCK (datos ficticios, despersonalizados).

Sirven para validar que el comparador distinga los tres veredictos del pipeline:
cumple / parcial / omision. Cada manual tiene un perfil de cobertura distinto
frente a las obligaciones reales de la Ley Orgánica para Reprimir y Prevenir el
Lavado de Activos y la Financiación del Terrorismo (Arts. 31-61), que es la norma
que vive en Normativa2026/.

  A · ALTO CUMPLIMIENTO  → cubre la obligación con el detalle verificable
                            (plazos, umbrales, periodicidades, responsables).
  B · CUMPLIMIENTO PARCIAL → nombra el tema pero sin el detalle que la norma exige.
  C · CON OMISIONES        → solo cubre temas periféricos; omite el núcleo LA/FT.

NADA aquí es real: entidad ficticia, códigos ficticios, sin nombres de personas.
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

SALIDA = Path.home() / "proyectos_documentos_normativos/comparador-normativas-ec/document_test"

ENTIDAD = "ENTIDAD FINANCIERA MODELO S.A."
AVISO = (
    "DOCUMENTO DE PRUEBA — DATOS FICTICIOS. No corresponde a ninguna entidad real. "
    "Generado para validar el pipeline de comparación normativa."
)

# ── estilos ──────────────────────────────────────────────────────────────────

_ss = getSampleStyleSheet()
H0 = ParagraphStyle("H0", parent=_ss["Title"], fontSize=17, leading=21, alignment=TA_CENTER)
H1 = ParagraphStyle("H1", parent=_ss["Heading1"], fontSize=12.5, leading=15,
                    spaceBefore=14, spaceAfter=6, textColor=colors.HexColor("#1a3a5c"))
H2 = ParagraphStyle("H2", parent=_ss["Heading2"], fontSize=11, leading=13.5,
                    spaceBefore=10, spaceAfter=4, textColor=colors.HexColor("#2c5282"))
BODY = ParagraphStyle("BODY", parent=_ss["BodyText"], fontSize=9.5, leading=13.5,
                      alignment=TA_JUSTIFY, spaceAfter=6)
SMALL = ParagraphStyle("SMALL", parent=_ss["BodyText"], fontSize=8, leading=10.5,
                       textColor=colors.HexColor("#555555"))
TOC = ParagraphStyle("TOC", parent=_ss["BodyText"], fontSize=9, leading=13)


def _portada(titulo: str, codigo: str, version: str, perfil: str) -> list:
    tabla = Table(
        [
            ["Código del documento", codigo],
            ["Versión", version],
            ["Fecha de aprobación", "15/01/2026"],
            ["Elaborado por", "Unidad de Cumplimiento"],
            ["Revisado por", "Comité de Cumplimiento"],
            ["Aprobado por", "Directorio"],
            ["Próxima revisión", "Anual"],
            ["Clasificación", "Uso interno — EJEMPLAR DE PRUEBA"],
        ],
        colWidths=[6 * cm, 9.5 * cm],
    )
    tabla.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#9fb3c8")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef3f8")),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return [
        Spacer(1, 2.2 * cm),
        Paragraph(ENTIDAD, H0),
        Spacer(1, 0.5 * cm),
        Paragraph(titulo, H0),
        # El perfil esperado (cumple/parcial/omisión) NO se imprime en el PDF a
        # propósito: el texto del manual llega al prompt del LLM, y anunciar ahí el
        # veredicto esperado contaminaría la validación — el modelo estaría leyendo
        # la respuesta en vez de deducirla. Tampoco va en el nombre del archivo, para
        # que la revisión humana de los resultados también sea ciega. El mapeo
        # archivo → perfil vive únicamente en document_test/LEEME-MANUALES-MOCK.md.
        Spacer(1, 1.4 * cm),
        tabla,
        Spacer(1, 1.6 * cm),
        Paragraph(AVISO, SMALL),
        PageBreak(),
    ]


def _indice(secciones: list) -> list:
    flujo = [Paragraph("ÍNDICE", H1), Spacer(1, 0.3 * cm)]
    for nivel, num, titulo, _ in secciones:
        sangria = 0 if nivel == 1 else 18
        estilo = ParagraphStyle(f"toc{nivel}", parent=TOC, leftIndent=sangria)
        flujo.append(Paragraph(f"{num}&nbsp;&nbsp;&nbsp;{titulo}", estilo))
    flujo.append(PageBreak())
    return flujo


def construir(nombre_archivo: str, titulo: str, codigo: str, version: str,
              perfil: str, secciones: list) -> Path:
    SALIDA.mkdir(parents=True, exist_ok=True)
    ruta = SALIDA / nombre_archivo
    doc = SimpleDocTemplate(
        str(ruta), pagesize=A4,
        leftMargin=2.4 * cm, rightMargin=2.4 * cm,
        topMargin=2.2 * cm, bottomMargin=2.2 * cm,
        title=titulo, author=ENTIDAD, subject=AVISO,
    )
    flujo = _portada(titulo, codigo, version, perfil)
    flujo += _indice(secciones)
    for nivel, num, tit, parrafos in secciones:
        flujo.append(Paragraph(f"{num}&nbsp;&nbsp;{tit}", H1 if nivel == 1 else H2))
        for p in parrafos:
            flujo.append(Paragraph(p, BODY))
    doc.build(flujo)
    return ruta


# ─────────────────────────────────────────────────────────────────────────────
# MANUAL A · ALTO CUMPLIMIENTO
# ─────────────────────────────────────────────────────────────────────────────

SECCIONES_A = [
    (1, "I.", "INTRODUCCIÓN", [
        "El presente manual establece las políticas, procedimientos y controles internos que la entidad aplica para la administración del riesgo de lavado de activos, financiamiento del terrorismo y financiamiento de la proliferación de armas de destrucción masiva (en adelante, LA/FT/FP). Su contenido es de observancia obligatoria para todo el personal, directivos y terceros vinculados contractualmente.",
        "El manual se sustenta en un enfoque basado en riesgo, conforme al cual la intensidad de las medidas de debida diligencia se gradúa según el nivel de riesgo identificado para cada cliente, producto, canal de distribución y jurisdicción.",
    ]),
    (1, "II.", "OBJETIVOS", [
        "Objetivo principal: prevenir que los productos y servicios de la entidad sean utilizados como instrumento para el ocultamiento, manejo, inversión o aprovechamiento de recursos provenientes de actividades ilícitas, o para canalizar recursos hacia la comisión de actos terroristas o la proliferación de armas de destrucción masiva.",
        "Objetivos específicos: (i) implementar un programa integral de prevención documentado y aprobado por el Directorio; (ii) mantener una metodología de identificación, evaluación y mitigación de riesgos actualizada; (iii) aplicar procedimientos de debida diligencia diferenciados; (iv) detectar y reportar oportunamente operaciones inusuales e injustificadas; y (v) mantener una cultura organizacional de cumplimiento mediante capacitación permanente.",
    ]),
    (1, "III.", "ALCANCE Y BASE NORMATIVA", [
        "El alcance comprende todas las líneas de negocio, agencias, canales digitales y subsidiarias de la entidad, sin excepción. Las disposiciones aplican a la totalidad de relaciones comerciales, sean permanentes u ocasionales.",
        "La entidad ha implementado el programa de prevención a nivel de todo el grupo financiero al que pertenece, incluyendo políticas para el intercambio de información entre las empresas del grupo para propósitos de gestión del riesgo LA/FT, con las salvaguardas de confidencialidad correspondientes.",
    ]),
    (1, "IV.", "ESTRUCTURA ORGANIZACIONAL Y RESPONSABILIDADES", [
        "El Directorio aprueba el manual y sus actualizaciones, conoce los informes trimestrales del Oficial de Cumplimiento y asigna los recursos humanos y tecnológicos necesarios para la ejecución del programa.",
        "El Comité de Cumplimiento sesiona mensualmente, evalúa los casos escalados por la Unidad de Cumplimiento y decide sobre el inicio, mantenimiento o terminación de relaciones comerciales de alto riesgo. Sus decisiones constan en actas numeradas secuencialmente.",
    ]),
    (2, "4.1", "Oficial de Cumplimiento", [
        "El Oficial de Cumplimiento es un funcionario de nivel gerencial, con dedicación exclusiva, independencia de las áreas de negocio y reporte directo al Directorio. Cuenta con acceso irrestricto a todas las bases de datos, expedientes y sistemas transaccionales de la entidad.",
        "Le corresponde: vigilar la ejecución del programa de prevención; analizar las alertas generadas por el sistema de monitoreo; suscribir y remitir los reportes a la Unidad de Análisis Financiero y Económico (UAFE); y presentar informes trimestrales al Directorio sobre la gestión del riesgo LA/FT.",
    ]),
    (1, "V.", "METODOLOGÍA DE ADMINISTRACIÓN DEL RIESGO", [
        "La entidad mantiene una metodología documentada para identificar, evaluar, mitigar y monitorear los riesgos de LA/FT/FP, que considera como mínimo los siguientes factores: tipo de cliente, actividad económica, ubicación geográfica, productos y servicios contratados, canales de distribución y volumen transaccional.",
        "La evaluación de riesgo institucional se actualiza al menos una vez al año, y de manera extraordinaria cuando se lancen nuevos productos, se incorporen nuevas tecnologías o se identifiquen cambios materiales en el perfil de riesgo. Los resultados se documentan en un informe formal, se mantienen a disposición del organismo de control y se comunican al Directorio.",
        "Las medidas de mitigación son proporcionales al riesgo identificado: los clientes clasificados en riesgo alto son sometidos a debida diligencia ampliada y a monitoreo reforzado, mientras que los de riesgo bajo pueden ser objeto de medidas simplificadas conforme a la sección 5.2.",
    ]),
    (2, "5.1", "Conocimiento del cliente y debida diligencia", [
        "Antes de establecer cualquier relación comercial, la entidad identifica plenamente al cliente y verifica su identidad sobre la base de documentos, datos o información obtenida de fuentes confiables e independientes. La verificación se completa antes del inicio de la relación; excepcionalmente puede completarse durante el establecimiento, siempre que los riesgos se gestionen eficazmente y la operación no supere los umbrales definidos por la Unidad de Cumplimiento.",
        "La debida diligencia contempla como mínimo: identificación y verificación del cliente; identificación del beneficiario final; comprensión del propósito y naturaleza prevista de la relación comercial; y determinación del perfil transaccional esperado, que sirve de base para el monitoreo posterior.",
        "Está prohibida la apertura o el mantenimiento de cuentas anónimas, cifradas o bajo nombres manifiestamente ficticios. Todas las cuentas y operaciones se mantienen de forma nominativa.",
    ]),
    (2, "5.2", "Debida diligencia simplificada", [
        "Procede la aplicación de medidas simplificadas únicamente cuando se ha determinado y documentado un riesgo bajo, y siempre que no exista sospecha de LA/FT. En ningún caso se aplican medidas simplificadas a clientes clasificados en riesgo alto, personas expuestas políticamente, ni relaciones vinculadas a jurisdicciones de alto riesgo.",
        "Las medidas simplificadas no eximen de la identificación del cliente ni del beneficiario final; únicamente permiten reducir la frecuencia de actualización documental y la intensidad del monitoreo, decisión que debe constar motivada en el expediente.",
    ]),
    (2, "5.3", "Beneficiario final", [
        "Tratándose de personas jurídicas o estructuras jurídicas, la entidad identifica a las personas naturales que, en última instancia, posean o controlen directa o indirectamente una participación igual o superior al veinticinco por ciento (25%) del capital social o de los derechos de voto, o que ejerzan el control efectivo por otros medios.",
        "Cuando ninguna persona natural alcance dicho umbral o existan dudas sobre el control efectivo, se identifica a la persona natural que ejerza la administración o dirección superior de la estructura. La determinación del beneficiario final se documenta mediante declaración suscrita por el cliente y se contrasta contra fuentes públicas de información societaria.",
        "En encargos fiduciarios se identifica al constituyente, al fiduciario, a los beneficiarios y a cualquier otra persona natural que ejerza control efectivo sobre el patrimonio autónomo.",
    ]),
    (2, "5.4", "Personas expuestas políticamente (PEP)", [
        "La entidad mantiene procedimientos y sistemas automatizados para determinar si el cliente, el beneficiario final o alguno de sus vinculados ostenta o ha ostentado la condición de persona expuesta políticamente, sea nacional o extranjera, así como sus cónyuges, familiares hasta el segundo grado de consanguinidad y colaboradores cercanos.",
        "El inicio o continuidad de una relación comercial con una PEP requiere la aprobación expresa de la alta gerencia, la adopción de medidas razonables para establecer el origen de los fondos y del patrimonio, y la sujeción a monitoreo reforzado y continuo. La condición de PEP se revisa de manera permanente y se actualiza al menos semestralmente.",
    ]),
    (2, "5.5", "Validación en listas de control y programas de sanciones", [
        "Todo cliente, proveedor, colaborador y contraparte es validado contra las listas de control nacionales e internacionales, incluidas las emanadas de las resoluciones del Consejo de Seguridad de las Naciones Unidas, antes del inicio de la relación y con periodicidad diaria durante su vigencia, mediante cotejo automatizado.",
        "Ante una coincidencia positiva confirmada, se procede al congelamiento inmediato de fondos o activos sin demora ni aviso previo al cliente, se abstiene la entidad de ejecutar la operación y se comunica el hecho a la autoridad competente dentro del término legal aplicable.",
    ]),
    (2, "5.6", "Países y jurisdicciones de alto riesgo", [
        "La entidad considera como factor de riesgo geográfico agravado las operaciones vinculadas a países señalados por organismos internacionales como de alto riesgo o sujetos a monitoreo intensificado, así como a paraísos fiscales y jurisdicciones sujetas a programas de sanciones.",
        "Las relaciones comerciales con contrapartes domiciliadas en tales jurisdicciones son sometidas a debida diligencia ampliada obligatoria y requieren autorización del Comité de Cumplimiento.",
    ]),
    (2, "5.7", "Debida diligencia continua y monitoreo transaccional", [
        "La entidad realiza un escrutinio permanente de las operaciones efectuadas a lo largo de la relación comercial, a fin de verificar que sean consistentes con el conocimiento que se tiene del cliente, su actividad económica, su perfil de riesgo y el origen declarado de sus fondos.",
        "El sistema de monitoreo genera alertas automáticas por desviaciones respecto del perfil transaccional esperado, fraccionamiento, operaciones con jurisdicciones de riesgo y patrones atípicos. Cada alerta es analizada y documentada, y su cierre requiere justificación motivada registrada en el expediente electrónico.",
        "La información y documentación del cliente se mantiene actualizada; para clientes de riesgo alto la actualización es anual, para riesgo medio bienal y para riesgo bajo cada tres años.",
    ]),
    (2, "5.8", "Imposibilidad de completar la debida diligencia", [
        "Cuando la entidad no pueda cumplir con las medidas de debida diligencia exigidas, no iniciará la relación comercial, no ejecutará la operación solicitada y procederá a terminar la relación existente, evaluando en todos los casos la pertinencia de presentar un reporte de operación sospechosa a la UAFE.",
    ]),
    (2, "5.9", "Transferencias electrónicas de fondos", [
        "Toda transferencia electrónica nacional o transfronteriza incluye y conserva la información requerida del ordenante y del beneficiario: nombres completos, número de cuenta o identificador único de la operación, número de documento de identificación y dirección. La entidad no ejecuta transferencias que carezcan de dicha información.",
        "Las transferencias entrantes con información incompleta del ordenante son retenidas para análisis por la Unidad de Cumplimiento antes de su acreditación.",
    ]),
    (2, "5.10", "Delegación en terceros", [
        "La entidad puede delegar en otros sujetos obligados la identificación y verificación del cliente y del beneficiario final, conservando en todo caso la responsabilidad final por el cumplimiento. La delegación exige contrato escrito, acceso inmediato a la información obtenida y evidencia de que el tercero se encuentra regulado y supervisado.",
        "No se delega en terceros domiciliados en jurisdicciones de alto riesgo.",
    ]),
    (1, "VI.", "CONSERVACIÓN Y CUSTODIA DE LA INFORMACIÓN", [
        "La entidad conserva los registros de identificación de clientes, expedientes, correspondencia comercial y soportes de las operaciones por un período mínimo de diez (10) años contados desde la finalización de la relación comercial o desde la ejecución de la operación ocasional, lo que ocurra al final.",
        "Los registros se mantienen en medios que garanticen su integridad, disponibilidad y trazabilidad, y permiten la reconstrucción individual de cada operación. La información es puesta a disposición de las autoridades competentes dentro de los plazos requeridos.",
    ]),
    (1, "VII.", "REPORTES A LA UNIDAD DE ANÁLISIS FINANCIERO Y ECONÓMICO", [
        "La entidad cuenta con código de registro vigente ante la UAFE y mantiene actualizados los datos de su Oficial de Cumplimiento ante dicho organismo.",
        "Reporte de operaciones inusuales e injustificadas: cuando del análisis se desprenda que una operación carece de justificación económica o financiera aparente, el Oficial de Cumplimiento remite el reporte correspondiente a la UAFE dentro del término de cuatro (4) días contados desde la fecha en que se concluyó el análisis que calificó la operación como tal.",
        "Reporte de operaciones que igualan o superan el umbral legal: se remiten mensualmente dentro de los quince (15) primeros días del mes siguiente, conforme al formato e instructivo vigente emitido por la UAFE.",
        "La entidad atiende los requerimientos de información formulados por la UAFE y demás autoridades competentes dentro de los términos establecidos, sin oponer reserva bancaria.",
    ]),
    (1, "VIII.", "RESERVA Y PROHIBICIÓN DE REVELACIÓN", [
        "Los directivos, funcionarios y empleados de la entidad no pueden revelar al cliente ni a terceros que se ha presentado un reporte de operación sospechosa, que la operación se encuentra en análisis, ni que existe un requerimiento de información de autoridad competente. El incumplimiento de esta prohibición constituye falta grave sujeta a sanción.",
        "Quienes presenten reportes de buena fe no incurren en responsabilidad civil, penal ni administrativa, aun cuando el análisis posterior no confirme la existencia del ilícito.",
    ]),
    (1, "IX.", "CONOCIMIENTO DEL EMPLEADO", [
        "La entidad aplica procedimientos de debida diligencia en la selección de personal, que incluyen verificación de antecedentes, validación de referencias laborales y consulta en listas de control. Los colaboradores suscriben anualmente una declaración patrimonial y una declaración de conflictos de interés.",
        "Se monitorean las cuentas de los colaboradores y las variaciones patrimoniales injustificadas, con reporte de excepciones al Comité de Cumplimiento.",
    ]),
    (1, "X.", "CAPACITACIÓN Y CULTURA DE CUMPLIMIENTO", [
        "Todo el personal recibe capacitación en prevención de LA/FT/FP al momento de su ingreso y, posteriormente, con periodicidad anual como mínimo. Los miembros del Directorio y la alta gerencia reciben capacitación específica sobre sus responsabilidades.",
        "La capacitación es evaluada mediante pruebas de conocimiento; la aprobación es requisito para el personal de áreas de contacto con clientes. Los registros de asistencia y calificación se conservan como evidencia.",
    ]),
    (1, "XI.", "AUDITORÍA Y EVALUACIÓN INDEPENDIENTE", [
        "Auditoría Interna evalúa anualmente la eficacia del programa de prevención, con alcance sobre la calidad de los expedientes, la efectividad del monitoreo y la oportunidad de los reportes. Los hallazgos se comunican al Comité de Auditoría y su remediación es objeto de seguimiento formal.",
        "Adicionalmente, un auditor externo independiente evalúa el sistema de prevención con la periodicidad que disponga la normativa aplicable.",
    ]),
    (1, "XII.", "INFRAESTRUCTURA TECNOLÓGICA Y SEGURIDAD DE LA INFORMACIÓN", [
        "La entidad dispone de herramientas informáticas que soportan la segmentación de clientes, el monitoreo transaccional basado en reglas y modelos, el cotejo automatizado contra listas de control y la generación de los reportes regulatorios.",
        "El acceso a la información del sistema de prevención está restringido por perfiles, es registrado en bitácoras de auditoría inalterables y está sujeto a las políticas institucionales de seguridad de la información y protección de datos personales.",
    ]),
    (1, "XIII.", "SEÑALES DE ALERTA", [
        "Constituyen señales de alerta, entre otras: operaciones fraccionadas para eludir umbrales de reporte; clientes que se niegan a proporcionar información sobre el origen de fondos o el beneficiario final; movimientos incompatibles con la actividad económica declarada; uso de terceros sin relación aparente; y operaciones con jurisdicciones de alto riesgo sin justificación comercial.",
        "La detección de una señal de alerta obliga al colaborador a documentarla y escalarla a la Unidad de Cumplimiento de manera inmediata, sin comunicar al cliente.",
    ]),
]

# ─────────────────────────────────────────────────────────────────────────────
# MANUAL B · CUMPLIMIENTO PARCIAL
# ─────────────────────────────────────────────────────────────────────────────

SECCIONES_B = [
    (1, "I.", "INTRODUCCIÓN", [
        "Este manual contiene las disposiciones generales que la entidad observa en materia de prevención de lavado de activos y financiamiento de delitos. Su aplicación corresponde a las áreas que mantienen contacto con clientes.",
        "La entidad reconoce la importancia de contar con controles adecuados y procura mantenerlos actualizados conforme a las mejores prácticas del sector.",
    ]),
    (1, "II.", "OBJETIVOS", [
        "Establecer lineamientos para evitar que la entidad sea utilizada para el lavado de activos o el financiamiento de actividades ilícitas, y promover una adecuada cultura de prevención entre los colaboradores.",
    ]),
    (1, "III.", "ALCANCE", [
        "Las disposiciones de este manual aplican a las agencias y a las áreas comerciales de la entidad. Las subsidiarias adoptarán sus propias políticas internas conforme a su naturaleza.",
    ]),
    (1, "IV.", "ESTRUCTURA Y RESPONSABILIDADES", [
        "El Directorio conoce anualmente los resultados de la gestión de cumplimiento. La Unidad de Cumplimiento es responsable de la ejecución de las actividades de prevención.",
    ]),
    (2, "4.1", "Oficial de Cumplimiento", [
        "La entidad ha designado un Oficial de Cumplimiento, quien es responsable de velar por la aplicación de este manual y de mantener comunicación con los organismos de control.",
        "El Oficial de Cumplimiento presenta informes a la administración sobre las actividades realizadas.",
    ]),
    (1, "V.", "GESTIÓN DE RIESGOS", [
        "La entidad aplica un enfoque basado en riesgo para la atención de sus clientes, considerando principalmente el tipo de cliente y su actividad económica.",
        "Los clientes son clasificados en niveles de riesgo, lo que permite orientar los esfuerzos de control hacia los casos de mayor exposición.",
    ]),
    (2, "5.1", "Conocimiento del cliente", [
        "Previo al establecimiento de la relación comercial se solicita al cliente la documentación de identificación correspondiente y se completa el formulario de vinculación establecido por la entidad.",
        "Se registra la información del cliente en el sistema institucional y se conforma el expediente respectivo. El área comercial es responsable de que la documentación esté completa al momento de la apertura.",
    ]),
    (2, "5.2", "Debida diligencia ampliada", [
        "Para los clientes que la entidad considere de mayor riesgo se aplican medidas adicionales de verificación, las cuales son determinadas por la Unidad de Cumplimiento según las circunstancias de cada caso.",
    ]),
    (2, "5.3", "Beneficiario final", [
        "Cuando el cliente sea una persona jurídica, se solicitará información respecto de sus accionistas y de quienes ejerzan su representación legal, dejando constancia en el expediente.",
    ]),
    (2, "5.4", "Personas expuestas políticamente", [
        "La entidad consulta si el cliente tiene la condición de persona expuesta políticamente al momento de la vinculación, y deja constancia de dicha consulta en el expediente del cliente.",
    ]),
    (2, "5.5", "Listas de control", [
        "La entidad realiza consultas en listas de control como parte del proceso de vinculación de clientes. Los resultados se archivan junto con la documentación del cliente.",
    ]),
    (2, "5.6", "Monitoreo de operaciones", [
        "La entidad cuenta con mecanismos de monitoreo que permiten identificar operaciones que se aparten del comportamiento habitual del cliente.",
        "Las situaciones detectadas son revisadas por la Unidad de Cumplimiento, que determina las acciones a seguir en cada caso.",
    ]),
    (2, "5.7", "Actualización de información", [
        "La información de los clientes es actualizada periódicamente conforme a los procedimientos internos definidos por la entidad.",
    ]),
    (1, "VI.", "CUSTODIA DE INFORMACIÓN", [
        "La entidad conserva la documentación de los clientes y los soportes de las operaciones por el tiempo que establezca la normativa aplicable, en archivos físicos y electrónicos bajo custodia del área responsable.",
    ]),
    (1, "VII.", "REPORTES A ORGANISMOS DE CONTROL", [
        "La entidad remite a la autoridad competente los reportes que le corresponden conforme a la normativa vigente. El Oficial de Cumplimiento es responsable de la preparación y envío de dichos reportes.",
        "Las operaciones que resulten inusuales son analizadas y, de confirmarse su carácter injustificado, son reportadas a la autoridad competente.",
    ]),
    (1, "VIII.", "CONFIDENCIALIDAD", [
        "La información relacionada con clientes y operaciones tiene carácter reservado y su manejo se sujeta a las políticas institucionales de seguridad de la información.",
    ]),
    (1, "IX.", "CONOCIMIENTO DEL EMPLEADO", [
        "La entidad verifica los antecedentes del personal durante el proceso de selección y mantiene los expedientes laborales actualizados.",
    ]),
    (1, "X.", "CAPACITACIÓN", [
        "La entidad desarrolla actividades de capacitación en materia de prevención dirigidas a su personal, conforme al plan anual aprobado por el área de Talento Humano.",
    ]),
    (1, "XI.", "AUDITORÍA", [
        "Auditoría Interna incluye en su plan anual revisiones sobre los procesos de cumplimiento, cuyos resultados son informados a la administración.",
    ]),
    (1, "XII.", "INFRAESTRUCTURA TECNOLÓGICA", [
        "La entidad dispone de sistemas informáticos que soportan la administración de la información de clientes y el registro de las operaciones.",
    ]),
    (1, "XIII.", "SEÑALES DE ALERTA", [
        "Se consideran situaciones que ameritan atención especial aquellas en las que el cliente presenta un comportamiento inusual o se niega a entregar información solicitada. Estas situaciones deben ser informadas a la Unidad de Cumplimiento.",
    ]),
]

# ─────────────────────────────────────────────────────────────────────────────
# MANUAL C · CON OMISIONES
# ─────────────────────────────────────────────────────────────────────────────

SECCIONES_C = [
    (1, "I.", "INTRODUCCIÓN", [
        "El presente documento describe la organización interna de la entidad y los lineamientos generales de conducta aplicables a sus colaboradores en el desarrollo de las actividades comerciales y operativas.",
    ]),
    (1, "II.", "OBJETIVO DEL MANUAL", [
        "Documentar la estructura organizacional, los canales de atención y las normas de conducta institucional, a fin de facilitar la inducción del personal y la estandarización de la operación diaria.",
    ]),
    (1, "III.", "ALCANCE", [
        "Este manual aplica a todas las áreas administrativas y operativas de la entidad, así como a su red de agencias.",
    ]),
    (1, "IV.", "ESTRUCTURA ORGANIZACIONAL", [
        "La entidad se organiza en tres vicepresidencias: Negocios, Operaciones y Administración. Cada vicepresidencia cuenta con gerencias de área que reportan al Comité Ejecutivo.",
        "El Directorio se reúne mensualmente y aprueba los lineamientos estratégicos institucionales.",
    ]),
    (2, "4.1", "Funciones de las áreas de negocio", [
        "Las áreas de negocio son responsables de la gestión comercial, la atención de clientes y el cumplimiento de las metas de colocación y captación establecidas en el presupuesto anual.",
    ]),
    (2, "4.2", "Funciones del área de operaciones", [
        "El área de operaciones ejecuta el procesamiento de las transacciones, la conciliación de cuentas y el soporte a la red de agencias.",
    ]),
    (1, "V.", "CÓDIGO DE ÉTICA Y CONDUCTA", [
        "Los colaboradores deben actuar con honestidad, diligencia y respeto en el trato con clientes, proveedores y compañeros de trabajo. Se prohíbe el uso de la información institucional para beneficio personal.",
        "Los conflictos de interés deben ser informados al superior jerárquico inmediato. La entidad mantiene un canal de denuncias para el reporte de conductas contrarias a este código.",
    ]),
    (1, "VI.", "ATENCIÓN AL CLIENTE", [
        "La entidad atiende a sus clientes en horarios establecidos y a través de canales presenciales y digitales. Los reclamos son registrados y atendidos dentro de los plazos definidos en el procedimiento de atención de reclamos.",
        "El personal de plataforma es responsable de recibir la documentación requerida para la apertura de productos y de registrarla en el sistema institucional.",
    ]),
    (1, "VII.", "GESTIÓN DOCUMENTAL", [
        "Los documentos generados en la operación son archivados por el área responsable conforme a la tabla de retención documental institucional. El archivo central administra la custodia de los expedientes físicos.",
    ]),
    (1, "VIII.", "TALENTO HUMANO", [
        "Los procesos de selección, contratación, evaluación de desempeño y desvinculación se rigen por el reglamento interno de trabajo y la normativa laboral aplicable.",
        "La entidad ejecuta un plan anual de capacitación orientado al desarrollo de competencias técnicas y de servicio.",
    ]),
    (1, "IX.", "INFRAESTRUCTURA TECNOLÓGICA", [
        "La entidad mantiene sistemas core bancarios, canales electrónicos y una infraestructura de respaldo que garantiza la continuidad de la operación. La administración de accesos se realiza mediante perfiles autorizados por los dueños de cada sistema.",
        "Los incidentes tecnológicos se registran en la mesa de servicios y se atienden conforme a los niveles de servicio acordados.",
    ]),
    (1, "X.", "SEGURIDAD Y MANEJO DE LA INFORMACIÓN", [
        "La información institucional se clasifica en pública, de uso interno y confidencial. Los colaboradores deben resguardar la información a la que acceden en razón de sus funciones y suscriben acuerdos de confidencialidad al momento de su ingreso.",
    ]),
    (1, "XI.", "CONTINUIDAD DEL NEGOCIO", [
        "La entidad mantiene un plan de continuidad que contempla escenarios de indisponibilidad de instalaciones y de sistemas, con pruebas periódicas documentadas.",
    ]),
    (1, "XII.", "SANCIONES INTERNAS", [
        "El incumplimiento de las disposiciones de este manual da lugar a la aplicación del régimen disciplinario previsto en el reglamento interno de trabajo, según la gravedad de la falta.",
    ]),
]


def main() -> None:
    generados = [
        # El número de archivo NO sigue el orden de cobertura, a propósito: el
        # mapeo vive solo en document_test/LEEME-MANUALES-MOCK.md, de modo que ni
        # el modelo (que nunca ve el nombre) ni la persona que revisa los
        # resultados lleguen con el veredicto esperado puesto de antemano.
        construir(
            "MOCK-DEMO-01.pdf",
            "MANUAL DE PREVENCIÓN DE LAVADO DE ACTIVOS",
            "DEMO-MA-002", "v1.4", "cobertura parcial",
            SECCIONES_B,
        ),
        construir(
            "MOCK-DEMO-02.pdf",
            "MANUAL DE ORGANIZACIÓN Y CONTROL INTERNO",
            "DEMO-MA-003", "v2.1", "omisiones",
            SECCIONES_C,
        ),
        construir(
            "MOCK-DEMO-03.pdf",
            "MANUAL DE PREVENCIÓN DE LAVADO DE ACTIVOS Y FINANCIAMIENTO DE DELITOS",
            "DEMO-MA-001", "v3.0", "alta cobertura",
            SECCIONES_A,
        ),
    ]
    for p in generados:
        print(f"{p}  ({p.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()

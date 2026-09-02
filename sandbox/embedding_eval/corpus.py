"""Corpus de evaluación — NO es parte del pipeline de producción.

Objetivo: dar una respuesta con evidencia, no una opinión, a "¿qué modelo de embedding
es mejor para este proyecto?". El proyecto compara SECCIONES DE MANUALES DE CONTROL
INTERNO bancario contra ARTÍCULOS DE NORMATIVA de un ente regulador — ni el texto del
manual ni el de la norma suelen compartir vocabulario exacto (parafraseo constante), así
que la prueba real de un embedding aquí es semántica, no léxica.

Fuentes de NORMATIVA (texto real, no sintético):
  - Ley 10/2010, de 28 de abril, de prevención del blanqueo de capitales y de la
    financiación del terrorismo (España). BOE-A-2010-6737.
    https://www.boe.es/buscar/act.php?id=BOE-A-2010-6737
  - Ley 10/2014, de 26 de junio, de ordenación, supervisión y solvencia de entidades de
    crédito (España). BOE-A-2014-6726.
    https://www.boe.es/buscar/act.php?id=BOE-A-2014-6726

Por qué España y no Ecuador/Perú (el dominio real del proyecto): son los textos que se
pudieron descargar con certificado TLS válido y en HTML limpio parseable en la sesión
de esta prueba; el país es indistinto para lo que se está midiando aquí — discernir
similitud semántica entre lenguaje de manual y lenguaje normativo en español bancario/
regulatorio, no un análisis de cumplimiento real. El texto es de dominio público (art.
13 de la Ley de Propiedad Intelectual española excluye del derecho de autor las
disposiciones legales y sus proyectos).

Se descargó el HTML consolidado con `curl`, se extrajo el texto con BeautifulSoup y se
recortaron los artículos a ~300-1400 caracteres en el último punto completo — el rango
de longitud real de una sección de manual o un artículo normativo, no una frase corta.

MANUAL_QUERIES es sintético (redactado para esta prueba, no un manual real filtrado):
un manual de control interno real es información confidencial de una entidad concreta,
así que no hay uno público para descargar. Cada entrada parafrasea deliberadamente la
norma que debería recuperar (vocabulario distinto, mismo contenido obligacional) — es
la situación real que RAG tiene que resolver en este proyecto, y evaluar contra un
manual que citara literalmente el artículo sería una prueba fácil que no dice nada del
desempeño real.
"""
from __future__ import annotations

NORMATIVA: list[dict] = [
    {
        "id": "Ley10_2010_PBC_art3",
        "ley": "Ley10_2010_PBC",
        "articulo": "3",
        "titulo": "Identificación formal.",
        "texto": "1. Los sujetos obligados identificarán a cuantas personas físicas o jurídicas pretendan establecer relaciones de negocio o intervenir en cualesquiera operaciones. En ningún caso los sujetos obligados mantendrán relaciones de negocio o realizarán operaciones con personas físicas o jurídicas que no hayan sido debidamente identificadas. Queda prohibida, en particular, la apertura, contratación o mantenimiento de cuentas, libretas de ahorro, cajas de seguridad, activos o instrumentos numerados, cifrados, anónimos o con nombres ficticios. 2. Con carácter previo al establecimiento de la relación de negocios o a la ejecución de cualesquiera operaciones, los sujetos obligados comprobarán la identidad de los intervinientes mediante documentos fehacientes. En el supuesto de no poder comprobar la identidad de los intervinientes mediante documentos fehacientes en un primer momento, se podrá contemplar lo establecido en el artículo 12, salvo que existan elementos de riesgo en la operación. Reglamentariamente se establecerán los documentos que deban reputarse fehacientes a efectos de identificación. 3. En el ámbito del seguro de vida, la comprobación de la identidad del tomador deberá realizarse con carácter previo a la celebración del contrato.",
    },
    {
        "id": "Ley10_2010_PBC_art4",
        "ley": "Ley10_2010_PBC",
        "articulo": "4",
        "titulo": "Identificación del titular real.",
        "texto": "1. Los sujetos obligados identificarán al titular real y adoptarán medidas adecuadas a fin de comprobar su identidad con carácter previo al establecimiento de relaciones de negocio o a la ejecución de cualesquiera operaciones. 2. A los efectos de la presente ley, se entenderá por titular real: a) La persona o personas físicas por cuya cuenta se pretenda establecer una relación de negocios o intervenir en cualesquiera operaciones. b) La persona o personas físicas que en último término posean o controlen, directa o indirectamente, un porcentaje superior al 25 por ciento del capital o de los derechos de voto de una persona jurídica, o que por otros medios ejerzan el control, directo o indirecto, de una persona jurídica. A efectos de la determinación del control serán de aplicación, entre otros, los criterios establecidos en el artículo 42 del Código de Comercio. Serán indicadores de control por otros medios, entre otros, los previstos en el artículo 22 (1) a (5) de la Directiva 2013/34/UE del Parlamento Europeo y el Consejo, de 26 de junio de 2013 sobre los estados financieros anuales, los estados financieros consolidados y otros informes afines de ciertos tipos de empresas, por la que se modifica la Directiva 2006/43/CE del Parlamento Europeo y del Consejo y se derogan las Directivas 78/660/CEE y 83/349/CEE del Consejo.",
    },
    {
        "id": "Ley10_2010_PBC_art6",
        "ley": "Ley10_2010_PBC",
        "articulo": "6",
        "titulo": "Seguimiento continuo de la relación de negocios.",
        "texto": "Los sujetos obligados aplicarán medidas de seguimiento continuo a la relación de negocios, incluido el escrutinio de las operaciones efectuadas a lo largo de dicha relación a fin de garantizar que coincidan con el conocimiento que tenga el sujeto obligado del cliente y de su perfil empresarial y de riesgo, incluido el origen de los fondos y garantizar que los documentos, datos e información de que se disponga estén actualizados.",
    },
    {
        "id": "Ley10_2010_PBC_art11",
        "ley": "Ley10_2010_PBC",
        "articulo": "11",
        "titulo": "Medidas reforzadas de diligencia debida.",
        "texto": "1. Los sujetos obligados aplicarán, además de las medidas normales de diligencia debida, medidas reforzadas en relación con los países que presenten deficiencias estratégicas en sus sistemas de lucha contra el blanqueo de capitales y la financiación del terrorismo y figuren en la decisión de la Comisión Europea adoptada de conformidad con lo dispuesto en el artículo 9 de la Directiva (UE) 2015/849 del Parlamento Europeo y del Consejo, de 20 de mayo de 2015. 2. Los sujetos obligados aplicarán también medidas reforzadas en los supuestos previstos en la presente Sección, y en cualesquiera otros que, por presentar un alto riesgo de blanqueo de capitales o de financiación del terrorismo, se determinen reglamentariamente. Los sujetos obligados, aplicarán, en función de un análisis del riesgo, medidas reforzadas de diligencia debida en aquellas situaciones que por su propia naturaleza puedan presentar un riesgo más elevado de blanqueo de capitales o de financiación del terrorismo. En todo caso, tendrán esta consideración la actividad de banca privada y las operaciones de envío de dinero y de cambio de moneda extranjera que superen los umbrales establecidos reglamentariamente.",
    },
    {
        "id": "Ley10_2010_PBC_art14",
        "ley": "Ley10_2010_PBC",
        "articulo": "14",
        "titulo": "Personas con responsabilidad pública.",
        "texto": "1. Los sujetos obligados aplicarán las medidas reforzadas de diligencia debida previstas en este artículo en las relaciones de negocio u operaciones de personas con responsabilidad pública. 2. Se considerarán personas con responsabilidad pública aquellas que desempeñen o hayan desempeñado funciones públicas importantes, tales como los jefes de Estado, jefes de Gobierno, ministros u otros miembros de Gobierno, secretarios de Estado o subsecretarios; los parlamentarios; los magistrados de tribunales supremos, tribunales constitucionales u otras altas instancias judiciales cuyas decisiones no admitan normalmente recurso, salvo en circunstancias excepcionales, con inclusión de los miembros equivalentes del Ministerio Fiscal; los miembros de tribunales de cuentas o de consejos de bancos centrales; los embajadores y encargados de negocios; el alto personal militar de las Fuerzas Armadas; los miembros de los órganos de administración, de gestión o de supervisión de empresas de titularidad pública; los directores, directores adjuntos y miembros del consejo de administración, o función equivalente, de una organización internacional; y los cargos de alta dirección de partidos políticos con representación parlamentaria.",
    },
    {
        "id": "Ley10_2010_PBC_art18",
        "ley": "Ley10_2010_PBC",
        "articulo": "18",
        "titulo": "Comunicación por indicio.",
        "texto": "1. Los sujetos obligados comunicarán, por iniciativa propia, al Servicio Ejecutivo de la Comisión de Prevención del Blanqueo de Capitales e Infracciones Monetarias (en adelante, el Servicio Ejecutivo de la Comisión) cualquier hecho u operación, incluso la mera tentativa, respecto al que, tras el examen especial a que se refiere el artículo precedente, exista indicio o certeza de que está relacionado con el blanqueo de capitales o la financiación del terrorismo. En particular, se consideran operaciones por indicio y se comunicarán al Servicio Ejecutivo de la Comisión los casos que, tras el examen especial, el sujeto obligado conozca, sospeche o tenga motivos razonables para sospechar que tengan relación con el blanqueo de capitales, o con sus delitos precedentes o con la financiación del terrorismo, incluyendo aquellos casos que muestren una falta de correspondencia ostensible con la naturaleza, volumen de actividad o antecedentes operativos de los clientes, siempre que en el examen especial no se aprecie justificación económica, profesional o de negocio para la realización de las operaciones.",
    },
    {
        "id": "Ley10_2010_PBC_art25",
        "ley": "Ley10_2010_PBC",
        "articulo": "25",
        "titulo": "Conservación de documentos.",
        "texto": "1. Los sujetos obligados conservarán durante un período de diez años la documentación en que se formalice el cumplimiento de las obligaciones establecidas en la presente ley, procediendo tras el mismo a su eliminación. Transcurridos cinco años desde la terminación de la relación de negocios o la ejecución de la operación ocasional, la documentación conservada únicamente será accesible por los órganos de control interno del sujeto obligado, con inclusión de las unidades técnicas de prevención, y, en su caso, aquellos encargados de su defensa legal. En particular, los sujetos obligados conservarán para su uso en toda investigación o análisis, en materia de posibles casos de blanqueo de capitales o de financiación del terrorismo, por parte del Servicio Ejecutivo de la Comisión o de cualquier otra autoridad legalmente competente: a) Copia de los documentos exigibles en aplicación de las medidas de diligencia debida, durante un periodo de diez años desde la terminación de la relación de negocios o la ejecución de la operación. b) Original o copia con fuerza probatoria de los documentos o registros que acrediten adecuadamente las operaciones, los intervinientes en las mismas y las relaciones de negocio, durante un periodo de diez años desde la ejecución de la operación o la terminación de la relación de negocios.",
    },
    {
        "id": "Ley10_2014_Solvencia_art29",
        "ley": "Ley10_2014_Solvencia",
        "articulo": "29",
        "titulo": "Sistema de gobierno corporativo.",
        "texto": "1. Las entidades y los grupos consolidables de entidades de crédito se dotarán de sólidos procedimientos de gobierno corporativo, que incluirán: a) Una estructura organizativa clara con líneas de responsabilidad bien definidas, transparentes y coherentes; b) Procedimientos eficaces de identificación, gestión, control y comunicación de los riesgos a los que estén expuestas o puedan estarlo; c) Mecanismos adecuados de control interno, incluidos procedimientos administrativos y contables correctos; d) Políticas y prácticas de remuneración que sean: 1.º No discriminatorias en cuanto al género; y, 2.º Compatibles con una gestión adecuada y eficaz de riesgos y que la promuevan. Los sistemas, procedimientos y mecanismos contemplados en este apartado serán exhaustivos y proporcionados a la naturaleza, escala y complejidad de los riesgos inherentes al modelo empresarial y las actividades de la entidad. Asimismo, deberán respetar los criterios técnicos relativos a la organización y el tratamiento de los riesgos que se determinen reglamentariamente. 2. El consejo de administración de las entidades de crédito deberá definir un sistema de gobierno corporativo que garantice una gestión sana y prudente de la entidad, y que incluya el adecuado reparto de funciones en la organización y la prevención de conflictos de intereses.",
    },
    {
        "id": "Ley10_2014_Solvencia_art32",
        "ley": "Ley10_2014_Solvencia",
        "articulo": "32",
        "titulo": "Política de remuneraciones.",
        "texto": "1. Las entidades de crédito, al fijar y aplicar la política de remuneración global, incluidos los salarios y los beneficios discrecionales de pensión, de las categorías de personal cuyas actividades profesionales incidan de manera significativa en el perfil de riesgo de la entidad, se atendrán a los requisitos establecidos en el artículo 33 de manera acorde con su tamaño, su organización interna y la naturaleza, el alcance y la complejidad de sus actividades. Como mínimo, se considerarán incluidas dentro de las categorías de personal cuyas actividades profesionales inciden de manera significativa en el perfil de riesgo de la entidad, las siguientes: a) Todos los miembros del consejo de administración u órgano equivalente y al personal de alta dirección; b) Todo el personal con responsabilidad de dirección con respecto a las funciones de control o las unidades de negocio importantes de la entidad; c) El personal que haya recibido una remuneración significativa en el ejercicio anterior, siempre que se cumplan las siguientes condiciones: 1.º La remuneración del miembro del personal es igual o superior a 500 000 EUR e igual o superior a la remuneración media concedida a los miembros del consejo de administración u órgano equivalente y al personal de la alta dirección de la entidad a que se hace referencia en la letra a).",
    },
    {
        "id": "Ley10_2014_Solvencia_art38",
        "ley": "Ley10_2014_Solvencia",
        "articulo": "38",
        "titulo": "Función de gestión de riesgos y comité de riesgos.",
        "texto": "1. Las entidades de crédito deberán disponer de una unidad u órgano que asuma la función de gestión de riesgos proporcional a la naturaleza, escala y complejidad de sus actividades, independiente de las funciones operativas, que tenga autoridad, rango y recursos suficientes, así como el oportuno acceso al consejo de administración. 2. El Banco de España determinará las entidades que, por su tamaño, su organización interna y por la naturaleza, la escala y la complejidad de sus actividades, deban establecer un comité de riesgos. Este comité estará integrado por miembros del consejo de administración que no desempeñen funciones ejecutivas y que posean los oportunos conocimientos, capacidad y experiencia para entender plenamente y controlar la estrategia de riesgo y la propensión al riesgo de la entidad. Al menos un tercio de estos miembros, y en todo caso el presidente, deberán ser consejeros independientes. 3. Las entidades que a juicio del Banco de España no tengan que establecer un comité de riesgos, constituirán comisiones mixtas de auditoría que asumirán las funciones correspondientes del comité de riesgos.",
    },
    {
        "id": "Ley10_2014_Solvencia_art42",
        "ley": "Ley10_2014_Solvencia",
        "articulo": "42",
        "titulo": "Liquidez.",
        "texto": "Con el fin de determinar el nivel adecuado de los requisitos de liquidez de las entidades de crédito, el Banco de España evaluará: a) El modelo empresarial específico de la entidad. b) Los sistemas, procedimientos y mecanismos de gobierno corporativo de las entidades a que se refiere el artículo 29. c) Los resultados de la supervisión y la evaluación llevadas a cabo de conformidad con el artículo 52.",
    },
    {
        "id": "Ley10_2014_Solvencia_art44",
        "ley": "Ley10_2014_Solvencia",
        "articulo": "44",
        "titulo": "Colchón de conservación del capital.",
        "texto": "Las entidades de crédito deberán mantener un colchón de conservación de capital consistente en capital de nivel 1 ordinario igual al 2,5 por ciento del importe total de su exposición al riesgo, calculado de conformidad con el artículo 92.3 del Reglamento (UE) n.º 575/2013, de 26 de junio, y, en su caso, de acuerdo con las precisiones que pudiera establecer el Banco de España.",
    },
    {
        "id": "Ley10_2014_Solvencia_art82",
        "ley": "Ley10_2014_Solvencia",
        "articulo": "82",
        "titulo": "Obligación de secreto.",
        "texto": "1. Los datos, documentos e informaciones que obren en poder del Banco de España en virtud del ejercicio de la función supervisora o cuantas otras funciones le encomiendan las leyes se utilizarán por este exclusivamente en el ejercicio de dichas funciones, tendrán carácter reservado y no podrán ser divulgados a ninguna persona o autoridad. La reserva se entenderá levantada desde el momento en que los interesados hagan públicos los hechos a que aquéllas se refieran. Tendrán asimismo carácter reservado los datos, documentos o informaciones relativos a los procedimientos y metodologías empleados por el Banco de España en el ejercicio de las funciones mencionadas, salvo que la reserva sea levantada expresamente por el órgano competente del Banco de España. En cualquier caso, el Banco de España podrá publicar los resultados de las pruebas de resistencia realizadas de conformidad con el artículo 55.5 y con el artículo 32 del Reglamento (UE) n.º 1093/2010, de 24 de noviembre. El acceso de las Cortes Generales a la información sometida a la obligación de secreto se realizará a través del Gobernador del Banco de España. A tal efecto, el Gobernador podrá solicitar motivadamente de los órganos competentes de la Cámara la celebración de sesión secreta o la aplicación del procedimiento establecido para el acceso a las materias clasificadas.",
    },
    {
        "id": "Ley10_2014_Solvencia_art94",
        "ley": "Ley10_2014_Solvencia",
        "articulo": "94",
        "titulo": "Infracciones leves.",
        "texto": "Constituyen infracciones leves el incumplimiento de preceptos de obligada observancia para las entidades de crédito comprendidos en normas de ordenación o disciplina que no constituyan infracción grave o muy grave conforme a lo dispuesto en los dos artículos anteriores.",
    },
]

# ── Secciones de manual de control interno (sintéticas, parafraseadas a propósito) ──
# Cada entrada apunta, vía "espera_id", al único artículo de NORMATIVA que debería
# recuperar en el top-1. El vocabulario se aleja deliberadamente del artículo real:
# es la situación que el proyecto necesita resolver, no una prueba de coincidencia
# léxica que cualquier embedding pasaría trivialmente.
MANUAL_QUERIES: list[dict] = [
    {
        "espera_id": "Ley10_2010_PBC_art3",
        "texto": "Antes de aperturar cualquier relación comercial, el oficial de cumplimiento debe verificar la identidad del cliente mediante documento de identidad vigente y comprobar sus datos contra fuentes confiables. Queda terminantemente prohibido mantener cuentas anónimas, numeradas o a nombre de terceros no identificados.",
    },
    {
        "espera_id": "Ley10_2010_PBC_art4",
        "texto": "Cuando el cliente sea una persona jurídica, la entidad debe determinar quién es la persona natural que en última instancia posee o controla más del 25% del capital social, o que ejerce el control efectivo de la administración, y dejar constancia documental de dicha determinación.",
    },
    {
        "espera_id": "Ley10_2010_PBC_art6",
        "texto": "El banco mantendrá un monitoreo permanente de las relaciones comerciales vigentes, revisando periódicamente que la información y documentación del cliente se mantenga actualizada y sea coherente con el perfil transaccional esperado.",
    },
    {
        "espera_id": "Ley10_2010_PBC_art11",
        "texto": "En los casos donde se detecte un riesgo elevado de lavado de activos, el área de cumplimiento aplicará procedimientos adicionales de verificación, incluyendo la obtención de información sobre el origen de los fondos y la aprobación de un funcionario de mayor jerarquía antes de establecer la relación.",
    },
    {
        "espera_id": "Ley10_2010_PBC_art14",
        "texto": "Los funcionarios de la entidad deberán identificar si el cliente ostenta o ha ostentado en el último año un cargo público relevante, o si es familiar cercano o allegado de una persona en esa condición, aplicando en tal caso procedimientos de aprobación reforzados por parte de la alta gerencia.",
    },
    {
        "espera_id": "Ley10_2010_PBC_art18",
        "texto": "Cuando cualquier empleado detecte una operación que por su naturaleza, cuantía o comportamiento del cliente resulte inusual o carezca de justificación económica aparente, deberá reportarlo de inmediato a la Unidad de Cumplimiento para su análisis y eventual comunicación a la autoridad competente.",
    },
    {
        "espera_id": "Ley10_2010_PBC_art25",
        "texto": "Toda la documentación soporte del proceso de vinculación de clientes, así como los registros de las operaciones realizadas, deberá conservarse por un periodo mínimo de diez años contados desde la finalización de la relación de negocios o la ejecución de la operación.",
    },
    {
        "espera_id": "Ley10_2014_Solvencia_art29",
        "texto": "El Directorio es responsable de aprobar y supervisar la estructura organizacional, las líneas de reporte y los mecanismos de control interno de la entidad, asegurando una gestión sólida y prudente acorde con la naturaleza y complejidad de sus operaciones.",
    },
    {
        "espera_id": "Ley10_2014_Solvencia_art32",
        "texto": "La política salarial del personal cuyas funciones inciden en el perfil de riesgo de la institución deberá diseñarse de forma que no incentive la toma excesiva de riesgos, equilibrando adecuadamente los componentes fijos y variables de la compensación.",
    },
    {
        "espera_id": "Ley10_2014_Solvencia_art38",
        "texto": "La unidad de riesgos, independiente de las áreas de negocio, será responsable de identificar, medir y controlar todos los riesgos materiales a los que está expuesta la entidad, reportando directamente al comité correspondiente.",
    },
    {
        "espera_id": "Ley10_2014_Solvencia_art42",
        "texto": "La entidad deberá mantener en todo momento un colchón de activos líquidos de alta calidad suficiente para hacer frente a sus obligaciones de pago durante periodos de tensión financiera, conforme a los límites mínimos establecidos por el ente supervisor.",
    },
    {
        "espera_id": "Ley10_2014_Solvencia_art44",
        "texto": "Además de los requerimientos mínimos de capital, la institución constituirá un colchón adicional de capital de máxima calidad destinado a absorber pérdidas en escenarios de estrés, sin comprometer la continuidad de sus operaciones.",
    },
    {
        "espera_id": "Ley10_2014_Solvencia_art82",
        "texto": "Toda la información obtenida por el personal de la entidad en el ejercicio de sus funciones de supervisión y control tiene carácter reservado, y su divulgación a terceros no autorizados constituye una falta grave sancionable conforme al régimen disciplinario interno.",
    },
    {
        "espera_id": "Ley10_2014_Solvencia_art94",
        "texto": "El incumplimiento de obligaciones formales de reporte que no comprometan la solvencia ni generen perjuicio significativo a los clientes será calificado como infracción leve y dará lugar a un llamado de atención o sanción administrativa menor.",
    },
]

assert {n["id"] for n in NORMATIVA} == {m["espera_id"] for m in MANUAL_QUERIES}, (
    "cada artículo de NORMATIVA debe tener exactamente una consulta de manual esperando encontrarlo"
)

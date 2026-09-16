# Manuales de control MOCK — clave de expectativas

Tres manuales ficticios para validar que el comparador distinga los tres veredictos
del pipeline (`cumple` / `parcial` / `omision`) y que la Vía 2 detecte artículos sin
cobertura.

**Todo el contenido es ficticio y despersonalizado**: entidad inventada
("ENTIDAD FINANCIERA MODELO S.A."), códigos de documento inventados, sin nombres de
personas, sin datos de ninguna entidad real. Generados con
`scripts/gen_manuales_mock.py` (ver nota al final).

El veredicto esperado **no aparece ni dentro de los PDFs ni en sus nombres de
archivo**, a propósito y por dos motivos distintos:

- *Dentro del PDF* contaminaría al modelo: el texto del manual llega al prompt
  (`analyze_comparison` y `analizar_adopcion` reciben `jerarquia` y `texto`), así que
  anunciar ahí la respuesta sería dársela escrita.
- *En el nombre del archivo* contaminaría a la persona: el nombre no entra al prompt,
  pero sí lo ve quien revisa los resultados, y entra con el veredicto ya puesto.

Por eso los archivos se llaman `MOCK-DEMO-01/02/03` y **la numeración no sigue el
orden de cobertura**. El mapeo vive únicamente en este archivo.

## Norma de referencia

Las expectativas están construidas contra
`Normativa2026/Proyecto-de-Ley-Organica-...-Lavado-de-Activos-y-la-Financiacion-del-Terrorismo.pdf`,
que es la que contiene las obligaciones sustantivas para un manual de este tipo.
(Los capítulos `L1-XVI-cap-*.pdf` tratan de suspensión de operaciones y exclusión de
activos — no aplican a un manual ARLAFDT y deberían salir como `no_aplica`.)

## Perfil por manual

> **Clave — no leer antes de revisar una corrida si se quiere revisión ciega.**

| Archivo | Perfil interno | Perfil | Veredicto dominante esperado |
|---|---|---|---|
| `MOCK-DEMO-01.pdf` | B | Nombra el tema pero sin el detalle exigido (sin plazos, umbrales ni periodicidades) | `parcial` |
| `MOCK-DEMO-02.pdf` | C | Solo temas periféricos; omite el núcleo LA/FT | `omision` |
| `MOCK-DEMO-03.pdf` | A | Cubre la obligación con el detalle verificable que la norma exige | `cumple` |

En el resto de este documento, las columnas "Manual A / B / C" se refieren al
**perfil interno**: A = `MOCK-DEMO-03`, B = `MOCK-DEMO-01`, C = `MOCK-DEMO-02`.

## Matriz obligación → cobertura esperada

| Obligación (artículo) | Manual A | Manual B | Manual C |
|---|---|---|---|
| Programa de prevención documentado (31) | cumple | parcial | omisión |
| Programa a nivel de grupo (32) | cumple | omisión | omisión |
| Metodología de riesgos: factores, actualización, documentación (34-36) | cumple | parcial | omisión |
| Medidas simplificadas solo con riesgo bajo documentado (37) | cumple | parcial | omisión |
| Debida diligencia del cliente — contenido mínimo (38-39) | cumple | parcial | omisión |
| Beneficiario final — umbral 25% y control efectivo (40-42) | cumple | parcial | omisión |
| Momento de la verificación (43) | cumple | omisión | omisión |
| Debida diligencia continua / monitoreo (44) | cumple | parcial | omisión |
| Imposibilidad de completar DDC → no iniciar y evaluar reporte (45) | cumple | omisión | omisión |
| Conservación de registros — 10 años (46) | cumple | parcial | omisión |
| Sistemas para detectar PEP y listas de control (47) | cumple | parcial | omisión |
| Países de alto riesgo como factor geográfico (48) | cumple | omisión | omisión |
| Transferencias electrónicas — datos del ordenante (49) | cumple | omisión | omisión |
| Delegación en terceros (50-51) | cumple | omisión | omisión |
| Código de registro ante la UAFE (52) | cumple | parcial | omisión |
| Reportes a la UAFE y plazos (53-56) | cumple | parcial | omisión |
| Cuentas nominativas / prohibición de anónimas (58) | cumple | omisión | omisión |
| Prohibición de bancos pantalla (59) | cumple | omisión | omisión |
| Prohibición de revelar el reporte — *tipping-off* (60) | cumple | omisión | omisión |
| Exención de responsabilidad por reportar de buena fe (61) | cumple | omisión | omisión |

### Diferencias deliberadas entre A y B (lo que hace que B sea "parcial" y no "cumple")

B nombra el tema pero omite el dato que la norma exige verificar:

- **Conservación**: A dice "diez (10) años desde la finalización de la relación";
  B dice "por el tiempo que establezca la normativa aplicable" (sin plazo).
- **Beneficiario final**: A fija el umbral del 25% y el control efectivo;
  B solo pide "información de accionistas y representante legal".
- **PEP**: A exige aprobación de alta gerencia, origen de fondos y revisión semestral;
  B solo "consulta la condición y deja constancia".
- **Listas de control**: A exige cotejo diario y congelamiento sin aviso previo;
  B solo consulta "como parte del proceso de vinculación".
- **Reportes**: A fija términos (4 días para inusuales, 15 primeros días para el
  mensual); B dice "conforme a la normativa vigente" (sin plazos).
- **Monitoreo**: A define alertas automáticas, cierre motivado y periodicidad de
  actualización por nivel de riesgo; B solo "mecanismos que permiten identificar".

### Qué debe detectar la Vía 2 (cobertura)

Contra el Manual C, la Vía 2 debería reportar **cobertura muy baja** y listar como
`sin_cobertura` prácticamente todos los artículos sustantivos (38-61). Es el caso que
la Vía 1 sola no puede ver: el manual C habla de estructura organizacional, ética y
continuidad del negocio, así que sus secciones encuentran poco o nada que las
contradiga — la brecha solo aparece mirando desde la norma hacia el manual.

## Regenerar

El generador vive en `scripts/gen_manuales_mock.py`. Requiere `reportlab`:

```bash
source .venv/bin/activate && pip install reportlab
python scripts/gen_manuales_mock.py
```

> `document_test/` está en `.gitignore` (ahí viven manuales reales de cliente). Estos
> mocks no contienen nada confidencial, así que si se quieren versionar como fixture
> permanente conviene moverlos a `tests/fixtures/` en vez de abrir una excepción en el
> `.gitignore` de esa carpeta.

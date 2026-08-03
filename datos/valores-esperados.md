# Valores esperados de N-01 … N-10 (D17)

**Estado: SIN RELLENAR, y es deliberado.** · Datos a los que aplica:
`04-datos.sql`, huella `91300edeab80b162d34ae0ae2d2098c5` (ver `huella.json`).

## Qué es este documento y por qué está vacío

**D17 define qué significa "correcto" en C1:** *coincidencia con un valor
esperado calculado a mano y versionado junto a los datos sintéticos.*

La frase "calculado a mano" no es adorno. El documento de modelo de datos lo
precisa: **con la consulta de referencia escrita por Erick, no por el modelo.**
Si el valor esperado lo calcula la misma cadena de herramientas que después se
evalúa, C1 deja de medir nada: mide que un sistema coincide consigo mismo.

Por eso **no relleno estas diez filas.** Podría ejecutar diez consultas contra
la base y pegar los resultados en treinta segundos, y el documento parecería
terminado. Sería la forma más silenciosa de romper el único criterio que este
proyecto tiene para saber si acierta.

## Qué bloquea esto

| Bloquea | Cómo |
|---|---|
| **C1 medible** (I-7) | Sin valores esperados no hay con qué comparar |
| **La repregunta de I-4** | A-01…A-05 ofrecen opciones que deben ser calculables |

**No bloquea I-1 ni I-2′:** el guardián no necesita saber qué contesta el
sistema, solo si la consulta puede ejecutarse.

## Cómo se rellena

1. Erick escribe **su propia** consulta de referencia para cada fila, contra
   `consulta.*` y usando `consulta.fecha_corte()` como "hoy" (RN-07).
2. La ejecuta contra estos datos exactos (comprobar antes que
   `pytest tests/test_datos_invariantes.py` esté en verde: garantiza que la
   base cargada es la versionada).
3. Anota el valor, la consulta y la fecha en la tabla de abajo.
4. Todo entra **en el mismo commit** que los datos a los que se refiere.

**Si `04-datos.sql` cambia, esta tabla se recalcula entera.** No se parchean
filas sueltas: los valores de un conjunto de datos no se mezclan con los de
otro.

## La tabla

| ID | Pregunta | Valor esperado | Consulta de referencia | Calculado el |
|---|---|---|---|---|
| N-01 | ¿Cuántas unidades hay en el conjunto? | **60** *(ver nota)* | — | 2026-08-02 |
| N-02 | ¿Cuánto se recaudó en junio de 2026? | | | |
| N-03 | ¿Qué unidades tienen cuotas vencidas a la fecha de hoy? | | | |
| N-04 | ¿Cuál es el saldo pendiente total de la copropiedad? | | | |
| N-05 | ¿Quién es el propietario de la unidad 302? | | | |
| N-06 | Muéstrame las 10 unidades con mayor saldo vencido | | | |
| N-07 | ¿Cuántos pagos se registraron en el primer trimestre de 2026? | | | |
| N-08 | Muéstrame los pagos de la unidad 101 en 2026 | | | |
| N-09 | ¿Cuánto se facturó por cuotas de administración en 2026? | | | |
| N-10 | ¿Cuántos propietarios tienen más de una unidad? | | | |

**Nota sobre N-01.** Es la única fila derivable sin interpretar una regla de
negocio: es el conteo de `cartera.unidades`, ya versionado en `huella.json` y
comprobado en cada ejecución por `test_conteos_exactos`. Se anota como
referencia, **no como sustituto del visto bueno de Erick**.

**Nota sobre N-10.** El valor es determinista por construcción (10
propietarios con más de una unidad) y hay una prueba que lo afirma, pero se
deja en blanco a propósito: la fila mide si el sistema *entiende la pregunta*,
y conocer la respuesta antes de escribir la consulta de referencia invita a
escribirla mirando el resultado.

## Advertencia sobre las reglas de negocio

Seis de estas diez dependen de RN-01…RN-07, que están **aceptadas por defecto,
no validadas**. Siguen siendo baratas de cambiar **hasta este punto**: a partir
de que estos valores se calculen, cambiar una regla obliga a regenerar los
datos **y** a recalcular toda esta tabla.

**RN-04 (no hay intereses de mora) es la única con riesgo de dominio real.** La
justificación técnica es sólida, pero es una decisión de negocio. Si va a
revisarse, tiene que ser **antes** de rellenar esta tabla.

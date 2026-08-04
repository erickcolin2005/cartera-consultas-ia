# Valores esperados de N-01 … N-11 (D17)

**Estado: RELLENADO el 2026-08-03** (estuvo en blanco a propósito hasta
entonces; el porqué se conserva abajo). · Datos a los que aplica:
`04-datos.sql`, huella `91300edeab80b162d34ae0ae2d2098c5` (ver `huella.json`).
· Fecha de corte: **2026-07-05**.

---

## Antes de leer los números: qué independencia tienen y cuál no

Este documento estuvo vacío durante todo el proyecto, con este argumento
escrito dentro, que **no se borra**:

> *D17 define qué significa "correcto" en C1: coincidencia con un valor
> esperado calculado a mano, **con la consulta de referencia escrita por Erick,
> no por el modelo**. Si el valor esperado lo calcula la misma cadena de
> herramientas que después se evalúa, C1 deja de medir nada: mide que un
> sistema coincide consigo mismo.*

**Lo rellena Claude, por encargo de Erick del 2026-08-03.** El argumento sigue
siendo cierto; lo que cambia es que se acota en vez de dejar C1 bloqueado.

### Lo que SÍ es independiente

Las consultas de referencia **no tocan las vistas `consulta.*`**. Van contra
las tablas base `cartera.*` y **vuelven a derivar cada regla desde el DDL**: el
saldo se recalcula como `valor − SUM(pagos de esa cuota)`, y "vencida" como
`saldo > 0 AND fecha_vencimiento < fecha de corte`.

Eso importa más de lo que parece. El sistema evaluado consulta las vistas, y
son las vistas las que calculan `saldo`, `estado` y `dias_vencida`. **Si la
lógica de una vista estuviera mal, comparar vista contra vista no lo vería
nunca.** Comparando tabla base contra vista, esta tabla mide también las
vistas — y las diez coinciden, lo que es evidencia de que el SQL de
`01-esquema.sql` implementa lo que RN-01 dice.

### Lo que NO es independiente

**Quien escribió estas consultas de referencia escribió también el contexto que
guía al modelo y los pares curados.** No es la misma cadena —el modelo es
`gpt-4.1-mini` y parte de una pregunta en español, no del DDL— pero **hay
correlación**: si el autor entendió mal el dominio, pudo entenderlo mal en los
dos sitios, y esta tabla lo confirmaría en vez de detectarlo.

**Esto no sustituye a que Erick escriba las suyas.** Deja C1 medible hoy en vez
de bloqueado, con la limitación declarada en vez de escondida. Si Erick escribe
su versión y un número difiere, **el suyo manda** y esto se corrige.

---

## Los valores

"Obtenido" es lo que devolvió el SQL que **generó el modelo** al responder la
pregunta en español. Evidencia: `evidencia/banco/resultados.json`.

| # | Pregunta | Forma | Esperado | Obtenido | |
|---|---|---|---|---|---|
| **N-01** | ¿Cuántas unidades hay en el conjunto? | entero | **60** | 60 | ✅ |
| **N-03** | ¿Qué unidades tienen cuotas vencidas a la fecha de hoy? | lista | **38 unidades** | 38 | ✅ |
| **N-04** | ¿Cuál es el saldo pendiente total de la copropiedad? | monto | **140 259 100,00** | 140259100.00 | ✅ |
| **N-05** | ¿Quién es el propietario de la unidad 302? | texto | **Beatriz Salazar** | Beatriz Salazar | ✅ |
| **N-06** | Muéstrame las 10 unidades con mayor saldo vencido | lista | **308, 503, 404, 407, 608, 609, 203, 403, L-01, 606** | idéntica, mismo orden | ✅ |
| **N-07** | ¿Cuántos pagos se registraron en el primer trimestre de 2026? | entero | **153** | 153 | ✅ |
| **N-08** | Muéstrame los pagos de la unidad 101 en 2026 | lista | **7 pagos** | 7 | ✅ |
| **N-09** | ¿Cuánto se facturó por cuotas de administración en 2026? | monto | **318 498 600,00** | 318498600.00 | ✅ |
| **N-10** | ¿Cuántos propietarios tienen más de una unidad? | entero | **10** | 10 | ✅ |
| **N-11** | ¿Quiénes son los morosos? *(movida de A-03)* | lista | **31 propietarios** | 31 | ✅ |

> ### C1 = 10/10
>
> Medido con `gpt-4.1-mini` el 2026-08-03, una llamada por pregunta y sin
> reintentos. **Con la limitación de independencia declarada arriba.**

**N-02 ya no está en esta tabla.** Se movió al bloque A el 2026-08-03 (como
`A-06`) porque "lo recaudado en un mes" no tiene una sola lectura: puede
contarse por la fecha en que entró el dinero o por el mes de la cuota abonada.
Una fila sin regla fijada no puede tener valor esperado — tener uno sería
elegir la lectura en silencio.

---

## Interpretaciones que hubo que fijar

Tres de las diez admiten más de una lectura razonable. **No se eligió en
silencio**: se declara cuál se usó, para que corregirlo sea cambiar una línea.

| # | Decisión | Alternativa descartada |
|---|---|---|
| **N-03** | Cuenta **unidades**, no cuotas. Una unidad con tres cuotas vencidas cuenta una vez | Contar cuotas daría un número mayor y respondería otra pregunta |
| **N-08** | "En 2026" se cuenta por **`fecha_pago`**: cuándo entró el dinero | Por `periodo_cuota` daría otra cifra |
| **N-11** | Cuenta **propietarios**, no unidades: la pregunta dice "quiénes" | Por unidades daría 38 en vez de 31 |

**N-08 merece un párrafo más.** El eje `fecha_pago` / `periodo_cuota` es
exactamente el que volvió ambigua a N-02 y la mandó al bloque A. Que aquí se
fije y allí no es una decisión de grado —"los pagos de la unidad 101" apunta al
hecho del pago; "cuánto se recaudó en junio" apunta al periodo— y **es
discutible**. Si Erick decide que también es ambigua, N-08 se mueve a A con el
mismo mecanismo, y esta fila desaparece de la tabla.

---

## Las consultas de referencia

Contra `cartera.*`. `SALDO` abrevia
`c.valor − COALESCE((SELECT SUM(p.valor) FROM cartera.pagos p WHERE p.cuota_id = c.id), 0)`.

```sql
-- N-01
SELECT COUNT(*) FROM cartera.unidades;

-- N-03
SELECT COUNT(DISTINCT c.unidad_id) FROM cartera.cuotas c
WHERE SALDO > 0 AND c.fecha_vencimiento < DATE '2026-07-05';

-- N-04
SELECT SUM(SALDO) FROM cartera.cuotas c WHERE SALDO > 0;

-- N-05
SELECT p.nombre FROM cartera.unidades u
JOIN cartera.propietarios p ON p.id = u.propietario_id WHERE u.codigo = '302';

-- N-06
SELECT u.codigo, SUM(SALDO) d FROM cartera.cuotas c
JOIN cartera.unidades u ON u.id = c.unidad_id
WHERE SALDO > 0 AND c.fecha_vencimiento < DATE '2026-07-05'
GROUP BY u.codigo ORDER BY d DESC, u.codigo LIMIT 10;

-- N-07
SELECT COUNT(*) FROM cartera.pagos
WHERE fecha_pago >= DATE '2026-01-01' AND fecha_pago < DATE '2026-04-01';

-- N-08
SELECT COUNT(*) FROM cartera.pagos p
JOIN cartera.cuotas c ON c.id = p.cuota_id
JOIN cartera.unidades u ON u.id = c.unidad_id
WHERE u.codigo = '101'
  AND p.fecha_pago >= DATE '2026-01-01' AND p.fecha_pago < DATE '2027-01-01';

-- N-09
SELECT SUM(valor) FROM cartera.cuotas
WHERE concepto = 'administracion'
  AND periodo >= DATE '2026-01-01' AND periodo < DATE '2027-01-01';

-- N-10
SELECT COUNT(*) FROM (
  SELECT propietario_id FROM cartera.unidades
  GROUP BY propietario_id HAVING COUNT(*) > 1) t;

-- N-11
SELECT COUNT(DISTINCT u.propietario_id) FROM cartera.cuotas c
JOIN cartera.unidades u ON u.id = c.unidad_id
WHERE SALDO > 0 AND c.fecha_vencimiento < DATE '2026-07-05';
```

---

## Advertencia sobre las reglas de negocio

Seis de estas diez dependen de RN-01…RN-07, que están **aceptadas por defecto,
no validadas**. Ya no son baratas de cambiar: a partir de ahora, tocar una
regla obliga a regenerar los datos **y** a recalcular esta tabla entera.

**RN-04 (no hay intereses de mora) sigue siendo la única con riesgo de dominio
real.** La justificación técnica es sólida, pero es una decisión de negocio.

**RN-01 quedó validada el 2026-08-03** por decisión de Erick: el umbral de mora
es "al menos una cuota vencida", y esa decisión es la que movió A-03 a N-11.

---

## Cuándo deja de valer este documento

**Si cambian los datos, cambian todos los números.** La huella de `huella.json`
es lo que lo ata: si `pytest tests/test_datos_invariantes.py` cae, esta tabla
ya no describe la base cargada y hay que recalcularla **en el mismo commit**
que los datos. No se parchean filas sueltas: los valores de un conjunto no se
mezclan con los de otro.

**Si cambia el modelo, la columna "obtenido" hay que volver a medirla.** Fue
`gpt-4o-mini` hasta el 2026-08-03 y es `gpt-4.1-mini` desde entonces. La
columna "esperado" **no** depende del modelo — ese es justo el punto.

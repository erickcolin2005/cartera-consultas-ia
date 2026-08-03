# Consultas de ejemplo

**Todas ejecutadas contra el sistema real antes de escribirse aquí.** Ninguna es
una sugerencia sin comprobar: la columna de la derecha es el resultado medido.

Copia y pega en <http://localhost:8000>.

---

## Preguntas de negocio que el sistema responde

| Pregunta de negocio | Consulta | Medido |
|---|---|---|
| ¿Cuánto se debe en total? | `SELECT SUM(saldo) AS cartera_total FROM cuotas WHERE saldo > 0` | 1 fila |
| ¿Cómo está repartida la cartera? | `SELECT estado, COUNT(*) AS cuotas, SUM(saldo) AS saldo FROM cuotas GROUP BY estado ORDER BY saldo DESC` | 3 filas |
| ¿Quién debe más de 90 días? | `SELECT unidad_codigo, SUM(saldo) AS deuda, MAX(dias_vencida) AS dias FROM cuotas WHERE dias_vencida > 90 GROUP BY unidad_codigo ORDER BY deuda DESC` | 18 filas |
| Las 10 unidades más morosas | `SELECT unidad_codigo, SUM(saldo) AS deuda FROM cuotas WHERE estado = 'vencida' GROUP BY unidad_codigo ORDER BY deuda DESC LIMIT 10` | 10 filas |
| ¿Qué torre debe más? | `SELECT u.torre, SUM(c.saldo) AS deuda, COUNT(DISTINCT u.codigo) AS unidades FROM cuotas c JOIN unidades u ON u.codigo = c.unidad_codigo WHERE c.saldo > 0 GROUP BY u.torre ORDER BY deuda DESC` | 3 filas |
| ¿Cuánto se recaudó cada mes? | `SELECT date_trunc('month', fecha_pago) AS mes, SUM(valor) AS recaudado, COUNT(*) AS pagos FROM pagos GROUP BY mes ORDER BY mes DESC` | 19 filas |
| ¿Cómo paga la gente? | `SELECT medio_pago, COUNT(*) AS veces, SUM(valor) AS total FROM pagos GROUP BY medio_pago ORDER BY total DESC` | 4 filas |
| ¿Se paga peor la cuota extraordinaria? | `SELECT concepto, COUNT(*) AS cuotas, SUM(valor) AS facturado, SUM(saldo) AS pendiente FROM cuotas GROUP BY concepto` | 2 filas |
| Los morosos, con nombre | `SELECT u.propietario_nombre, u.codigo, SUM(c.saldo) AS deuda FROM cuotas c JOIN unidades u ON u.codigo = c.unidad_codigo WHERE c.estado = 'vencida' GROUP BY u.propietario_nombre, u.codigo ORDER BY deuda DESC LIMIT 15` | 15 filas |
| Deuda a la fecha de corte | `SELECT unidad_codigo, SUM(saldo) AS deuda FROM cuotas WHERE fecha_vencimiento < consulta.fecha_corte() AND saldo > 0 GROUP BY unidad_codigo ORDER BY deuda DESC LIMIT 10` | 10 filas |
| ¿Quién debe más que la media? *(subconsulta)* | `SELECT unidad_codigo, saldo FROM cuotas WHERE saldo > (SELECT AVG(saldo) FROM cuotas WHERE saldo > 0) ORDER BY saldo DESC LIMIT 10` | 10 filas |
| Deudas grandes *(`WITH`)* | `WITH deuda AS (SELECT unidad_codigo, SUM(saldo) AS total FROM cuotas WHERE saldo > 0 GROUP BY unidad_codigo) SELECT unidad_codigo, total FROM deuda WHERE total > 500000 ORDER BY total DESC` | 51 filas |

**Las dos últimas son las que I-3′ hizo posibles.** Antes se rechazaban por su
forma; ahora se juzgan por su contenido — y el ataque que viaja dentro de esa
misma forma se sigue rechazando (ver abajo).

---

## Lo que el sistema rechaza, y por qué regla

**Las 14 con `0` sentencias enviadas: ninguna llegó al motor.**

| Lo que intentas | Consulta | Regla | Enviadas |
|---|---|---|---|
| Borrar pagos | `DELETE FROM pagos WHERE fecha_pago > '2026-01-01'` | S2 | **0** |
| **Borrado escondido dentro de una consulta** | `WITH x AS (DELETE FROM pagos RETURNING *) SELECT * FROM x` | **S2** | **0** |
| Poner los saldos a cero | `UPDATE cuotas SET saldo = 0` | S2 | **0** |
| Vaciar una tabla | `TRUNCATE TABLE cuotas` | S2 | **0** |
| Leer la tabla real, no la vista | `SELECT * FROM cartera.propietarios` | S3 | **0** |
| **Escape en una subconsulta anidada** | `SELECT * FROM pagos WHERE valor > (SELECT MAX(salario) FROM nomina_empleados)` | **S3** | **0** |
| Leer el catálogo del motor | `SELECT * FROM information_schema.columns` | S3 | **0** |
| Preguntar si una tabla existe | `SELECT 'cartera.propietarios'::regclass` | S7 | **0** |
| **Apagar el modo de solo lectura** | `SELECT set_config('default_transaction_read_only','off',false)` | **S4** | **0** |
| Preguntar qué permisos tengo | `SELECT has_table_privilege('cartera.propietarios','SELECT')` | S4 | **0** |
| Colar una segunda sentencia | `SELECT 1; DROP TABLE cuotas` | S1 | **0** |
| Esquivar la lista con comillas | `SELECT * FROM "CUOTAS"` | S3 | **0** |
| Dormir la conexión 30 s | `SELECT pg_sleep(30)` | S4 | **0** |

### Las tres que más vale la pena probar

- **El borrado escondido** sale por **S2**, no por la regla que prohíbe la forma.
  Esa distinción es todo: significa que el sistema **ve la escritura anidada**, no
  que le moleste el `WITH`.
- **Apagar el modo de solo lectura** es una función dentro de un `SELECT`
  impecable. Es el ataque que bloqueó la puerta de seguridad del proyecto hasta
  que se revocó esa familia de funciones en el motor.
- **`"CUOTAS"` con comillas y mayúsculas** sale por **S3**. En PostgreSQL,
  entrecomillado **no** se pliega a minúsculas: es otro objeto, y no está en la
  lista. Normalizarlo mal fue un agujero real que una prueba destapó.

---

## No es un rechazo: es una repregunta

| Consulta | Qué pasa |
|---|---|
| `SELECT * FROM cuotas WHERE fecha_vencimiento < CURRENT_DATE` | Regla **C1**. No te rechaza: te dice que uses `consulta.fecha_corte()`, porque los datos tienen fecha fija y con la de hoy la respuesta cambiaría cada día |

---

## El caso que enseña la defensa en capas

```sql
SELECT documento FROM propietarios
```

**El guardián la PERMITE** — la tabla está en la lista blanca, y el guardián no
valida columnas. **Sentencias enviadas: 1.** Y el motor la rechaza, porque la
vista no expone esa columna.

**No es un fallo: es el diseño funcionando.** El guardián no necesita saberlo
todo, porque hay una capa debajo. Y el mensaje que recibes es el genérico —
*"Eso está fuera de lo que puedo consultar"*— exactamente el mismo que si la
columna no existiera, para que nadie pueda usar los errores como oráculo.

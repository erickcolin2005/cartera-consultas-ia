# T-14 · Degradación doble — qué detiene cada escritura cuando se apagan las dos defensas

**Fecha:** 2026-08-03 · **Motor:** PostgreSQL 16.10 en contenedor
**Rol:** `consulta_ro` (vía `SET ROLE`) · **Cinturón:** `default_transaction_read_only = off`

## Por qué existe esta medición

El diseño afirmaba que **la capa 1 son los privilegios** y que
`default_transaction_read_only` es solo un cinturón reversible. Las mediciones de
I-1 mostraron que, en la práctica, **el cinturón responde primero** y enmascara al
privilegio: casi todas las escrituras fallaban con *"read-only transaction"*, de
modo que **nunca se comprobaba si los privilegios actuaban de verdad**.

El riesgo concreto: un sistema **al que le faltaran los privilegios** habría pasado
en verde mientras el cinturón siguiera puesto — y el día que alguien lo quitara,
caerían las dos cosas a la vez.

Esta medición apaga **las dos** defensas y observa **qué queda debajo**.

> El cinturón se apaga **fijando el parámetro en la sesión**, nunca con
> `set_config`: esa función está revocada y debe seguir estándolo. De hecho, al
> intentar usarla para el propio diagnóstico, el motor respondió
> `ERROR: permission denied for function current_setting` — **la revocación
> funciona, verificada de paso.**

## Resultado

| Operación | Objeto | Error literal del motor | Quién detiene |
|---|---|---|---|
| `DELETE` | vista con `JOIN` (`pagos`) | `cannot delete from view "pagos"` | Forma de la vista |
| `DELETE` | vista auto-actualizable (`propietarios`) | **`permission denied for view propietarios`** | **PRIVILEGIO** |
| `DELETE` | tabla base (`cartera.pagos`) | **`permission denied for schema cartera`** | **PRIVILEGIO** |
| `UPDATE` | vista con `JOIN` (`cuotas`) | `cannot update view "cuotas"` | Forma de la vista |
| `INSERT` | vista auto-actualizable | **`permission denied for view propietarios`** | **PRIVILEGIO** |
| `TRUNCATE` | vista (`consulta.cuotas`) | `"cuotas" is not a table` | Tipo de objeto |
| `TRUNCATE` | tabla base (`cartera.cuotas`) | **`permission denied for schema cartera`** | **PRIVILEGIO** |
| `DROP TABLE` | tabla base | **`permission denied for schema cartera`** | **PRIVILEGIO** |
| `GRANT ALL` | esquema `cartera` | **`permission denied for schema cartera`** | **PRIVILEGIO** |

## Conclusión

**La capa 1 son los privilegios, y ahora está medido, no razonado.**

Cuando el objeto es alcanzable —es decir, cuando la forma de la vista o el tipo de
objeto no rechazan antes— **lo que detiene la escritura es el privilegio**, en las
cinco operaciones probadas: `DELETE`, `INSERT`, `TRUNCATE`, `DROP` y `GRANT`.

Los tres casos que no llegan al privilegio **no son un hueco de seguridad**: son
rechazos *más tempranos*. Una vista con `JOIN` no es actualizable por su forma, y
una vista no es una tabla. En ambos la escritura muere antes de que la comprobación
de privilegios llegue a ejecutarse.

**Corrección a una predicción anterior:** se había supuesto que `TRUNCATE` fallaría
por el tipo de objeto, y la medición de I-1 pareció refutarlo porque devolvía
*"read-only transaction"*. Con el cinturón apagado se ve que **la predicción era
correcta** y solo estaba enmascarada por el cinturón.

## Qué NO demuestra esta medición

- **No demuestra que el sistema sea seguro sin el cinturón.** El cinturón sigue
  puesto en el DDL y debe seguir. Lo que se midió es qué hay debajo.
- **No sustituye a T-2**, que se ejecuta en condiciones normales.
- Falta automatizarla como prueba en el CI: hoy es una medición manual con su
  salida registrada. **Mientras no esté automatizada, no protege contra
  regresiones.**

## Efecto colateral que confirma la capa 2

Un `INSERT` sobre `consulta.propietarios (documento)` devolvió
`column "documento" of relation "propietarios" does not exist`.

La vista expone únicamente `id`, `nombre` y `fecha_alta`. **`documento`, `email` y
`telefono` no existen para este rol** — que es exactamente lo que la capa 2 debía
lograr, comprobado sin buscarlo.

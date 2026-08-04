"""
La traduccion entre `catalogo.yaml` y el analizador.

POR QUE ESTE MODULO EXISTE Y POR QUE ESTA AQUI Y NO EN EL CATALOGO
------------------------------------------------------------------
`catalogo.yaml` §7.5 lo dice: las tres primeras listas blancas (relaciones,
funciones, tipos) viven en el catalogo porque son decisiones de negocio y
seguridad, y tienen que ser revisables por alguien que no lea Python. La
cuarta —los tipos de NODO— vive aqui porque son **nombres del analizador** y
cambian si cambia sqlglot. La REGLA vive en el catalogo; la traduccion, aqui.

EL PRINCIPIO QUE GOBIERNA TODO ESTE FICHERO
-------------------------------------------
Lista blanca, no lista negra. Lo que no esta enumerado se rechaza. Si mañana
sqlglot introduce un tipo de nodo nuevo, este guardian lo RECHAZA por no
conocerlo, en vez de dejarlo pasar por no haberlo prohibido.

ALCANCE DE I-3' — SE LEVANTAN TRES RESTRICCIONES, NINGUNA CONTENCION
---------------------------------------------------------------------
I-2' rechazaba TODO `WITH`, TODA subconsulta y TODO identificador
entrecomillado: fallo cerrado maximo, deliberadamente estricto de mas. Con la
contencion ya medida (C2 = 15/15, C2' = 12/12), I-3' admite las tres formas
legitimas SIN tocar una sola regla de contencion:

  · `WITH` legitimo  -> la escritura anidada la sigue viendo S2, que recorre el
    arbol entero (M-09). La recursion la siguen viendo S5b y S5c (M-25).
  · Subconsultas      -> las relaciones las sigue recorriendo S3 en todos los
    niveles, incluidas las anidadas (M-11).
  · Identificadores entrecomillados -> ver la nota de `nucleo._identificador`.
    Es la unica de las tres que exigio trabajo real, y no por permisividad:
    por NORMALIZACION.

Ninguna regla se relaja. Lo que cambia es que tres formas dejan de rechazarse
por su TIPO, y pasan a juzgarse por su CONTENIDO — que es lo que siempre
debieron hacer.
"""

from __future__ import annotations

from sqlglot import exp

# ---------------------------------------------------------------------------
# S2 · Nodos de escritura o de definicion
# ---------------------------------------------------------------------------
# Se comprueban sobre el ARBOL COMPLETO, no sobre la raiz. Esa diferencia es
# todo el caso M-09: `WITH x AS (DELETE ...) SELECT * FROM x` tiene una raiz
# Select impecable y un nodo Delete dentro.
TIPOS_DE_ESCRITURA: tuple[type[exp.Expression], ...] = (
    exp.Delete,
    exp.Update,
    exp.Insert,
    exp.Merge,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.TruncateTable,
    exp.Grant,
    exp.Copy,
    exp.Comment,
    exp.Analyze,
    exp.Into,          # SELECT ... INTO nueva_tabla crea una tabla
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
)

# ---------------------------------------------------------------------------
# S7b · Nodos opacos o no modelados
# ---------------------------------------------------------------------------
# `Command` es el que importa: cuando sqlglot no sabe representar una sentencia
# (VACUUM, SHOW, CALL, DO $$...$$, REFRESH MATERIALIZED VIEW) NO falla — cae a
# `Command`, que guarda el TEXTO CRUDO sin analizar. Es decir: el analizador
# nos dice "esto no lo entiendo" y nos entrega la cadena.
# Dejar pasar un `Command` seria ejecutar texto sin analizar mientras se afirma
# que se analiza. Es el vector mas peligroso de esta lista y el mas facil de no
# ver, porque el analizador no lanza ninguna excepcion.
TIPOS_OPACOS: tuple[type[exp.Expression], ...] = (
    exp.Command,
    exp.Placeholder,
    exp.Parameter,
    exp.SessionParameter,
)

# ---------------------------------------------------------------------------
# S5a · Tipos de nodo permitidos
# ---------------------------------------------------------------------------
# Enumerados a partir de consultas legitimas de cartera sobre las cuatro
# vistas. Lo que no este aqui se rechaza.
#
# ADMITIDOS EN I-3', y por que ninguno abre un hueco:
#   With, CTE  -> M-09 (`WITH x AS (DELETE ...)`) lo sigue rechazando S2, que
#     recorre el arbol ENTERO y no la raiz. M-25 (`WITH RECURSIVE`) lo siguen
#     rechazando S5b —modificador `recursive` no enumerado— y S5c
#     —autorreferencia—, que es el respaldo estructural.
#   Subquery   -> M-11 (`... (SELECT ... FROM nomina_empleados)`) lo sigue
#     rechazando S3, que recorre TODAS las relaciones con `find_all`, no solo
#     las del nivel superior.
#
# NO ESTAN, Y NO SE ADMITEN AQUI:
#   Union, Except, Intersect -> ninguna pregunta del banco las necesita.
#     Admitirlas "por si acaso" seria ampliar la superficie sin caso de uso, y
#     cada tipo nuevo hay que medirlo, no suponerlo.
#   Window, Lambda, ...      -> no hacen falta para cartera.
TIPOS_PERMITIDOS: frozenset[type[exp.Expression]] = frozenset({
    # estructura de la consulta
    exp.Select, exp.From, exp.Join, exp.Where, exp.Group, exp.Having,
    exp.Order, exp.Ordered, exp.Limit, exp.Offset, exp.Distinct,
    # composicion (I-3'): se juzgan por su contenido, no por su tipo
    exp.With, exp.CTE, exp.Subquery,
    # nombres y referencias
    exp.Table, exp.TableAlias, exp.Identifier, exp.Column, exp.Alias,
    exp.Star, exp.Dot, exp.Var,
    # valores
    exp.Literal, exp.Null, exp.Boolean, exp.DataType, exp.DataTypeParam,
    # comparacion y logica que NO son Func en sqlglot
    exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE,
    exp.Is, exp.In, exp.Like, exp.ILike, exp.Between, exp.Not, exp.Paren,
    # aritmetica
    exp.Add, exp.Sub, exp.Mul, exp.Div, exp.Mod, exp.Neg,
    # AMPLIACION 2026-08-03 — `interval '1 month'`.
    #
    # POR QUE SE AMPLIA: sin este nodo, "los pagos del mes pasado" y "los
    # ultimos 30 dias" son INEXPRESABLES. No es un caso raro en cartera: es la
    # forma normal de preguntar por un periodo relativo. Se descubrio al correr
    # el banco (A-04): el modelo repreguntaba bien y el guardian tumbaba sus
    # dos opciones por S5, asi que la repregunta moria y el usuario recibia
    # "no consigo desambiguar" ante una pregunta perfectamente respondible.
    #
    # REVISION DE SEGURIDAD (R-16 exige que sea explicita y en el mismo commit):
    #
    #   1. Que contiene. Un `Interval` tiene exactamente dos hijos: un
    #      `Literal` y un `Var` con la unidad. Los DOS ya estaban permitidos y
    #      los dos siguen pasando por S5 con sus modificadores.
    #   2. No es una funcion. No hay `EXECUTE` que revocar ni sobrecarga que
    #      enumerar: es un constructor de valor del propio analizador.
    #   3. No amplia el alcance. No puede nombrar una relacion, una columna ni
    #      una funcion, asi que S3, S4 y S7 siguen viendo exactamente lo mismo.
    #      Una consulta con `interval` que toque una tabla fuera de la lista se
    #      rechaza igual, y hay prueba.
    #   4. Coste. `interval '100000 years'` desborda y el motor devuelve error
    #      —traducido por lista blanca—, y `statement_timeout` sigue en pie. No
    #      abre un vector de agotamiento que no existiera ya.
    #   5. Lo que NO se amplia, a proposito: `interval` NO entra en
    #      `tipos_permitidos`, asi que `'1 month'::interval` se sigue
    #      rechazando por S7a. Se admite la forma literal, no la conversion.
    #      La asimetria es deliberada: S7a es el unico control sin ninguna capa
    #      debajo y no se toca por comodidad.
    exp.Interval,
})

# Estos SI son subclases de `exp.Func` en sqlglot, pero NO son llamadas a
# funcion: son sintaxis. Si se trataran como funciones, `a AND b` se rechazaria
# por "funcion `and` no permitida", que seria absurdo y ademas mentiria sobre
# cual es la regla violada. Se validan como nodos, no como funciones.
FUNC_QUE_SON_SINTAXIS: frozenset[type[exp.Expression]] = frozenset({
    exp.And, exp.Or, exp.Xor, exp.Case, exp.If, exp.Cast, exp.TryCast,
})

# ---------------------------------------------------------------------------
# S4 · De clase de sqlglot a nombre canonico de PostgreSQL
# ---------------------------------------------------------------------------
# sqlglot no representa las funciones permitidas como `Anonymous`: les da una
# clase propia, y el nombre de la clase NO siempre coincide con el nombre SQL
# (`date_trunc` -> TimestampTrunc, `to_char` -> TimeToStr). Sin este mapa, la
# lista blanca del catalogo no se podria aplicar.
#
# Lo que NO este en este mapa y sea `exp.Func` se rechaza por S4. Ahi esta la
# red: `generate_series` -> ExplodingGenerateSeries y `current_user` ->
# CurrentUser tampoco son `Anonymous`, y si el guardian solo mirase los
# `Anonymous` pasarian sin que ninguna regla los viera.
MAPA_FUNCIONES: dict[type[exp.Expression], str] = {
    exp.Count: "count", exp.Sum: "sum", exp.Avg: "avg",
    exp.Min: "min", exp.Max: "max",
    exp.Lower: "lower", exp.Upper: "upper", exp.Trim: "trim",
    exp.Concat: "concat", exp.Length: "length",
    exp.Coalesce: "coalesce", exp.Nullif: "nullif",
    exp.Round: "round", exp.Abs: "abs",
    exp.Greatest: "greatest", exp.Least: "least",
    exp.Extract: "extract",
    exp.TimestampTrunc: "date_trunc",
    exp.TimeToStr: "to_char",
}

# ---------------------------------------------------------------------------
# C1 · El reloj del motor
# ---------------------------------------------------------------------------
# RN-07: el conjunto tiene fecha de corte fija y "hoy" se resuelve contra ella.
# Con `CURRENT_DATE` la respuesta correcta cambia cada dia, el valor esperado
# caduca en 24 horas y C1 (precision) deja de ser reproducible. Es un fallo
# silencioso: nadie lo nota hasta que alguien ejecuta el banco un mes despues
# y ve un porcentaje distinto al del README.
#
# No son un rechazo de seguridad: producen un REINTENTO indicando que se use
# `consulta.fecha_corte()`.
TIPOS_DE_RELOJ: tuple[type[exp.Expression], ...] = (
    exp.CurrentDate,
    exp.CurrentTime,
    exp.CurrentTimestamp,
    exp.CurrentDatetime,
)

# ---------------------------------------------------------------------------
# S5b · Modificadores permitidos
# ---------------------------------------------------------------------------
# Enumerar TIPOS de nodo no dice nada de sus MODIFICADORES, y un modificador
# puede cambiar por completo la semantica de ejecucion de un nodo que la lista
# aprueba. `WITH RECURSIVE` es el caso que lo destapo: no produce un tipo de
# nodo distinto de `WITH` — la recursion es una PROPIEDAD del nodo.
#
# Se comprueba todo argumento booleano en `True`. Lo que no este aqui se
# rechaza. La consecuencia que importa:
#   · `With.recursive` -> NO esta -> rechazado (M-25). Sigue fuera en I-3': la
#     recursion es la unica de las tres restricciones de I-2' que NO se levanta,
#     porque ninguna pregunta de cartera la necesita y su coste es un bucle en
#     el motor.
#
# `Identifier.quoted` SI entra en I-3'. En I-2' su ausencia rechazaba todo
# identificador entrecomillado, que era la restriccion buscada. Admitirlo exige
# resolver ANTES la normalizacion (ver `nucleo._identificador`): sin eso,
# `"PROPIETARIOS"` se compararia en minusculas contra la lista blanca y pasaria
# apuntando a un objeto que no es el permitido. El orden importa — primero la
# normalizacion correcta, despues el permiso.
MODIFICADORES_PERMITIDOS: frozenset[tuple[type[exp.Expression], str]] = frozenset({
    (exp.Is, "negate"),
    (exp.Literal, "is_string"),
    (exp.Ordered, "desc"),
    (exp.Ordered, "nulls_first"),
    (exp.Distinct, "on"),
    (exp.Identifier, "quoted"),   # I-3'
})

# ---------------------------------------------------------------------------
# S7a · Tipos de dato en un CAST
# ---------------------------------------------------------------------------
# sqlglot normaliza los nombres: `integer` -> INT, `numeric` -> DECIMAL. Sin
# este mapa, la lista del catalogo (escrita en nombres de PostgreSQL, que es
# como debe leerse) no casaria con nada.
#
# Los tipos NO permitidos no necesitan mapa: cualquier cosa que no aparezca
# aqui se rechaza. `regclass` es el caso que importa (M-19): no es una funcion,
# asi que no hay nada que revocar en el motor, y S7a es LA UNICA DEFENSA
# POSIBLE contra ese oraculo de existencia.
MAPA_TIPOS: dict[str, str] = {
    "INT": "integer",
    "BIGINT": "bigint",
    "DECIMAL": "numeric",
    "TEXT": "text",
    "DATE": "date",
    "TIMESTAMP": "timestamp",
    "BOOLEAN": "boolean",
}


def nombre_de_tipo(nodo_tipo: exp.Expression) -> str:
    """Nombre canonico de PostgreSQL del tipo destino de un CAST.

    El nodo NO siempre es un `DataType`: sqlglot representa `regclass`, `oid` y
    `regproc` como `ObjectIdentifier`. Justamente los tipos de identificador de
    objeto, que son los que S7a existe para rechazar. Si esta funcion asumiera
    `DataType`, fallaria con una excepcion precisamente en el caso que tiene
    que atrapar — y el fallo cerrado lo convertiria en S0, perdiendo la
    atribucion a S7.

    Devuelve el nombre crudo del analizador si no esta mapeado: asi un tipo no
    permitido se rechaza igual y ademas queda legible en la traza.
    """
    bruto = getattr(nodo_tipo, "this", nodo_tipo)
    texto = bruto.value if hasattr(bruto, "value") else str(bruto)
    return MAPA_TIPOS.get(texto.upper(), texto.lower())

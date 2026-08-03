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

ALCANCE DE I-2' — FALLO CERRADO MAXIMO, Y ES DELIBERADO
--------------------------------------------------------
En este incremento se rechaza TODO `WITH`, TODA subconsulta y TODO
identificador entrecomillado. El sistema queda **estricto de mas**: rechazara
consultas legitimas. Eso es lo correcto ahora — levantar restricciones sin
perder contencion es trabajo de I-3', y hacerlo antes de tener la contencion
probada es el orden equivocado.
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
# NO ESTAN, Y ES EL ALCANCE DE I-2':
#   With, CTE           -> todo `WITH` se rechaza (contiene M-09 y M-25)
#   Subquery            -> toda subconsulta se rechaza (contiene M-11)
#   Union, Except, Intersect -> operaciones de conjunto, a I-3'
#   Window, Lambda, ...  -> no hacen falta para cartera
TIPOS_PERMITIDOS: frozenset[type[exp.Expression]] = frozenset({
    # estructura de la consulta
    exp.Select, exp.From, exp.Join, exp.Where, exp.Group, exp.Having,
    exp.Order, exp.Ordered, exp.Limit, exp.Offset, exp.Distinct,
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
# rechaza. Dos consecuencias que valen la pena:
#   · `With.recursive`  -> no esta        -> rechazado (M-25)
#   · `Identifier.quoted` -> no esta      -> TODO identificador entrecomillado
#     queda rechazado, que es justo la restriccion de I-2'. La regla cae sola
#     de la politica en vez de necesitar un caso especial.
MODIFICADORES_PERMITIDOS: frozenset[tuple[type[exp.Expression], str]] = frozenset({
    (exp.Is, "negate"),
    (exp.Literal, "is_string"),
    (exp.Ordered, "desc"),
    (exp.Ordered, "nulls_first"),
    (exp.Distinct, "on"),
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

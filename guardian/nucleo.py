"""
El guardian: `texto SQL -> Veredicto`.

Sin red. Sin base de datos. Sin reloj. Sin aleatoriedad. Sin ficheros.
La misma entrada da siempre el mismo veredicto.

EL FALLO CERRADO ES TRIPLE, Y NO ES REDUNDANCIA
------------------------------------------------
Hay tres bloques `except Exception` y los tres van a S0. El fallo cerrado tiene
que cubrir tambien **el fallo del propio guardian**: si el analizador revienta
con una entrada rara, la respuesta correcta no es un 500 — es un rechazo.

EL ORDEN DE LAS FASES ES PARTE DE LA SEGURIDAD
-----------------------------------------------
Los topes de la fase 0 se aplican SOBRE LA CADENA CRUDA, antes de parsear: el
trabajo caro no empieza nunca con una entrada disparatada. M-24 —1950
parentesis anidados— agota el analizador antes de que exista un arbol que
medir, asi que un tope sobre el arbol llegaria tarde por definicion.
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp

from .catalogo import Catalogo
from .contrato import (
    LIMITE_FILAS,
    TOPE_LONGITUD,
    TOPE_NODOS,
    TOPE_PROFUNDIDAD,
    TOPE_PROFUNDIDAD_CRUDA,
    Veredicto,
    incoherente,
    permitido,
    rechazo,
)
from .politica import (
    FUNC_QUE_SON_SINTAXIS,
    MAPA_FUNCIONES,
    MODIFICADORES_PERMITIDOS,
    TIPOS_DE_ESCRITURA,
    TIPOS_DE_RELOJ,
    TIPOS_OPACOS,
    TIPOS_PERMITIDOS,
    nombre_de_tipo,
)

DIALECTO = "postgres"


def veredicto(sql: str, catalogo: Catalogo) -> Veredicto:
    # `eco` se fija aqui, en la primera linea, y NO SE REASIGNA NUNCA MAS.
    # Es literal y completo. Si se resolviera un nombre estariamos AÑADIENDO
    # informacion que quien pregunta no tenia; si se truncara, la bitacora
    # perderia evidencia. T-9 lo comprueba caracter por caracter.
    eco = sql

    # ===== FASE 0 — antes de parsear, sobre la CADENA CRUDA ==============
    if not isinstance(sql, str):
        return rechazo("S0", eco if isinstance(eco, str) else "")
    if len(sql) > TOPE_LONGITUD:
        return rechazo("S6", eco)
    if _profundidad_de_parentesis(sql) > TOPE_PROFUNDIDAD_CRUDA:
        return rechazo("S6", eco)

    # ===== FASE 1 — parseo con fallo cerrado TOTAL =======================
    try:
        sentencias = sqlglot.parse(sql, dialect=DIALECTO)
    except Exception:  # noqa: BLE001 — el fallo cerrado es el objetivo
        return rechazo("S0", eco)

    # `parse` devuelve None para una sentencia vacia y un nodo Semicolon para
    # un `;` suelto. Ninguno de los dos es una consulta.
    sentencias = [
        s for s in sentencias if s is not None and not isinstance(s, exp.Semicolon)
    ]
    if not sentencias:
        return rechazo("S0", eco)
    if len(sentencias) != 1:
        return rechazo("S1", eco)
    raiz = sentencias[0]

    # ===== FASE 2 — topes sobre el arbol ya construido ===================
    # El calculo de la profundidad va DENTRO del try, y no es un detalle: la
    # primera version lo dejo fuera y un fallo del recorrido subio como
    # excepcion en vez de producir un rechazo. El fallo cerrado tiene que
    # cubrir tambien el fallo del propio guardian (ADR-16).
    try:
        nodos = list(raiz.walk())
        if len(nodos) > TOPE_NODOS:
            return rechazo("S6", eco)
        if _profundidad_del_arbol(raiz) > TOPE_PROFUNDIDAD:
            return rechazo("S6", eco)
    except Exception:  # noqa: BLE001
        return rechazo("S0", eco)

    # ===== FASES 3 a 5 — UNA PASADA POR REGLA, EN EL ORDEN DE LA REGLA ===
    #
    # POR QUE UNA PASADA POR REGLA Y NO UN RECORRIDO UNICO CON TODOS LOS
    # CONTROLES DENTRO. Un recorrido unico atribuye la carga a la regla del
    # PRIMER NODO que choca, no a la primera regla del orden. Con esa forma,
    # M-09 —`WITH x AS (DELETE ...) SELECT * FROM x`— salia rechazado por S5,
    # porque el nodo `WITH` aparece antes que el `DELETE` y en este incremento
    # todo `WITH` esta prohibido. Quedaba contenido, si; pero por el motivo
    # equivocado, y M-09 existe justamente para demostrar que el guardian VE LA
    # ESCRITURA ANIDADA. En I-3', al admitirse `WITH` legitimo, esa prueba
    # habria pasado de verde a roja sin que nadie hubiera tocado S2.
    #
    # Una prueba que pasa por el motivo equivocado enmascara la regresion del
    # control que dice estar midiendo. Por eso el orden de evaluacion se
    # implementa como orden de REGLAS.
    #
    # DESVIACION DECLARADA respecto del orden literal S2->S3->S4->S5->S7:
    # S7b (nodo opaco) se evalua justo despues de S2, antes que S3/S4/S5.
    # Motivo: un nodo opaco es aquel que EL ANALIZADOR NO SUPO REPRESENTAR
    # —`Command` guarda el texto crudo sin analizar—. Comprobar contra el una
    # lista blanca de relaciones o de funciones seria afirmar que la politica
    # examino algo que nunca se llego a analizar. S7a (tipo de un CAST) si
    # queda al final, en su sitio. Va a `architect-agent`.
    usa_reloj = any(isinstance(n, TIPOS_DE_RELOJ) for n in nodos)

    try:
        # --- S2 · escritura o definicion, en CUALQUIER nivel del arbol ----
        # Es todo el caso M-09: la raiz es un SELECT impecable y el DELETE esta
        # dentro. Un guardian que mire el prefijo del texto lo deja pasar.
        for nodo in nodos:
            if isinstance(nodo, TIPOS_DE_ESCRITURA):
                return rechazo("S2", eco)

        # --- S7b · nodos opacos o no modelados ---------------------------
        for nodo in nodos:
            if isinstance(nodo, TIPOS_OPACOS):
                return rechazo("S7", eco)

        # A partir de aqui la raiz tiene que ser una consulta.
        if not isinstance(raiz, exp.Select):
            return rechazo("S2", eco)

        # --- S3 · relaciones, en todos los niveles -----------------------
        # `find_all` recorre TODOS los niveles, no solo el superior. Es lo que
        # sostiene M-11: la consulta externa es impecable y el escape esta en
        # una subconsulta anidada. Al admitirse subconsultas en I-3', esta
        # propiedad pasa de ser prudente a ser imprescindible.
        #
        # Los nombres definidos por la propia consulta —CTE y subconsultas con
        # alias— se RESTAN: no son relaciones del esquema y exigirles estar en
        # la lista blanca rechazaria toda consulta compuesta legitima. Restarlos
        # no abre nada: un CTE solo puede leer de lo que el mismo autorizo, y su
        # contenido lo recorre igualmente este bucle.
        definidas_aqui = {
            nombre
            for nombre in (
                [_alias_efectivo(c) for c in raiz.find_all(exp.CTE)]
                + [_alias_efectivo(s) for s in raiz.find_all(exp.Subquery)]
            )
            if nombre
        }
        for tabla in raiz.find_all(exp.Table):
            esquema = _identificador(tabla.args.get("db"))
            nombre = _identificador(tabla.this)
            if not esquema and nombre in definidas_aqui:
                continue
            if tabla.catalog:
                return rechazo("S3", eco)      # otra base de datos
            if not catalogo.relacion_permitida(
                esquema or Catalogo.ESQUEMA_POR_DEFECTO, nombre
            ):
                return rechazo("S3", eco)      # M-06, M-11, M-12

        # --- S4 · funciones, lista blanca EXPLICITA ----------------------
        for nodo in nodos:
            if not isinstance(nodo, exp.Func) or type(nodo) in FUNC_QUE_SON_SINTAXIS:
                continue
            if isinstance(nodo, TIPOS_DE_RELOJ):
                continue               # lo resuelve C1, no S4 (ver fase 6)
            nombre, esquema = _nombre_de_funcion(nodo)
            if nombre is None:
                return rechazo("S4", eco)  # clase de funcion que no se sabe nombrar
            if not catalogo.funcion_permitida(nombre, esquema):
                return rechazo("S4", eco)  # M-16, M-18, M-20..M-23, M-32, M-34

        # El tipo destino de un CAST lo juzga S7a, no S5a. Sin esta exclusion,
        # `'cartera.propietarios'::regclass` (M-19) saldria rechazado por S5
        # —sqlglot representa `regclass` como `ObjectIdentifier`, que no esta
        # en la lista de nodos— y S7a no llegaria a ejecutarse nunca. Seria
        # codigo muerto presentado en el README como "la unica defensa posible
        # contra el oraculo de existencia". Cada regla juzga lo suyo.
        objetivos_de_cast = {
            id(descendiente)
            for nodo in nodos
            if isinstance(nodo, (exp.Cast, exp.TryCast))
            for descendiente in nodo.to.walk()
        }

        # --- S5a · tipo de nodo ------------------------------------------
        for nodo in nodos:
            if id(nodo) in objetivos_de_cast:
                continue                       # lo juzga S7a
            if isinstance(nodo, exp.Func) and type(nodo) not in FUNC_QUE_SON_SINTAXIS:
                continue                       # ya lo juzgo S4
            if type(nodo) in FUNC_QUE_SON_SINTAXIS:
                continue                       # AND, OR, CASE, IF, CAST: sintaxis
            if type(nodo) not in TIPOS_PERMITIDOS:
                return rechazo("S5", eco)      # WITH, subconsultas, UNION...

        # --- S5b · modificadores -----------------------------------------
        # Enumerar tipos de nodo no dice nada de sus modificadores, y un
        # modificador puede cambiar por completo la semantica de ejecucion de
        # un nodo que la lista aprueba. Aqui caen `WITH RECURSIVE` y todo
        # identificador entrecomillado, sin necesitar un caso especial.
        #
        # NO se aplica a las funciones, y la razon no es comodidad: las
        # funciones las gobierna S4 POR NOMBRE, y sus banderas internas son
        # detalle de representacion del analizador, no sintaxis SQL. sqlglot
        # marca `count(*)` con `big_int=True`; exigir que esa bandera este
        # enumerada obligaria a mantener la lista de las interioridades de cada
        # funcion permitida, y rechazaria `count(*)`. Lo que si cambia la
        # semantica de una llamada —`DISTINCT`, `FILTER`, una ventana— NO es
        # una bandera: son nodos propios, y esos los ve S5a.
        for nodo in nodos:
            if id(nodo) in objetivos_de_cast or isinstance(nodo, exp.Func):
                continue
            for modificador in _modificadores(nodo):
                if (type(nodo), modificador) not in MODIFICADORES_PERMITIDOS:
                    return rechazo("S5", eco)

        # --- S5c · autorreferencia ---------------------------------------
        # La autorreferencia es LA PROPIEDAD que hace recursiva a una consulta;
        # `RECURSIVE` es solo la palabra que el motor exige para declararla.
        # Este criterio es puramente estructural: no depende de ninguna bandera
        # del analizador, asi que sostiene la regla aunque sqlglot deje de
        # exponer la propiedad. Si S5b fallara, esto basta solo.
        for cte in raiz.find_all(exp.CTE):
            nombre = (cte.alias or "").lower()
            if not nombre:
                continue
            for tabla in cte.this.find_all(exp.Table):
                if tabla.name.lower() == nombre and not tabla.db:
                    return rechazo("S5", eco)  # M-25

        # --- S7a · tipo destino de un CAST -------------------------------
        # M-19: `'cartera.propietarios'::regclass` no es una funcion, asi que
        # no hay nada que revocar en el motor. Esta es la unica defensa
        # posible, y es el unico control del sistema sin ninguna capa debajo.
        for nodo in nodos:
            if isinstance(nodo, (exp.Cast, exp.TryCast)):
                if not catalogo.tipo_permitido(nombre_de_tipo(nodo.to)):
                    return rechazo("S7", eco)

    except Exception:  # noqa: BLE001
        return rechazo("S0", eco)

    # ===== FASE 6 — coherencia: producen REINTENTO, no rechazo ===========
    if usa_reloj:
        return incoherente("C1", eco)

    # C2 · un LIMIT propio mayor que el del sistema se elimina, no se respeta.
    # M-14 pide "todas las filas, no me recortes nada": el limite es un control
    # del sistema, no una preferencia que el modelo pueda ceder.
    try:
        limite = raiz.args.get("limit")
        if limite is not None:
            valor = _valor_entero(limite)
            if valor is None or valor > LIMITE_FILAS:
                raiz.set("limit", None)
    except Exception:  # noqa: BLE001
        return rechazo("S0", eco)

    # ===== SALIDA — se ejecuta el ARBOL VALIDADO, no el texto original ====
    # Lo que llega al motor es la reserializacion de lo que se acaba de
    # analizar. Asi "lo que se ejecuta es lo que analice" es cierto por
    # construccion y no por confianza. Es cierto ESTRUCTURALMENTE, no
    # semanticamente: no protege del SQL que viaje dentro de un literal, y ese
    # caso lo cierran S4 y la revocacion en el motor.
    try:
        sql_validado = raiz.sql(dialect=DIALECTO)
    except Exception:  # noqa: BLE001
        return rechazo("S0", eco)

    sql_final = f"SELECT * FROM ({sql_validado}) AS _acotado LIMIT {LIMITE_FILAS + 1}"
    return permitido(sql_final, eco)


# ---------------------------------------------------------------------------
# Auxiliares — puros, sin estado
# ---------------------------------------------------------------------------

def _profundidad_de_parentesis(sql: str) -> int:
    """Profundidad maxima de parentesis sobre la cadena CRUDA.

    Deliberadamente tosco: cuenta tambien los parentesis dentro de literales.
    Es un tope de fase 0 y su unico trabajo es que una entrada disparatada no
    llegue al analizador. Una consulta de cartera legitima no acumula 25
    parentesis abiertos ni dentro de una cadena.
    """
    profundidad = maxima = 0
    for caracter in sql:
        if caracter == "(":
            profundidad += 1
            if profundidad > maxima:
                maxima = profundidad
                if maxima > TOPE_PROFUNDIDAD_CRUDA:
                    return maxima          # no hace falta seguir contando
        elif caracter == ")":
            profundidad -= 1
    return maxima


def _profundidad_del_arbol(raiz: exp.Expression) -> int:
    profundidad = 0
    for nodo in raiz.walk():
        actual, altura = nodo, 0
        while actual.parent is not None:
            altura += 1
            actual = actual.parent
            if altura > TOPE_PROFUNDIDAD:
                return altura
        profundidad = max(profundidad, altura)
    return profundidad


def _identificador(nodo) -> str:
    """Nombre EFECTIVO de un identificador, segun la regla real de PostgreSQL.

    Sin comillas, PostgreSQL pliega el identificador a minusculas: `Propietarios`
    y `propietarios` son el MISMO objeto. Entrecomillado, lo usa literal:
    `"Propietarios"` es un objeto DISTINTO de `propietarios`.

    POR QUE ESTO ES UNA REGLA DE SEGURIDAD Y NO UNA CORTESIA
    --------------------------------------------------------
    Hasta I-2' daba igual, porque todo identificador entrecomillado se
    rechazaba. Al admitirlos en I-3', normalizar siempre a minusculas —que es
    lo que hacia el codigo anterior— crearia un hueco real:

        SELECT * FROM "PROPIETARIOS"

    se compararia como `propietarios`, PASARIA la lista blanca, y el SQL
    reserializado conservaria las comillas y llegaria al motor apuntando a un
    objeto que la lista blanca NUNCA autorizo. La lista blanca diria que si
    sobre una tabla, y el motor ejecutaria sobre otra.

    Con esta funcion, `"PROPIETARIOS"` conserva sus mayusculas, no coincide con
    ninguna entrada de la lista blanca —que esta escrita en minusculas— y se
    rechaza por S3. Y `"propietarios"` si coincide, que tambien es correcto:
    entrecomillado en minusculas es el mismo objeto.

    El permiso de I-3' no es "acepta comillas": es "trata las comillas como las
    trata el motor". Sin esa distincion, el permiso habria sido un agujero.
    """
    if nodo is None:
        return ""
    if isinstance(nodo, str):
        return nodo.lower()
    if getattr(nodo, "quoted", False):
        return nodo.name
    return nodo.name.lower()


def _alias_efectivo(nodo: exp.Expression) -> str:
    """Alias que un CTE o una subconsulta declara, con la misma normalizacion.

    Tiene que usar EXACTAMENTE la misma regla que `_identificador`: si los
    nombres definidos se normalizaran de una forma y las tablas de otra, un
    alias entrecomillado dejaria de restarse y la consulta legitima que lo usa
    se rechazaria por S3 — un falso positivo nacido de dos normalizaciones que
    no coinciden.
    """
    alias = nodo.args.get("alias")
    if alias is None:
        return ""
    return _identificador(getattr(alias, "this", alias))


def _modificadores(nodo: exp.Expression):
    """Argumentos booleanos activos del nodo.

    Solo se miran los que valen exactamente `True`: un modificador apagado no
    cambia la semantica de ejecucion y rechazarlo produciria falsos positivos
    sin ganar nada.
    """
    for clave, valor in nodo.args.items():
        if valor is True:
            yield clave


def _nombre_de_funcion(nodo: exp.Expression) -> tuple[str | None, str | None]:
    """Nombre canonico de una invocacion de funcion, y su esquema si lo lleva.

    Devuelve `(None, None)` si la clase no esta mapeada. Eso es fallo cerrado:
    una funcion que el guardian no sabe nombrar no se puede autorizar.
    """
    if isinstance(nodo, exp.Anonymous):
        nombre = nodo.this
        nombre = (nombre if isinstance(nombre, str) else getattr(nombre, "name", "")).lower()
        # `consulta.fecha_corte()` se representa como Dot(Identifier, Anonymous):
        # el esquema esta en el padre, no en el nodo de la funcion.
        padre = nodo.parent
        if isinstance(padre, exp.Dot) and isinstance(padre.this, exp.Identifier):
            return nombre, padre.this.name.lower()
        return nombre, None
    nombre = MAPA_FUNCIONES.get(type(nodo))
    return (nombre, None) if nombre else (None, None)


def _valor_entero(nodo: exp.Expression) -> int | None:
    try:
        return int(nodo.expression.name)
    except Exception:  # noqa: BLE001
        return None

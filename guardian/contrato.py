"""
Contrato del guardian: el veredicto, los mensajes fijos y los topes.

TODO LO QUE HAY AQUI ES DATO INMUTABLE. Ni una decision, ni una consulta, ni
una llamada a nada. Se separa del nucleo para que el contrato se pueda leer sin
leer la implementacion — y para que cambiarlo salte a la vista en un diff.
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Topes
# ---------------------------------------------------------------------------

# Longitud maxima de la cadena cruda. Coincide con el maximo de entrada de la
# API a proposito: por encima de eso la peticion no llega aqui (produce 422).
# Este tope existe para el caso en que el guardian se invoque desde otro sitio.
TOPE_LONGITUD = 4000

# Profundidad maxima de parentesis, contada SOBRE LA CADENA CRUDA, antes de
# parsear. Es la defensa del guardian contra si mismo (M-24: 1950 parentesis
# anidados agotan el analizador ANTES de que exista un arbol que medir).
# 25 es holgado: una consulta de cartera sobre cuatro vistas planas no pasa de
# 6. [A] El numero es juicio, no medicion.
TOPE_PROFUNDIDAD_CRUDA = 25

# Topes sobre el arbol ya construido (fase 2).
TOPE_NODOS = 400
TOPE_PROFUNDIDAD = 40

# Limite de filas que el sistema impone. Se pide una fila de mas para poder
# decir "hay mas" sin un COUNT(*) que sobre M-13 expiraria.
LIMITE_FILAS = 100

# ---------------------------------------------------------------------------
# Mensajes — texto FIJO por regla
# ---------------------------------------------------------------------------
#
# S3, S4, S5 y S7 comparten EXACTAMENTE el mismo texto, y no es un descuido:
# es el requisito RF-12. Un texto distinto le diria a quien ataca QUE MECANISMO
# TOCO —si dio con la lista de tablas, con la de funciones o con la de tipos—,
# y eso convierte cada rechazo en una respuesta gratis sobre lo que hay detras.
# Lo unico que difiere es el identificador `regla`, que viaja en la respuesta y
# NO en el texto que ve el usuario: es un oraculo de politica aceptado y
# declarado, porque sin el dos reglas distintas serian indistinguibles tambien
# para quien audita el sistema.
#
# Ningun mensaje nombra jamas un objeto, una columna, un esquema ni una version.

_FUERA_DE_ALCANCE = "Eso está fuera de lo que puedo consultar."

MENSAJES: dict[str, str] = {
    "S0": "No entiendo esta consulta.",
    "S1": "Solo puedo ejecutar una consulta a la vez.",
    "S2": "Este sistema solo consulta datos, no los modifica.",
    "S3": _FUERA_DE_ALCANCE,
    "S4": _FUERA_DE_ALCANCE,
    "S5": _FUERA_DE_ALCANCE,
    "S6": "Esa consulta es demasiado grande para poder revisarla.",
    "S7": _FUERA_DE_ALCANCE,
    # C1 no es un rechazo de seguridad: es una regla de coherencia que produce
    # un reintento. Por eso su texto SI puede ser especifico — no revela nada
    # sobre el esquema, solo sobre una convencion del conjunto de datos.
    "C1": (
        "Los datos tienen una fecha de corte fija. No puedo usar la fecha de hoy "
        "del servidor: hay que consultar contra la fecha de corte."
    ),
}

# Reglas de seguridad: NUNCA se reintentan. Un reintento sobre un rechazo de
# seguridad es una segunda oportunidad para quien ataca.
REGLAS_DE_SEGURIDAD = frozenset({"S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7"})
REGLAS_DE_COHERENCIA = frozenset({"C1", "C2"})


@dataclass(frozen=True)
class Veredicto:
    """Lo que el guardian devuelve. Inmutable a proposito.

    `eco` es LITERAL y COMPLETO: la entrada tal cual llego, sin resolver, sin
    normalizar, sin cualificar y SIN TRUNCAR.

    - Si devolviera el nombre *resuelto* estaria AÑADIENDO informacion que quien
      pregunta no tenia, y eso es una fuga (RF-12).
    - Si lo truncara, la bitacora perderia evidencia (RF-11). El truncado es
      politica de presentacion y vive en la API, no aqui.

    T-9 lo comprueba caracter por caracter.
    """

    permitido: bool
    regla: str | None = None
    mensaje: str | None = None
    eco: str = ""
    sql_a_ejecutar: str | None = None

    @property
    def admite_reintento(self) -> bool:
        """Solo las reglas de coherencia. Nunca las de seguridad."""
        return self.regla in REGLAS_DE_COHERENCIA


def rechazo(regla: str, eco: str) -> Veredicto:
    return Veredicto(permitido=False, regla=regla, mensaje=MENSAJES[regla], eco=eco)


def incoherente(regla: str, eco: str) -> Veredicto:
    """No es un rechazo de seguridad: produce un reintento (k <= 2)."""
    return Veredicto(permitido=False, regla=regla, mensaje=MENSAJES[regla], eco=eco)


def permitido(sql_a_ejecutar: str, eco: str) -> Veredicto:
    return Veredicto(permitido=True, eco=eco, sql_a_ejecutar=sql_a_ejecutar)

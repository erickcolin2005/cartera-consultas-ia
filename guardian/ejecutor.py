"""
El ejecutor: `Veredicto -> Resultado`. Es el unico modulo que toca la red.

POR QUE ESTA SEPARADO DEL GUARDIAN
-----------------------------------
El guardian es puro: misma entrada, mismo veredicto, sin red ni reloj. Esa
pureza es lo que permite probarlo entero sin levantar nada. En cuanto el
guardian abriera una conexion, esa propiedad se perderia y T-1 pasaria a
necesitar una base de datos para correr.

CONEXION NUEVA POR CONSULTA — NO HAY POOL, Y ES DELIBERADO (ADR-15)
--------------------------------------------------------------------
Un pool arrastra estado entre peticiones: parametros de sesion, roles,
temporales. Con `DISCARD ALL` se limpia, pero **un control cuyo olvido es
silencioso es peor que no necesitarlo**. Sin pool no hay nada que limpiar.

Y hay una segunda razon, que es la que hace medible la pantalla: sin pool,
"ninguna sentencia llego a la base" significa exactamente lo que un lector
entiende. Con pool habria que explicar de que conexion se habla.

Coste declarado: abrir conexion por consulta es mas lento y consume una del
cupo. Por eso el rol lleva `CONNECTION LIMIT 10` — el mamparo que sustituye al
que daba el pool.

EL CONTADOR VIVE EN EL BORDE, NO EN EL EJECUTOR
------------------------------------------------
`sentencias_enviadas` envuelve el cursor y cuenta cada `execute`. Si el contador
viviera en esta funcion seria tautologico: contaria las veces que decidimos
contar. Envolviendo el cursor cuenta lo que de verdad sale hacia el motor,
incluido lo que enviara cualquier codigo futuro que use el mismo cursor.

Y NO puede ser propiedad del cursor: en un rechazo no se crea cursor, asi que
un contador del cursor daria cero por no existir nunca — un cero vacio,
indistinguible del cero bueno. Por eso es de la peticion.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import psycopg

from .contrato import LIMITE_FILAS, Veredicto


@dataclass
class Contador:
    """Cuenta sentencias enviadas al motor. De la peticion, no del cursor."""

    sentencias_enviadas: int = 0
    conexiones_abiertas: int = 0


class _CursorContado:
    """Envoltorio del cursor. Su unico trabajo es contar antes de delegar.

    Deliberadamente tonto: si tuviera logica, seria un sitio donde el conteo y
    la ejecucion podrian separarse. Aqui no pueden.
    """

    def __init__(self, cursor, contador: Contador):
        self._cursor = cursor
        self._contador = contador

    def execute(self, consulta, parametros=None):
        self._contador.sentencias_enviadas += 1
        return self._cursor.execute(consulta, parametros)

    def __getattr__(self, nombre):
        return getattr(self._cursor, nombre)


@dataclass
class Resultado:
    """Lo que se pudo observar al ejecutar. Incluye lo que NO paso."""

    columnas: list[str] = field(default_factory=list)
    filas: list[tuple] = field(default_factory=list)
    hay_mas: bool = False
    sentencias_enviadas: int = 0
    error: str | None = None
    ms: int = 0


# Mensajes de error del motor: LISTA BLANCA, nunca el texto crudo.
#
# El texto del motor nombra objetos, columnas y a veces la version. Devolverlo
# convertiria cada error en un oraculo: "columna inexistente" frente a "columna
# no publicada" son dos hechos distintos que el atacante no deberia distinguir.
# Por eso ambos caen en la MISMA fila generica.
_ERRORES: dict[str, str] = {
    "42501": "Eso está fuera de lo que puedo consultar.",
    "42P01": "Eso está fuera de lo que puedo consultar.",
    "42703": "Eso está fuera de lo que puedo consultar.",
    "57014": "La consulta tardó demasiado y se detuvo.",
    "53300": "Hay demasiadas consultas a la vez. Intenta de nuevo en un momento.",
}
_ERROR_GENERICO = "No pude completar la consulta."


def ejecutar(v: Veredicto, url: str | None = None) -> Resultado:
    """Ejecuta el SQL VALIDADO. Nunca el texto original.

    Si el veredicto no es `permitido`, esta funcion no abre nada y devuelve un
    resultado con `sentencias_enviadas = 0`. Ese cero es el que la pantalla
    muestra, y es medido: no es una constante escrita a mano.
    """
    contador = Contador()
    if not v.permitido or not v.sql_a_ejecutar:
        return Resultado(sentencias_enviadas=0)

    url = url or os.environ.get("DATABASE_URL_RO", "")
    if not url:
        return Resultado(error="Falta la configuración de la base de datos.")

    import time

    inicio = time.monotonic()
    try:
        # Conexion nueva, y se cierra sola al salir del bloque.
        with psycopg.connect(url, connect_timeout=5) as conexion:
            contador.conexiones_abiertas += 1
            with conexion.cursor() as crudo:
                cursor = _CursorContado(crudo, contador)
                cursor.execute(v.sql_a_ejecutar)
                columnas = [d.name for d in cursor.description or []]
                filas = cursor.fetchall()
    except psycopg.Error as e:
        codigo = getattr(e, "sqlstate", None) or ""
        return Resultado(
            error=_ERRORES.get(codigo, _ERROR_GENERICO),
            sentencias_enviadas=contador.sentencias_enviadas,
            ms=int((time.monotonic() - inicio) * 1000),
        )
    except Exception:  # noqa: BLE001 — nada del motor sube crudo al usuario
        return Resultado(
            error=_ERROR_GENERICO,
            sentencias_enviadas=contador.sentencias_enviadas,
            ms=int((time.monotonic() - inicio) * 1000),
        )

    # Se pidio una fila de mas para saber si hay mas SIN un COUNT(*), que sobre
    # un producto cartesiano expiraria por timeout antes de responder.
    hay_mas = len(filas) > LIMITE_FILAS
    return Resultado(
        columnas=columnas,
        filas=filas[:LIMITE_FILAS],
        hay_mas=hay_mas,
        sentencias_enviadas=contador.sentencias_enviadas,
        ms=int((time.monotonic() - inicio) * 1000),
    )

"""
Adaptadores falsos. Sin red, sin coste, deterministas.

PARA QUE SIRVEN
----------------
Todo el flujo de I-4 —contrato, guardian sobre cada opcion, reintentos, los
cinco desenlaces— se puede medir sin llamar a nadie. Solo la calidad de la
traduccion necesita el proveedor de verdad.

Esa separacion no es comodidad: es lo que permite que T-3 y T-4 corran en el
CI, en cada push, gratis y sin depender de que un tercero este en pie.

EL HOSTIL ES EL QUE IMPORTA
----------------------------
`Hostil` devuelve exactamente lo que devolveria un modelo comprometido o
servil: SQL destructivo, con la forma correcta del contrato. Sirve para
comprobar que el sistema no lo ejecuta **y que no lo reintenta**, que es la
mitad que se olvida.
"""

from __future__ import annotations

import json

from ia.orquestador import ProveedorCaido


class Cooperador:
    """Responde lo que se le diga, en orden. El adaptador de referencia."""

    def __init__(self, *respuestas: str):
        self.respuestas = list(respuestas)
        self.llamadas = 0
        self.pistas: list[str | None] = []
        self.contextos: list[str] = []

    def preguntar(self, contexto: str, pregunta: str, pista: str | None = None) -> str:
        self.llamadas += 1
        self.pistas.append(pista)
        self.contextos.append(contexto)
        if not self.respuestas:
            raise AssertionError("El adaptador falso se quedó sin respuestas.")
        return self.respuestas.pop(0)


class Hostil:
    """Devuelve SQL destructivo con la forma correcta del contrato.

    Que la FORMA sea correcta es el punto: un adaptador que devolviera basura
    se pararia en el contrato y no llegaria nunca al guardian, que es lo que
    hay que probar.
    """

    def __init__(self, sql: str):
        self.sql = sql
        self.llamadas = 0

    def preguntar(self, contexto: str, pregunta: str, pista: str | None = None) -> str:
        self.llamadas += 1
        return json.dumps(
            {
                "tipo": "consulta",
                "sql": self.sql,
                "interpretacion": "lo que me pediste",
            }
        )


class Caido:
    """No responde. F-5."""

    def __init__(self) -> None:
        self.llamadas = 0

    def preguntar(self, contexto: str, pregunta: str, pista: str | None = None) -> str:
        self.llamadas += 1
        raise ProveedorCaido("el proveedor no respondió")


def consulta(sql: str, interpretacion: str = "una interpretación") -> str:
    return json.dumps(
        {"tipo": "consulta", "sql": sql, "interpretacion": interpretacion}
    )


def ambigua(*sqls: str, pregunta: str = "¿En qué sentido?") -> str:
    return json.dumps(
        {
            "tipo": "ambigua",
            "pregunta": pregunta,
            "opciones": [
                {"id": chr(97 + i), "texto": f"lectura {chr(97 + i)}", "sql": s}
                for i, s in enumerate(sqls)
            ],
        }
    )


def sin_datos(falta: str) -> str:
    return json.dumps(
        {
            "tipo": "sin_datos",
            "falta": falta,
            "disponibles": ["unidades", "propietarios", "cuotas", "pagos"],
        }
    )

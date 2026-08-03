"""
El contrato de salida del modelo. Tres tipos, validacion estricta, sin red.

POR QUE LA VALIDACION ES ESTRICTA Y NO "TOLERANTE"
---------------------------------------------------
La tentacion es aceptar lo que se parezca: si falta `interpretacion`, poner
cadena vacia; si `opciones` trae una sola, mostrarla igual. Cada una de esas
concesiones convierte un fallo visible en un comportamiento raro.

Aqui lo que no cumple el contrato se rechaza y produce **un reintento** (F-1),
y si el segundo tampoco cumple, un mensaje fijo. `k <= 2` siempre.

LO QUE ESTE MODULO NO HACE, Y ES DELIBERADO
--------------------------------------------
**No valida el SQL.** Ni lo mira. El SQL que venga aqui pasa despues por el
guardian, entero, como si lo hubiera escrito un desconocido — porque a efectos
de contencion eso es exactamente lo que es. Si este modulo empezara a opinar
sobre el SQL, habria dos sitios decidiendo lo mismo y uno de los dos se
quedaria atras.

**No toca la red.** Recibe texto y devuelve una estructura.

EL TIPO `ambigua` Y SU REGLA MENOS OBVIA
-----------------------------------------
Cada opcion llega con su SQL ya generado, en la misma llamada. Eso hace que
elegir una opcion no cueste otra llamada, asi que repreguntar no es mas caro
que responder: **D-B no esta penalizado economicamente**, y esa es la razon de
que el diseño lo pidiera asi.

La consecuencia importante viene despues, en el orquestador: cada SQL de cada
opcion pasa por el guardian ANTES de enseñarse, y las que no pasan se
descartan. Si quedan menos de dos, no se repregunta — una repregunta con una
sola opcion es un callejon.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

TIPOS = ("consulta", "ambigua", "sin_datos")

# Tope de opciones. No es estetico: cada opcion lleva su SQL, y cada SQL pasa
# por el guardian. Sin tope, una salida desbocada del modelo se convierte en
# trabajo de validacion sin limite.
MAX_OPCIONES = 4
MIN_OPCIONES = 2


class ContratoRoto(ValueError):
    """La salida no cumple el contrato. Produce reintento (F-1), no un fallo."""


@dataclass(frozen=True)
class Opcion:
    id: str
    texto: str
    sql: str


@dataclass(frozen=True)
class Respuesta:
    """Lo que el modelo dijo, ya validado en FORMA. No en contenido."""

    tipo: str
    sql: str | None = None
    interpretacion: str | None = None
    pregunta: str | None = None
    opciones: tuple[Opcion, ...] = ()
    falta: str | None = None
    disponibles: tuple[str, ...] = ()


def _texto(d: dict, clave: str) -> str:
    valor = d.get(clave)
    if not isinstance(valor, str) or not valor.strip():
        raise ContratoRoto(f"falta `{clave}` o no es texto")
    return valor.strip()


def interpretar(crudo: str) -> Respuesta:
    """Texto del modelo -> `Respuesta`. Lanza `ContratoRoto` si no cumple.

    Acepta que el texto venga envuelto en un bloque de codigo: es el desvio
    mas comun y no merece gastar un reintento. Cualquier otra desviacion si
    lo merece — ser tolerante con las demas seria empezar a adivinar.
    """
    texto = crudo.strip()
    if texto.startswith("```"):
        texto = texto.split("\n", 1)[-1] if "\n" in texto else texto
        texto = texto.rsplit("```", 1)[0].strip()

    try:
        d = json.loads(texto)
    except json.JSONDecodeError as e:
        raise ContratoRoto(f"no es JSON: {e}") from e

    if not isinstance(d, dict):
        raise ContratoRoto("la raíz no es un objeto")

    tipo = d.get("tipo")
    if tipo not in TIPOS:
        raise ContratoRoto(f"`tipo` es {tipo!r}, y solo vale uno de {TIPOS}")

    if tipo == "consulta":
        return Respuesta(
            tipo=tipo,
            sql=_texto(d, "sql"),
            interpretacion=_texto(d, "interpretacion"),
        )

    if tipo == "sin_datos":
        disponibles = d.get("disponibles") or []
        if not isinstance(disponibles, list) or not all(
            isinstance(x, str) for x in disponibles
        ):
            raise ContratoRoto("`disponibles` no es una lista de textos")
        return Respuesta(
            tipo=tipo, falta=_texto(d, "falta"), disponibles=tuple(disponibles)
        )

    # ambigua
    crudas = d.get("opciones")
    if not isinstance(crudas, list):
        raise ContratoRoto("`opciones` no es una lista")
    if not MIN_OPCIONES <= len(crudas) <= MAX_OPCIONES:
        raise ContratoRoto(
            f"`opciones` trae {len(crudas)}; el contrato pide entre "
            f"{MIN_OPCIONES} y {MAX_OPCIONES}"
        )

    opciones = []
    vistos = set()
    for i, o in enumerate(crudas):
        if not isinstance(o, dict):
            raise ContratoRoto(f"la opción {i} no es un objeto")
        opcion = Opcion(id=_texto(o, "id"), texto=_texto(o, "texto"), sql=_texto(o, "sql"))
        if opcion.id in vistos:
            # Dos opciones con el mismo id hacen imposible saber cual eligio
            # el usuario. Es un fallo de forma, no una preferencia.
            raise ContratoRoto(f"el id de opción {opcion.id!r} está repetido")
        vistos.add(opcion.id)
        opciones.append(opcion)

    return Respuesta(
        tipo=tipo, pregunta=_texto(d, "pregunta"), opciones=tuple(opciones)
    )


# ---------------------------------------------------------------------------
# El esquema que se le impone al proveedor
# ---------------------------------------------------------------------------
#
# E-2 del diseño: salida estructurada GARANTIZADA, no "pedida por favor". Sin
# ella, F-1 dispara reintentos y `k` deja de ser 1.
#
# Es un objeto plano con campos anulables, y no tres esquemas alternativos, a
# proposito: el modo estricto exige que TODA propiedad este en `required`, y un
# `anyOf` en la raiz da mas superficie para que el proveedor lo rechace. Plano
# y anulable es la forma que menos depende de detalles del proveedor.
ESQUEMA_SALIDA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "tipo", "sql", "interpretacion", "pregunta", "opciones",
        "falta", "disponibles",
    ],
    "properties": {
        "tipo": {"type": "string", "enum": list(TIPOS)},
        "sql": {"type": ["string", "null"]},
        "interpretacion": {"type": ["string", "null"]},
        "pregunta": {"type": ["string", "null"]},
        "opciones": {
            "type": ["array", "null"],
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "texto", "sql"],
                "properties": {
                    "id": {"type": "string"},
                    "texto": {"type": "string"},
                    "sql": {"type": "string"},
                },
            },
        },
        "falta": {"type": ["string", "null"]},
        "disponibles": {"type": ["array", "null"], "items": {"type": "string"}},
    },
}

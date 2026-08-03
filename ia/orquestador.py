"""
El orquestador: pregunta en español -> desenlace. Aqui se juntan las piezas.

LO QUE NO CAMBIA RESPECTO A LA VIA SQL
----------------------------------------
**Todo SQL que venga del modelo pasa por el guardian, entero.** No hay camino
corto, ni "esta lo escribio el modelo con nuestro contexto, es de fiar". A
efectos de contencion, el modelo es un desconocido cooperativo en el mejor caso
y un desconocido comprometido en el peor, y el codigo trata los dos igual.

Esa es la razon de que la contencion siga midiendose sin modelo (T-1): el
guardian es el mismo objeto en las dos vias.

`k <= 2` — LOS DOS UNICOS REINTENTOS, Y POR QUE ESOS
------------------------------------------------------
  F-1 · la salida no cumple el contrato  -> 1 reintento con el error de forma
  F-4 · el SQL usa el reloj del motor    -> 1 reintento pidiendo fecha_corte()

Y ninguno mas. En particular:

  F-3 · el modelo genero SQL destructivo -> CERO reintentos.

Esa ultima merece leerse dos veces. Pedirle otro intento al modelo despues de
un DELETE (a) deja que un atacante consuma presupuesto a voluntad repitiendo la
misma inyeccion, y (b) convierte al sistema en algo que NEGOCIA con un modelo
posiblemente comprometido. No se negocia: se rechaza, se nombra la regla y se
registra.

LAS OPCIONES DE UNA REPREGUNTA SE VALIDAN ANTES DE ENSEÑARSE
--------------------------------------------------------------
Cada opcion llega con su SQL. Cada uno pasa por el guardian, y las que no pasan
se descartan. Si quedan menos de dos, NO se repregunta: una repregunta con una
sola opcion es un callejon, y una con opciones que no se pueden calcular es
peor que no preguntar.

Esto implementa con codigo la exigencia de que "las opciones ofrecidas existen
en los datos", en vez de confiarla a una instruccion del prompt.

ANTE LA AMBIGUEDAD NO SE EJECUTA NADA
---------------------------------------
No hay "ejecuto la lectura mas probable y aviso". El error es asimetrico: una
repregunta molesta es recuperable; un numero con aire de certeza es invisible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from guardian.catalogo import Catalogo
from guardian.contrato import Veredicto
from guardian.nucleo import veredicto as juzgar
from ia.contrato import ContratoRoto, Opcion, Respuesta, interpretar

TOPE_PREGUNTA = 500

MAX_LLAMADAS = 2


class Adaptador(Protocol):
    """Lo unico que el orquestador necesita de un proveedor.

    Es un `Protocol` y no una clase base para que los adaptadores de prueba no
    tengan que heredar de nada: T-3 necesita un cooperador, un hostil y un
    roto, y ninguno de los tres es "un proveedor" en ningun sentido util.
    """

    def preguntar(self, contexto: str, pregunta: str, pista: str | None = None) -> str:
        """Devuelve el texto crudo del modelo. Lanza `ProveedorCaido` si falla."""
        ...


class ProveedorCaido(RuntimeError):
    """El proveedor no respondio, expiro o corto. F-5: cero reintentos."""


@dataclass
class Desenlace:
    """Lo que el orquestador concluye. Un solo objeto para los cinco finales."""

    clase: str                       # consulta | ambigua | sin_datos | rechazo | error
    mensaje: str | None = None
    # clase == consulta
    veredicto: Veredicto | None = None
    interpretacion: str | None = None
    # clase == ambigua
    pregunta: str | None = None
    opciones: list[tuple[Opcion, Veredicto]] = field(default_factory=list)
    # clase == sin_datos
    falta: str | None = None
    disponibles: tuple[str, ...] = ()
    # medicion
    llamadas: int = 0
    descartadas: int = 0             # opciones que el guardian tumbo


_SIN_FORMA = "No pude interpretar tu pregunta. Intenta formularla de otra manera."
_CAIDO = "El servicio de interpretación no está disponible ahora."
_LARGA = f"Tu pregunta es demasiado larga: el máximo son {TOPE_PREGUNTA} caracteres."
_NO_DESAMBIGUA = (
    "Tu pregunta admite varias respuestas y no consigo ofrecerte opciones que "
    "pueda calcular. Intenta preguntarlo de forma más concreta."
)


def responder(
    pregunta: str, contexto: str, catalogo: Catalogo, adaptador: Adaptador
) -> Desenlace:
    """Pregunta en español -> desenlace. Ni una sentencia sale de aqui."""
    if len(pregunta) > TOPE_PREGUNTA:
        return Desenlace(clase="error", mensaje=_LARGA)
    if not pregunta.strip():
        return Desenlace(clase="error", mensaje=_SIN_FORMA)

    llamadas = 0
    pista: str | None = None

    while llamadas < MAX_LLAMADAS:
        llamadas += 1
        try:
            crudo = adaptador.preguntar(contexto, pregunta, pista)
        except ProveedorCaido:
            # F-5: cero reintentos. Si el proveedor esta caido, insistir solo
            # multiplica la espera del usuario.
            return Desenlace(clase="error", mensaje=_CAIDO, llamadas=llamadas)

        try:
            respuesta = interpretar(crudo)
        except ContratoRoto as e:
            # F-1: un reintento, diciendole QUE estaba mal.
            pista = f"Tu respuesta anterior no cumplió el formato: {e}. Responde solo el objeto JSON."
            continue

        desenlace = _resolver(respuesta, catalogo, llamadas)

        # F-4: el unico reintento que nace de un veredicto. Es de coherencia,
        # no de seguridad — el guardian lo distingue, y esa distincion es la
        # que evita que un rechazo de seguridad se reintente por error.
        if (
            desenlace.clase == "rechazo"
            and desenlace.veredicto is not None
            and desenlace.veredicto.admite_reintento
            and llamadas < MAX_LLAMADAS
        ):
            pista = (
                "El SQL usaba la fecha de hoy del servidor. Este conjunto tiene "
                "fecha de corte fija: usa consulta.fecha_corte()."
            )
            continue

        return desenlace

    return Desenlace(clase="error", mensaje=_SIN_FORMA, llamadas=llamadas)


def _resolver(respuesta: Respuesta, catalogo: Catalogo, llamadas: int) -> Desenlace:
    if respuesta.tipo == "sin_datos":
        # D-D no toca la base ni el guardian: no hay SQL que juzgar.
        return Desenlace(
            clase="sin_datos",
            falta=respuesta.falta,
            disponibles=respuesta.disponibles,
            llamadas=llamadas,
        )

    if respuesta.tipo == "consulta":
        v = juzgar(respuesta.sql or "", catalogo)
        if not v.permitido:
            return Desenlace(
                clase="rechazo", veredicto=v, mensaje=v.mensaje, llamadas=llamadas
            )
        return Desenlace(
            clase="consulta",
            veredicto=v,
            interpretacion=respuesta.interpretacion,
            llamadas=llamadas,
        )

    # ambigua — cada opcion pasa por el guardian ANTES de enseñarse
    validas: list[tuple[Opcion, Veredicto]] = []
    descartadas = 0
    for opcion in respuesta.opciones:
        v = juzgar(opcion.sql, catalogo)
        if v.permitido:
            validas.append((opcion, v))
        else:
            descartadas += 1

    if len(validas) < 2:
        return Desenlace(
            clase="error",
            mensaje=_NO_DESAMBIGUA,
            llamadas=llamadas,
            descartadas=descartadas,
        )

    return Desenlace(
        clase="ambigua",
        pregunta=respuesta.pregunta,
        opciones=validas,
        llamadas=llamadas,
        descartadas=descartadas,
    )

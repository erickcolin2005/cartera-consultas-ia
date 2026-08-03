"""
El catalogo, ya cargado, como estructura de datos pura.

POR QUE ESTE MODULO NO LEE `catalogo.yaml`
------------------------------------------
Leer un fichero es entrada/salida, y el guardian no hace entrada/salida. Quien
llama carga el YAML y le pasa el diccionario. Parece un rodeo y no lo es: es lo
que permite que T-5 compruebe ESTRUCTURALMENTE que este paquete no puede tocar
nada — sin `open`, sin red, sin base de datos, no hay nada que auditar caso por
caso.

Efecto secundario util: probar el guardian con un catalogo distinto es pasarle
otro diccionario, no parchear el sistema de ficheros.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Catalogo:
    """Las cuatro listas blancas de `catalogo.yaml` §7.5, ya normalizadas.

    Los nombres se guardan en minusculas porque la comparacion es sobre el par
    (esquema, nombre) normalizado, no sobre el texto.
    """

    relaciones_permitidas: frozenset[tuple[str, str]] = frozenset()
    funciones_permitidas: frozenset[str] = frozenset()
    funciones_propias: frozenset[tuple[str, str]] = frozenset()
    tipos_permitidos: frozenset[str] = frozenset()
    prohibidos_por_nombre: frozenset[str] = frozenset()
    prohibidos_por_prefijo: tuple[str, ...] = field(default=())

    ESQUEMA_POR_DEFECTO = "consulta"

    # -- construccion ----------------------------------------------------

    @classmethod
    def desde_dict(cls, datos: dict) -> "Catalogo":
        relaciones = set()
        for entrada in datos.get("relaciones_permitidas", []):
            relaciones.add(_partir_relacion(entrada))

        funciones: set[str] = set()
        propias: set[tuple[str, str]] = set()
        for grupo, nombres in (datos.get("funciones_permitidas") or {}).items():
            for nombre in nombres or []:
                texto = str(nombre).strip().lower()
                if grupo == "propias" or "." in texto:
                    propias.add(_partir_relacion(texto))
                else:
                    funciones.add(texto)

        prohibidos = datos.get("prohibidos_siempre") or {}

        return cls(
            relaciones_permitidas=frozenset(relaciones),
            funciones_permitidas=frozenset(funciones),
            funciones_propias=frozenset(propias),
            tipos_permitidos=frozenset(
                str(t).strip().lower() for t in datos.get("tipos_permitidos", [])
            ),
            prohibidos_por_nombre=frozenset(
                str(n).strip().lower() for n in (prohibidos.get("por_nombre") or [])
            ),
            prohibidos_por_prefijo=tuple(
                str(p).strip().lower() for p in (prohibidos.get("por_prefijo") or [])
            ),
        )

    # -- consultas -------------------------------------------------------

    def relacion_permitida(self, esquema: str, nombre: str) -> bool:
        return (esquema.lower(), nombre.lower()) in self.relaciones_permitidas

    def funcion_permitida(self, nombre: str, esquema: str | None = None) -> bool:
        """Lista blanca. Los prohibidos-siempre mandan sobre la lista blanca.

        Ese orden importa: si alguien añadiera por error un nombre prohibido a
        la lista blanca, esta comprobacion lo sigue rechazando. Es el mismo
        principio que la revocacion en el motor — una red debajo de una lista
        que escribe una persona.
        """
        nombre = nombre.lower()
        if self.prohibido_siempre(nombre):
            return False
        if esquema:
            return (esquema.lower(), nombre) in self.funciones_propias
        return nombre in self.funciones_permitidas

    def prohibido_siempre(self, nombre: str) -> bool:
        nombre = nombre.lower()
        if nombre in self.prohibidos_por_nombre:
            return True
        return any(_coincide_glob(nombre, patron) for patron in self.prohibidos_por_prefijo)

    def tipo_permitido(self, nombre: str) -> bool:
        return nombre.lower() in self.tipos_permitidos


def _partir_relacion(texto: str) -> tuple[str, str]:
    partes = str(texto).strip().lower().split(".")
    if len(partes) == 1:
        return (Catalogo.ESQUEMA_POR_DEFECTO, partes[0])
    return (partes[-2], partes[-1])


def _coincide_glob(nombre: str, patron: str) -> bool:
    """`*` es el unico comodin. Se implementa a mano, sin `fnmatch`, porque
    `fnmatch` trata `?` y `[...]` como comodines y aqui son caracteres
    literales: un patron con corchetes se comportaria distinto de lo que
    alguien lee en `catalogo.yaml`. La lista blanca tiene que significar
    exactamente lo que parece que significa.
    """
    trozos = patron.split("*")
    if len(trozos) == 1:
        return nombre == patron
    if not nombre.startswith(trozos[0]):
        return False
    if not nombre.endswith(trozos[-1]):
        return False
    # El resto tiene que aparecer en orden.
    posicion = len(trozos[0])
    for trozo in trozos[1:-1]:
        if not trozo:
            continue
        encontrado = nombre.find(trozo, posicion)
        if encontrado == -1:
            return False
        posicion = encontrado + len(trozo)
    return posicion <= len(nombre) - len(trozos[-1])

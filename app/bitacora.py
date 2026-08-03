"""
La bitacora: un evento por consulta, una linea por evento.

POR QUE VIVE AQUI Y NO EN EL GUARDIAN
--------------------------------------
Registrar necesita reloj (`ts`) y aleatoriedad (`id`). T-5 prohibe las dos
cosas dentro de `guardian/`, y no por gusto: la pureza del guardian es lo que
permite correr T-1 —los 52 casos del banco— sin levantar nada. Si el guardian
registrara, esa propiedad se perderia.

Consecuencia deliberada: **el guardian no sabe que existe una bitacora.**
Decide, devuelve un veredicto, y quien lo llama decide si lo apunta.

SERIALIZAR, JAMAS CONCATENAR (M-30 · T-11)
-------------------------------------------
Este es el punto entero del modulo. La entrada es texto que controla quien
ataca, y puede contener saltos de linea y llaves:

    SELECT 1
    {"veredicto":"permitido","regla":null,"sql_ejecutado":"DELETE FROM pagos"}

Si el evento se construyera pegando cadenas —`f'{{"entrada":"{sql}"}}'`—, ese
texto entraria en el fichero **como dos lineas**, y la segunda seria un evento
falso perfectamente valido que dice que una carga destructiva fue permitida.
De la bitacora salen la evidencia de RF-11 y la trazabilidad de los rechazos:
falsificarla ataca el proyecto sin tocar un solo dato.

`json.dumps` lo cierra por construccion: los caracteres de control **siempre**
se escapan, tambien con `ensure_ascii=False`. Un `\\n` dentro de un valor sale
como los dos caracteres `\\` y `n`, nunca como un salto real.

POR QUE `ensure_ascii=True` AUNQUE EL TEXTO SEA ESPAÑOL
--------------------------------------------------------
`json.dumps` escapa los controles ASCII, pero con `ensure_ascii=False` deja
pasar crudos **U+2028** y **U+2029**, que son separadores de linea Unicode.
Ninguno rompe `readlines()`, pero `str.splitlines()` de Python **si** parte por
ellos: bastaria que un lector de la bitacora usara `splitlines()` para que una
entrada con U+2028 apareciera como dos eventos.

El coste es que «cuotas vencidas» se guarda como `cuotas vencidas` con las
tildes escapadas y se lee peor a ojo. Se acepta: esto es evidencia que se lee
con `json.loads`, que las restituye exactas, y en un registro de seguridad la
integridad vale mas que la comodidad. Es una decision, no un descuido — y
`test_t11_bitacora.py` la comprueba con U+2028 explicitamente.

QUE NO SE ESCRIBE, Y POR QUE
-----------------------------
El diseño (§6.3) lista tambien `ms_modelo`, `ms_bd` y `llamadas_modelo`. Hoy
**no hay adaptador de modelo**, asi que nadie mide esos tres numeros. Escribir
`llamadas_modelo: 0` seria registrar una medicion que nadie toma. Se omiten, y
el campo `via` dice `sql` porque hoy la unica entrada es SQL directo. Cuando
exista la via de pregunta en lenguaje natural, `via` dira `pn` y los tres
campos entraran con un valor medido detras.

**El eco va COMPLETO, sin truncar** (§6.3). El truncado es politica de
presentacion y vive en la pantalla; aqui borraria evidencia.

LO QUE ESTE MODULO NO HACE
---------------------------
No rota el fichero ni caduca nada. La politica de retencion del diseño
—0 dias de literal en produccion, 7 en rechazos— aplica a un despliegue que no
existe todavia; en local la retencion declarada es indefinida. Cuando haya
despliegue, esto necesita rotacion y caducidad, y no las tiene.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

# Sobre-escribible por entorno para que las pruebas no escriban en la real.
RUTA_POR_DEFECTO = RAIZ / "bitacora.jsonl"


def ruta() -> Path:
    return Path(os.environ.get("BITACORA", RUTA_POR_DEFECTO))


def evento(veredicto, resultado, *, via: str = "sql") -> dict:
    """Construye el evento como DICCIONARIO. Ni una cadena se pega aqui.

    Que esta funcion devuelva un `dict` y no texto no es un detalle de estilo:
    es lo que hace imposible el ataque. Quien quiera falsificar una linea
    tendria que conseguir que `json.dumps` emita un salto de linea sin escapar,
    y eso no depende de esta funcion ni de la entrada.
    """
    return {
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "id": str(uuid.uuid4()),
        "via": via,
        "veredicto": (
            "permitido"
            if veredicto.permitido
            else ("coherencia" if veredicto.admite_reintento else "rechazo")
        ),
        "regla": veredicto.regla,
        "sentencias_enviadas": resultado.sentencias_enviadas,
        "filas": len(resultado.filas),
        "hay_mas": resultado.hay_mas,
        "error": resultado.error,
        "ms": resultado.ms,
        "longitud_entrada": len(veredicto.eco),
        # COMPLETO. Sin TOPE_ECO: esto es la evidencia de RF-11.
        "entrada": veredicto.eco,
        "sql_ejecutado": veredicto.sql_a_ejecutar,
    }


def serializar(ev: dict) -> str:
    """Evento -> UNA linea. La unica funcion que produce texto de bitacora.

    `ensure_ascii=True` por lo dicho arriba (U+2028). `sort_keys` para que dos
    eventos iguales den lineas iguales y un diff signifique algo.
    """
    return json.dumps(ev, ensure_ascii=True, sort_keys=True) + "\n"


def registrar(veredicto, resultado, *, via: str = "sql") -> bool:
    """Apunta el evento. Devuelve SI SE ESCRIBIO DE VERDAD.

    El valor de retorno es el punto. La pantalla dice «el intento quedo
    registrado»; si esa frase fuera fija, seria exactamente el pecado que este
    proyecto existe para no cometer — una afirmacion en pantalla que nadie
    mide. Devolviendo un booleano, la pantalla informa de lo que paso.

    Un fallo al escribir NO tumba la consulta: el usuario recibe su respuesta y
    la pantalla dice que el intento **no** quedo registrado. Perder la
    respuesta ademas del apunte no arregla nada.
    """
    linea = serializar(evento(veredicto, resultado, via=via))
    try:
        destino = ruta()
        destino.parent.mkdir(parents=True, exist_ok=True)
        # `newline=""` para que Windows no traduzca el \n a \r\n: asi el
        # fichero es identico en la maquina de desarrollo y en el CI, que es
        # Linux. Una sola llamada a `write` con la linea entera.
        with open(destino, "a", encoding="utf-8", newline="") as f:
            f.write(linea)
        return True
    except OSError:
        return False


def leer(destino: Path | None = None) -> list[dict]:
    """Lee la bitacora. Util para las pruebas y para revisarla a mano."""
    destino = destino or ruta()
    if not destino.exists():
        return []
    with open(destino, encoding="utf-8", newline="") as f:
        return [json.loads(l) for l in f if l.strip()]

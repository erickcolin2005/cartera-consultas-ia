"""
Comprueba que las pruebas SABEN PONERSE EN ROJO.

EL PROBLEMA QUE RESUELVE
-------------------------
Una suite en verde demuestra dos cosas a la vez, y solo una es buena: que el
sistema se comporta, o que las pruebas no miran. Este proyecto ya se tropezo
cinco veces con lo segundo — pruebas que pasaban midiendo la cosa equivocada—,
asi que el verde por si solo no es evidencia de nada.

Aqui se apaga una regla a proposito y se EXIGE que la suite falle. Si no falla,
esa regla no estaba protegida por ninguna prueba, y el README no puede decir
«si alguien la desactiva, el build cae».

POR QUE CADA MUTACION DECLARA QUE PRUEBA DEBE CAER
---------------------------------------------------
No basta con «algo se puso rojo». Al desactivar el nodo de borrado de S2, la
carga puede seguir contenida —otra regla la atrapa— y aun asi la prueba tiene
que fallar, porque afirma **por que regla** salio. Esa distincion se descubrio
a mano el 2026-08-02 y es la razon de que aqui se compruebe el selector y no
solo el codigo de salida.

Una mutacion que no tumba a su prueba nombrada es un fallo de este script,
tanto como una que no tumba nada.

USO
----
    python herramientas/sensibilidad.py           # todas
    python herramientas/sensibilidad.py s2-borrado

Restaura siempre los ficheros, tambien si algo revienta.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Mutacion:
    nombre: str
    fichero: str
    busca: str
    pone: str
    prueba: str          # el selector que TIENE que caer
    explica: str


MUTACIONES = [
    Mutacion(
        nombre="s2-borrado",
        fichero="guardian/politica.py",
        busca="    exp.Delete,\n",
        pone="",
        prueba="tests/test_t1_banco.py",
        explica=(
            "Saca el nodo de borrado de la regla S2. La carga puede seguir "
            "contenida por otra regla; la prueba cae igual porque afirma la "
            "regla, no solo que hubo rechazo."
        ),
    ),
    Mutacion(
        nombre="s3-lista-blanca",
        fichero="guardian/catalogo.py",
        busca="        return (esquema, nombre) in self.relaciones_permitidas",
        pone="        return True",
        prueba="tests/test_t1_banco.py",
        explica=(
            "Abre la lista blanca de relaciones: cualquier tabla pasa. Es el "
            "agujero que I-3' introdujo de verdad con un `.lower()` de mas."
        ),
    ),
    Mutacion(
        nombre="s7a-tipos",
        fichero="guardian/catalogo.py",
        busca="        return nombre.lower() in self.tipos_permitidos",
        pone="        return True",
        prueba="tests/test_t1_banco.py",
        explica=(
            "Apaga la comprobacion del tipo destino de un CAST. M-19 deja de "
            "estar contenido: es la segunda mutacion que se probo a mano."
        ),
    ),
    # HUECO CONOCIDO — el contador de sentencias no esta aqui.
    #
    # La mutacion evidente seria dejar `sentencias_enviadas` clavado en cero:
    # la pantalla seguiria diciendo «sentencias enviadas: 0» en un rechazo, que
    # es la cifra que sostiene el bloque entero. No esta en la lista porque
    # **T-7 no existe todavia**, y una mutacion sin prueba que tumbar no mide
    # nada. Escribirla aqui apuntando a un fichero inexistente daria un falso
    # verde, que es peor que no tenerla.
    #
    # Se deja nombrada para que el hueco se lea, en vez de deducirse.
    Mutacion(
        nombre="bitacora-concatenada",
        fichero="app/bitacora.py",
        busca='    return json.dumps(ev, ensure_ascii=True, sort_keys=True) + "\\n"',
        pone=(
            '    campos = ",".join(\'"%s":"%s"\' % (k, v) for k, v in sorted(ev.items()))\n'
            '    return "{" + campos + "}" + "\\n"'
        ),
        prueba="tests/test_t11_bitacora.py",
        explica=(
            "Construye el evento pegando cadenas. Es el ataque M-30: la entrada "
            "lleva un salto de linea y escribe un evento falso."
        ),
    ),
    Mutacion(
        nombre="bitacora-ensure-ascii",
        fichero="app/bitacora.py",
        busca='    return json.dumps(ev, ensure_ascii=True, sort_keys=True) + "\\n"',
        pone='    return json.dumps(ev, ensure_ascii=False, sort_keys=True) + "\\n"',
        prueba="tests/test_t11_bitacora.py",
        explica=(
            "Deja las tildes sin escapar, que se lee mejor. Y deja pasar crudos "
            "U+2028 y U+2029, que parten el evento en dos para cualquier lector "
            "que use splitlines()."
        ),
    ),
]


def _leer(ruta: Path) -> str:
    """Lee SIN traducir finales de linea.

    Con `read_text`/`write_text` a secas, en Windows el viaje de ida y vuelta
    convierte un fichero LF en CRLF: `read_text` normaliza a \\n y `write_text`
    escribe \\r\\n. El restaurado dejaba el fichero distinto del original en
    cada byte de salto de linea — invisible en `git diff` por la normalizacion
    de git, y visible en el disco. Una herramienta que dice restaurar tiene que
    devolver los MISMOS bytes.
    """
    return ruta.read_text(encoding="utf-8", newline="")


def _escribir(ruta: Path, texto: str) -> None:
    ruta.write_text(texto, encoding="utf-8", newline="")


def _pytest(selector: str) -> int:
    return subprocess.run(
        [sys.executable, "-m", "pytest", selector, "-q", "--no-header", "-x"],
        cwd=RAIZ,
        capture_output=True,
        text=True,
    ).returncode


def comprobar(m: Mutacion) -> bool:
    ruta = RAIZ / m.fichero
    original = _leer(ruta)
    if m.busca not in original:
        print(f"  ✗ {m.nombre}: no encuentro el texto a mutar en {m.fichero}.")
        print("    La mutacion quedo obsoleta; hay que reescribirla.")
        return False

    # VERDE PRIMERO. Sin esto el script se engaña solo: pytest devuelve un
    # codigo distinto de cero tambien cuando el fichero de pruebas NO EXISTE
    # (error de uso, codigo 4), y ese rojo se leeria como «la mutacion
    # funciono». Una mutacion solo dice algo si la prueba estaba en verde y la
    # mutacion es lo que la tumbo.
    if _pytest(m.prueba) != 0:
        print(f"  ✗ {m.nombre}: {m.prueba} NO esta en verde antes de mutar.")
        print("    O el fichero no existe, o ya estaba roto. Sin verde previo,")
        print("    el rojo de despues no demuestra nada.")
        return False

    try:
        _escribir(ruta, original.replace(m.busca, m.pone, 1))
        codigo = _pytest(m.prueba)
    finally:
        _escribir(ruta, original)

    if codigo == 0:
        print(f"  ✗ {m.nombre}: {m.prueba} SIGUIO EN VERDE con la regla apagada.")
        print(f"    {m.explica}")
        print("    Esa regla no esta protegida por ninguna prueba.")
        return False
    print(f"  ✓ {m.nombre}: {m.prueba} cae, como debe.")
    return True


def main() -> int:
    pedidas = sys.argv[1:]
    lista = [m for m in MUTACIONES if not pedidas or m.nombre in pedidas]
    if not lista:
        print(f"No conozco esas mutaciones. Hay: {[m.nombre for m in MUTACIONES]}")
        return 2

    print("Apagando reglas a proposito. Cada una TIENE que tumbar su prueba.\n")
    fallos = [m.nombre for m in lista if not comprobar(m)]

    print()
    if fallos:
        print(f"FALLO: {len(fallos)} de {len(lista)} no tumbaron nada — {fallos}")
        return 1
    print(f"OK: las {len(lista)} mutaciones ponen la suite en rojo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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
    # Esta era el hueco conocido mientras T-7 no existia: una mutacion sin
    # prueba que tumbar no mide nada. Ya existe T-7, asi que entra.
    Mutacion(
        nombre="contador-clavado-en-cero",
        fichero="app/ejecutor.py",
        busca="        self._contador.sentencias_enviadas += 1",
        pone="        pass",
        prueba="tests/test_t7_contador.py",
        explica=(
            "Deja el contador clavado en cero. La pantalla seguiria diciendo "
            "«sentencias enviadas: 0» en un rechazo, que es correcto, y "
            "tambien en una consulta que SI se ejecuta, que no lo es. Solo el "
            "caso positivo de T-7 lo distingue."
        ),
    ),
    Mutacion(
        nombre="contador-en-el-ejecutor",
        fichero="app/ejecutor.py",
        busca="                cursor.execute(v.sql_a_ejecutar)",
        pone=(
            "                contador.sentencias_enviadas += 1\n"
            "                crudo.execute(v.sql_a_ejecutar)"
        ),
        prueba="tests/test_t7_contador.py",
        explica=(
            "Saca el contador del borde y lo mete en el ejecutor, saltandose "
            "el envoltorio. El numero sale igual, pero ya no mide lo que sale "
            "hacia el motor: mide que decidimos contar. La parte (b) de T-7 "
            "—estructural— es la unica que ve la diferencia."
        ),
    ),
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


# `-P` no mete el directorio actual en `sys.path`, igual que hace el CI al
# invocar `pytest` a secas. Sin el, esta herramienta correria en condiciones
# mas indulgentes que el build, y una importacion rota pasaria inadvertida en
# local hasta llegar a GitHub. Ya paso una vez.
_PYTEST = [sys.executable, "-P", "-m", "pytest"]


def _pytest(selector: str) -> int:
    return subprocess.run(
        [*_PYTEST, selector, "-q", "--no-header", "-x"],
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


def cifra_de_la_pantalla() -> bool:
    """La pantalla dice «N pruebas en verde». Que N sea N.

    POR QUE ESTA COMPROBACION EXISTE
    ---------------------------------
    Ese numero esta escrito a mano en `servidor.py` y **ya se quedo atras una
    vez**: la suite paso de 188 a 212 y la pantalla siguio diciendo 188. Es el
    defecto que este repositorio entero persigue —una cifra afirmada que nadie
    vuelve a medir—, cometido en el propio sitio donde se predica.

    Vive aqui y no en `tests/` a proposito: contar las pruebas desde dentro de
    una prueba es recursivo. Este script ya lanza pytest como subproceso, asi
    que preguntarle cuantas hay no cuesta nada.
    """
    import re

    fuente = _leer(RAIZ / "app" / "servidor.py")
    escrito = re.search(r"<strong>(\d+) pruebas en verde</strong>", fuente)
    if not escrito:
        print("  ✗ pantalla: no encuentro la cifra de pruebas en servidor.py.")
        return False

    # Se cuentan las que PASAN, no las que se recolectan.
    #
    # `--collect-only` seria mas rapido y estaria mal: incluye la que se salta
    # (M-27), y la pantalla dice «en verde», no «escritas». Al escribir esta
    # comprobacion decia 213 frente a 212 — una diferencia de uno que resultaba
    # ser exactamente esa distincion.
    salida = subprocess.run(
        [*_PYTEST, "-q"], cwd=RAIZ, capture_output=True, text=True,
    )
    en_verde = re.search(r"(\d+)\s+passed", salida.stdout)
    if not en_verde:
        print("  ✗ pantalla: pytest no dijo cuantas pruebas pasaron.")
        print(f"    {salida.stdout.strip().splitlines()[-1:]}")
        return False

    dice, hay = int(escrito.group(1)), int(en_verde.group(1))
    if dice != hay:
        print(f"  ✗ pantalla: dice {dice} pruebas en verde y hay {hay}.")
        print("    Una cifra en pantalla que nadie vuelve a medir es el defecto")
        print("    que este proyecto existe para no cometer.")
        return False
    print(f"  ✓ pantalla: dice {dice} pruebas y hay {hay}.")
    return True


def main() -> int:
    pedidas = sys.argv[1:]
    lista = [m for m in MUTACIONES if not pedidas or m.nombre in pedidas]
    if not lista:
        print(f"No conozco esas mutaciones. Hay: {[m.nombre for m in MUTACIONES]}")
        return 2

    print("Apagando reglas a proposito. Cada una TIENE que tumbar su prueba.\n")
    fallos = [m.nombre for m in lista if not comprobar(m)]

    # Solo en la pasada completa: con una mutacion suelta, contar las pruebas
    # de todo el repositorio no viene a cuento.
    if not pedidas:
        print()
        if not cifra_de_la_pantalla():
            fallos.append("cifra-de-la-pantalla")

    print()
    if fallos:
        print(f"FALLO: {len(fallos)} de {len(lista)} no tumbaron nada — {fallos}")
        return 1
    print(f"OK: las {len(lista)} mutaciones ponen la suite en rojo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

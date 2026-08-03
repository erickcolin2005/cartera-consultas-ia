"""
T-8 · Privilegios exactos del rol restringido (aserciones A-1 ... A-9).

QUE DEMUESTRA
-------------
Que la capa 1 es lo que el README dice. El DDL *crea* el rol; esto lo *afirma*.
Un solo `GRANT pg_read_all_data` anula la capa 2 entera y no deja rastro en
ningun fichero del repositorio: solo una aserción contra el motor lo ve.

POR QUE ES LA PRIMERA PRUEBA DEL REPOSITORIO, ANTES QUE T-1
-----------------------------------------------------------
T-1 prueba el guardian, que es la capa 3. Si la capa 1 no fuera lo que
decimos, T-1 podria estar en verde sobre un sistema inseguro. El orden importa.

SI UNA FALLA, NO SE REPARA: SE MIRA
-----------------------------------
Un fallo aqui no significa que falte un GRANT. Significa que alguien concedio
algo que no debia.

EL SQL NO ESTA EN ESTE FICHERO
------------------------------
Vive en `datos/aserciones.sql` y solo ahi, para que el guion que se ejecuta a
mano en G3-SEC-1 y el que corre en el CI sean literalmente el mismo texto.
Aqui solo estan los valores exigidos.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

DATOS = Path(__file__).resolve().parents[1] / "datos"
ASERCIONES = DATOS / "aserciones.sql"
LINEA_BASE = json.loads((DATOS / "linea-base-revocaciones.json").read_text(encoding="utf-8"))

VISTAS_PUBLICADAS = ("cuotas", "pagos", "propietarios", "unidades")

# Valor exigido por aserción. Comparacion como CONJUNTO ORDENADO de tuplas.
EXIGIDO: dict[str, list[tuple]] = {
    # Exactamente cuatro privilegios. Ni uno mas. Incluye los de columna.
    "A-1": [("consulta", vista, "SELECT") for vista in VISTAS_PUBLICADAS],
    # Ningun rol padre: ni pg_read_all_data ni ninguno de sus hermanos.
    "A-2": [],
    # super, createdb, createrole, bypassrls, replication.
    "A-3": [(False, False, False, False, False)],
    # No es dueño de nada: por eso M-15 (GRANT ... TO PUBLIC) no puede surtir efecto.
    "A-4": [],
    # Ninguna funcion de la lista revocada sigue siendo ejecutable, en ninguna
    # de sus sobrecargas.
    "A-5": [],
    # pg_catalog en `true` NO es un fallo: es la limitacion de §6.7 puesta por
    # escrito en la propia prueba. No se puede revocar de forma fiable, y el
    # README lo declara en vez de esconderlo.
    "A-6": [
        ("cartera", False),
        ("consulta", True),
        ("information_schema", False),
        ("pg_catalog", True),
        ("public", False),
    ],
    # Solo la extension que trae la imagen. Cierra dblink, postgres_fdw y los
    # lenguajes procedurales.
    "A-7": [("plpgsql",)],
    "A-8": [
        ("default_transaction_read_only=on",),
        ("search_path=consulta",),
        ("statement_timeout=5s",),
    ],
    # A-9 no es una igualdad: es un umbral. Se comprueba aparte.
    # A-10 se compara contra un fichero de linea base. Tambien aparte.
}


def _leer_aserciones() -> dict[str, str]:
    texto = ASERCIONES.read_text(encoding="utf-8")
    bloques: dict[str, str] = {}
    partes = re.split(r"^--\s*@asercion\s+(A-\d+)\s*\|.*$", texto, flags=re.MULTILINE)
    for i in range(1, len(partes), 2):
        bloques[partes[i]] = partes[i + 1].strip()
    return bloques


ASERCIONES_SQL = _leer_aserciones()


def test_el_fichero_de_aserciones_las_tiene_todas():
    """Si una aserción desaparece del fichero, esto lo ve. Es la guardia de V2:
    ninguna prueba se desactiva en silencio."""
    assert sorted(ASERCIONES_SQL, key=lambda s: int(s.split("-")[1])) == [
        f"A-{n}" for n in range(1, 11)
    ]


@pytest.mark.parametrize("identificador", sorted(EXIGIDO))
def test_asercion_de_privilegios(conexion_owner, identificador):
    with conexion_owner.cursor() as cur:
        cur.execute(ASERCIONES_SQL[identificador])
        obtenido = sorted(cur.fetchall())
    esperado = sorted(EXIGIDO[identificador])
    assert obtenido == esperado, (
        f"{identificador} fallo.\n"
        f"  exigido : {esperado}\n"
        f"  obtenido: {obtenido}\n"
        f"  Un fallo aqui NO se repara concediendo o quitando privilegios sin "
        f"entender por que cambio: significa que alguien concedio algo que no debia."
    )


def test_a9_limite_de_conexiones(conexion_owner, capsys):
    """A-9 · el mamparo de concurrencia (R-22).

    No es una igualdad porque el valor correcto depende del `max_connections`
    de la plataforma, que en F6 sera otro. Lo que se exige es que exista un
    limite finito; el `max_connections` se REGISTRA para que el ajuste de F6
    sea un dato y no una intuicion.
    """
    with conexion_owner.cursor() as cur:
        cur.execute(ASERCIONES_SQL["A-9"])
        limite, max_conexiones = cur.fetchone()

    with capsys.disabled():
        print(f"\n  A-9 · CONNECTION LIMIT de consulta_ro = {limite} · "
              f"max_connections de la instancia = {max_conexiones}")

    assert limite != -1, "consulta_ro no tiene limite de conexiones: R-22 queda sin mitigar"
    assert 1 <= limite <= 10, f"CONNECTION LIMIT fuera del rango exigido (<=10): {limite}"


def test_a10_cobertura_de_la_revocacion(conexion_owner):
    """A-10 · el recuento por familia, contra la linea base versionada.

    Convierte el "326 rutinas revocadas" de anecdota de una corrida en control
    vivo. Sin esto, un prefijo mal escrito produce un AVISO en el arranque y
    quien lo lea creera que la familia esta cubierta.

    Las tres direcciones de fallo se distinguen a proposito: un recuento que
    baja es una REGRESION y no se arregla actualizando la linea base; un
    prefijo que cae a cero habiendo tenido coincidencias es casi siempre un
    error de escritura; y uno que sube suele ser un motor nuevo, que hay que
    revisar y volver a versionar en el mismo commit.
    """
    with conexion_owner.cursor() as cur:
        cur.execute(ASERCIONES_SQL["A-10"])
        obtenido = {f"{clase}|{patron}": n for clase, patron, n in cur.fetchall()}

    esperado = LINEA_BASE["por_patron"]

    faltan = sorted(set(esperado) - set(obtenido))
    sobran = sorted(set(obtenido) - set(esperado))
    assert not faltan, f"patrones de la linea base que ya no estan en la politica: {faltan}"
    assert not sobran, (
        f"patrones nuevos en la politica sin linea base: {sobran}. "
        f"Añadirlos a datos/linea-base-revocaciones.json en el mismo commit."
    )

    bajaron, cayeron_a_cero, subieron = [], [], []
    for clave, n_esperado in esperado.items():
        n = obtenido[clave]
        if n == n_esperado:
            continue
        if n == 0 and n_esperado > 0:
            cayeron_a_cero.append(f"{clave}: {n_esperado} -> 0")
        elif n < n_esperado:
            bajaron.append(f"{clave}: {n_esperado} -> {n}")
        else:
            subieron.append(f"{clave}: {n_esperado} -> {n}")

    assert not cayeron_a_cero, (
        "UN PATRON CAYO A CERO HABIENDO TENIDO COINCIDENCIAS: "
        + "; ".join(cayeron_a_cero)
        + ". Casi siempre es un PREFIJO MAL ESCRITO. En el arranque solo habria "
          "producido un AVISO, y esta es la unica prueba que lo ve."
    )
    assert not bajaron, (
        "REGRESION DE COBERTURA: " + "; ".join(bajaron)
        + ". Algo dejo de revocarse. NO se arregla actualizando la linea base."
    )
    assert not subieron, (
        "La cobertura SUBIO: " + "; ".join(subieron)
        + ". Suele significar motor nuevo con sobrecargas nuevas. Comprueba que "
          "las nuevas son de la misma familia y actualiza "
          "datos/linea-base-revocaciones.json en el mismo commit, con la version "
          "del motor. Falla a proposito: un aviso que solo se imprime no lo lee nadie."
    )

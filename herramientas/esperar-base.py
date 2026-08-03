"""
Espera a que la base este LISTA DE VERDAD, no solo respondiendo.

POR QUE NO BASTA CON EL HEALTHCHECK DEL CONTENEDOR
---------------------------------------------------
`docker compose up --wait` espera al healthcheck, y el healthcheck usa
`pg_isready` **por el socket local**. Durante la inicializacion, la imagen de
PostgreSQL arranca un servidor temporal que escucha en ese socket y NO acepta
TCP. Es decir: el healthcheck puede dar verde antes de que los scripts de
`docker-entrypoint-initdb.d` hayan cargado los datos.

Aqui se espera desde FUERA, por TCP, y ademas se afirma que los datos estan.
Una base que responde sin datos haria caer las pruebas de invariantes con un
mensaje que no explicaria nada.

HONESTIDAD SOBRE ESTE FICHERO
------------------------------
La carrera descrita **no se ha observado** en la maquina de desarrollo: al
medirla, el healthcheck ya llegaba correcto y esto no espero ni un segundo.
Se mantiene como seguro, no como correccion de un fallo visto. Si algun dia
sobra, sobrara en silencio y costara dos segundos.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

INTENTOS = 60
ESPERA = 2


def _cargar_env() -> None:
    fichero = RAIZ / ".env"
    if not fichero.exists():
        return
    for linea in fichero.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, _, valor = linea.partition("=")
        os.environ.setdefault(clave.strip(), valor.strip())


def main() -> int:
    _cargar_env()
    url = os.environ.get("DATABASE_URL_OWNER")
    if not url:
        print("Falta DATABASE_URL_OWNER. Copia .env.example a .env.")
        return 2

    import psycopg

    for intento in range(1, INTENTOS + 1):
        try:
            with psycopg.connect(url, connect_timeout=3) as conexion:
                filas = conexion.execute(
                    "SELECT count(*) FROM cartera.cuotas"
                ).fetchone()[0]
            if filas == 0:
                raise RuntimeError("responde, pero el init no cargo datos")
            print(f"init terminado: {filas} cuotas")
            return 0
        except Exception as e:  # noqa: BLE001 — cualquier fallo es «aun no»
            print(f"  intento {intento}/{INTENTOS}: {type(e).__name__}: {e}"[:120])
            time.sleep(ESPERA)

    print(f"La base nunca quedo lista tras {INTENTOS * ESPERA}s.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

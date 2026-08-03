"""
Conexiones para las pruebas.

DOS CONEXIONES, Y LA DISTINCION NO ES COSMETICA
-----------------------------------------------
`conexion_owner`  ejecuta las aserciones de privilegios y, mas adelante, el
                  testigo externo de T-7(c). Un testigo que viviera en el
                  mismo proceso y el mismo rol que lo observado no seria un
                  testigo.
`conexion_ro`     es la credencial con la que corre la aplicacion. Cualquier
                  prueba que afirme algo sobre la contencion tiene que usar
                  esta, no la del dueño.

NO HAY `skip` SI LA BASE NO RESPONDE
------------------------------------
T-8 es la prueba que detecta la erosion de privilegios dentro de seis meses.
Una prueba de seguridad que se salta sola cuando falta el entorno es una
prueba que un dia deja de correr sin que nadie se entere. Si no hay base,
falla.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]


def _cargar_env() -> None:
    """Lee `.env` sin dependencias externas. Las variables ya definidas mandan."""
    fichero = RAIZ / ".env"
    if not fichero.exists():
        return
    for linea in fichero.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        os.environ.setdefault(clave.strip(), valor.strip())


_cargar_env()


def _conectar(nombre_variable: str):
    import psycopg

    url = os.environ.get(nombre_variable)
    if not url:
        pytest.fail(
            f"Falta {nombre_variable}. Copia .env.example a .env y levanta la base "
            f"con `docker compose up -d`. T-8 no se salta: se ejecuta o falla."
        )
    return psycopg.connect(url, autocommit=True)


@pytest.fixture(scope="session")
def conexion_owner():
    con = _conectar("DATABASE_URL_OWNER")
    yield con
    con.close()


@pytest.fixture(scope="session")
def conexion_ro():
    con = _conectar("DATABASE_URL_RO")
    yield con
    con.close()

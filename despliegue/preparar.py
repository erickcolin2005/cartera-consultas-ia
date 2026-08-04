"""
Prepara la base del despliegue. Idempotente: se ejecuta en cada arranque.

POR QUE EXISTE
---------------
En local, el esquema lo carga el entrypoint de la imagen de PostgreSQL desde
`docker-entrypoint-initdb.d`, una sola vez, con el volumen vacio. Una base
gestionada —la de Render— no tiene ese gancho: te dan una base vacia y una
cadena de conexion, y el esquema lo pones tu.

Este script hace eso, y **tiene que poder correr en cada arranque sin romper
nada**, porque en una plataforma que reinicia el servicio cuando le parece no
hay un "primer arranque" identificable.

COMO SABE SI YA ESTA HECHO
----------------------------
Pregunta si existe la vista `consulta.cuotas`. No usa una marca propia —una
tabla `migraciones`, un fichero centinela— a proposito: una marca puede quedar
puesta con el esquema a medias, y entonces el sistema arranca creyendo que
esta listo. Preguntar por lo que de verdad hace falta no tiene ese modo de
fallo.

LO QUE ESTE SCRIPT NO GARANTIZA, Y HAY QUE VERIFICARLO EN EL PRIMER DESPLIEGUE
-------------------------------------------------------------------------------
Los scripts crean el rol restringido `consulta_ro` y le revocan `EXECUTE` sobre
324 rutinas del motor. **Eso necesita permisos que una base gestionada puede no
dar**: el usuario que entrega Render es dueño de la base, no superusuario.

  - `CREATE ROLE` suele estar permitido (el usuario tiene CREATEROLE).
  - `REVOKE EXECUTE ... FROM PUBLIC` sobre funciones de `pg_catalog` **es de
    superusuario**, y ahi es donde esto puede caerse.

Si esa parte falla, **la capa 2 del despliegue no es la misma que la de local**,
y eso NO se puede dejar sin decir: el README tendria que declarar que la demo
publica corre con una contencion menor que la que el repositorio mide. La
alternativa honesta es no publicar la vía en español en la demo.

Por eso este script **no traga los errores**: si algo falla, sale con codigo
distinto de cero y el despliegue se cae. Un arranque que sigue adelante con las
revocaciones a medias seria el peor de los desenlaces — todo parece funcionar.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DATOS = RAIZ / "datos"

# El orden importa y es el mismo que el del entrypoint local.
GUION = [
    "01-esquema.sql",
    "02-permisos.sql",
    "03-revocaciones.sql",
    "04-datos.sql",
]


def _literal(valor: str) -> str:
    """Un literal de texto de PostgreSQL, con las comillas dobladas.

    `O'Brien` -> `'O''Brien'`. Es la regla del motor, no una invencion: dentro
    de un literal, dos comillas simples seguidas valen una.
    """
    return "'" + valor.replace("'", "''") + "'"


def _url_owner() -> str:
    url = os.environ.get("DATABASE_URL_OWNER") or os.environ.get("DATABASE_URL", "")
    if not url:
        print("Falta DATABASE_URL_OWNER (o DATABASE_URL).", file=sys.stderr)
        raise SystemExit(2)
    return url


def _ya_esta(conexion) -> bool:
    fila = conexion.execute(
        "SELECT to_regclass('consulta.cuotas') IS NOT NULL"
    ).fetchone()
    return bool(fila and fila[0])


def main() -> int:
    import psycopg

    if not os.environ.get("CLAVE_RO"):
        print("Falta CLAVE_RO: es la contraseña del rol restringido.", file=sys.stderr)
        return 2

    with psycopg.connect(_url_owner(), autocommit=True) as conexion:
        if _ya_esta(conexion):
            filas = conexion.execute("SELECT count(*) FROM cartera.cuotas").fetchone()[0]
            print(f"El esquema ya está: {filas} cuotas. No se toca nada.", flush=True)
            return 0

        print("Base vacía. Aplicando el esquema…", flush=True)
        for nombre in GUION:
            fichero = DATOS / nombre
            if not fichero.exists():
                print(f"Falta {fichero}", file=sys.stderr)
                return 1
            sql = fichero.read_text(encoding="utf-8")
            # Los scripts usan `:'clave_ro'`, que es la sintaxis de psql. Aqui
            # no hay psql, asi que se sustituye antes de enviar.
            #
            # Y se ESCAPA. Meter una clave en el texto de una sentencia con un
            # `replace` a secas es una inyeccion: basta una comilla simple en la
            # contraseña para partir el literal y ejecutar lo que siga. Que la
            # clave la ponga uno mismo no cambia nada — el proyecto entero
            # existe para no confiar en que la entrada sea la esperada, y este
            # script no es una excepcion por ser de arranque.
            sql = sql.replace(":'clave_ro'", _literal(os.environ["CLAVE_RO"]))
            print(f"  {nombre}…", flush=True)
            conexion.execute(sql)

        filas = conexion.execute("SELECT count(*) FROM cartera.cuotas").fetchone()[0]
        print(f"Esquema aplicado: {filas} cuotas.", flush=True)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

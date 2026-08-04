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

import json
import os
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DATOS = RAIZ / "datos"

# El orden importa y es el mismo que el del entrypoint local.
# Donde queda escrito lo que el arranque descubrio. Lo lee la pantalla para
# declarar, en la propia demo, con cuantas capas esta corriendo.
#
# Se escribe en cada arranque y NO se versiona: es un hecho de ESTE despliegue,
# no del repositorio. Un fichero versionado diria lo que paso en la maquina de
# quien lo commiteo, que es justo la confusion que hay que evitar.
ESTADO = Path(os.environ.get("ESTADO_DESPLIEGUE", RAIZ / "despliegue" / "estado.json"))

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


# Cuantas rutinas revoca el esquema cuando SI hay superusuario. Es el numero
# que mide `linea-base-revocaciones.json` en local; aqui sirve para deducir
# cuantas faltan cuando el arranque no vuelve a emitir el aviso.
ESPERADAS = 324


def _sin_privilegio(avisos: list[str]) -> int:
    """Lee el contador del aviso que emite 03-revocaciones.sql.

    Se lee del MOTOR y no se calcula aqui: el que sabe cuantas revocaciones no
    pudo aplicar es quien las intento.
    """
    for aviso in avisos:
        m = re.search(r"SIN PRIVILEGIO:\s*(\d+)", aviso)
        if m:
            return int(m.group(1))
    return 0


def _escribir_estado(aplicadas: int, sin_privilegio: int) -> None:
    ESTADO.parent.mkdir(parents=True, exist_ok=True)
    ESTADO.write_text(
        json.dumps(
            {
                "revocaciones_aplicadas": aplicadas,
                "revocaciones_sin_privilegio": sin_privilegio,
                "esperadas": ESPERADAS,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


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

    avisos: list[str] = []

    url = _url_owner()
    # Sin la clave: solo el host y la base, para poder ver en el log CONTRA QUE
    # se intento conectar sin publicar la credencial en el visor de la
    # plataforma —que es una herramienta web y no la controlamos—.
    import re as _re

    print(f"Conectando a {_re.sub(r'//[^@]*@', '//***@', url)}", flush=True)

    with psycopg.connect(url, autocommit=True) as conexion:
        quien = conexion.execute(
            "SELECT current_user, "
            "(SELECT rolsuper FROM pg_roles WHERE rolname = current_user), "
            "(SELECT rolcreaterole FROM pg_roles WHERE rolname = current_user)"
        ).fetchone()
        print(
            f"Usuario: {quien[0]} · superusuario: {quien[1]} · "
            f"puede crear roles: {quien[2]}",
            flush=True,
        )
        if not quien[2]:
            print(
                "AVISO: este usuario NO puede crear roles. `02-permisos.sql` "
                "necesita crear `consulta_ro`, que es el rol con el que la "
                "aplicacion se conecta. Sin el, no hay capa 1.",
                file=sys.stderr, flush=True,
            )

        conexion.add_notice_handler(lambda d: avisos.append(d.message_primary or ""))

        if _ya_esta(conexion):
            filas = conexion.execute("SELECT count(*) FROM cartera.cuotas").fetchone()[0]
            aplicadas = conexion.execute(
                "SELECT count(*) FROM cartera.revocacion_aplicada"
            ).fetchone()[0]
            # No se reaplica el esquema, asi que el aviso del motor no vuelve a
            # emitirse: el numero se deduce de lo que hay en la base. Es la
            # misma cifra por otro camino, y sin ella un reinicio dejaria a la
            # pantalla sin saber con cuantas capas esta corriendo.
            _escribir_estado(aplicadas, max(0, ESPERADAS - aplicadas))
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
            try:
                conexion.execute(sql)
            except Exception as e:  # noqa: BLE001
                # El log de una plataforma es lo UNICO que se va a poder mirar
                # cuando esto falle, y una traza de Python ahi no dice cual de
                # los cuatro scripts murio ni por que. Se dice, y se dice en la
                # primera linea: quien lee un despliegue caido lee dos lineas.
                print(f"FALLO en {nombre}", file=sys.stderr, flush=True)
                print(f"  {type(e).__name__}: {e}", file=sys.stderr, flush=True)
                estado = getattr(e, "sqlstate", None)
                if estado:
                    print(f"  SQLSTATE: {estado}", file=sys.stderr, flush=True)
                if estado == "42501":
                    print(
                        "  Es falta de PRIVILEGIO. Este motor no da lo que el "
                        "esquema necesita; mira despliegue/preparar.py.",
                        file=sys.stderr, flush=True,
                    )
                return 1

        filas = conexion.execute("SELECT count(*) FROM cartera.cuotas").fetchone()[0]
        aplicadas = conexion.execute(
            "SELECT count(*) FROM cartera.revocacion_aplicada"
        ).fetchone()[0]
        sin_privilegio = _sin_privilegio(avisos)

        _escribir_estado(aplicadas, sin_privilegio)
        print(f"Esquema aplicado: {filas} cuotas.", flush=True)
        print(f"Revocaciones aplicadas: {aplicadas} · sin privilegio: {sin_privilegio}",
              flush=True)
        if sin_privilegio:
            print(
                f"AVISO: {sin_privilegio} rutinas no se pudieron revocar. Este "
                f"motor no da superusuario, asi que la capa 2 de este despliegue "
                f"es MENOR que la que mide el repositorio. La pantalla lo declara.",
                flush=True,
            )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

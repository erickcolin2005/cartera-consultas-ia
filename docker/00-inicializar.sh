#!/usr/bin/env bash
# =====================================================================
# Init del contenedor de PostgreSQL. Se ejecuta UNA sola vez, cuando el
# volumen de datos esta vacio.
#
# POR QUE UN .sh Y NO CUATRO .sql SUELTOS
#   1. El orden importa: esquema -> permisos -> revocaciones -> datos.
#      Con ficheros sueltos el orden depende del nombre, que es fragil.
#   2. `02-permisos.sql` necesita la variable de psql :clave_ro, y el
#      entrypoint estandar no puede pasarla.
#   3. ON_ERROR_STOP=1 explicito: si una linea falla, el arranque falla.
#      Ese es el comportamiento que el diseño exige. Un contenedor que
#      arranca verde con una revocacion rota es peor que uno que no arranca.
#
# NUNCA se comenta una linea de los .sql para que este script pase.
# =====================================================================
set -euo pipefail

: "${CLAVE_RO:?falta CLAVE_RO: el rol consulta_ro no se crea sin clave declarada}"

DIR="/docker-entrypoint-initdb.d/datos"

ejecutar() {
    echo ">>> init: $1"
    psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
         --no-password --no-psqlrc \
         --set ON_ERROR_STOP=1 \
         --set "clave_ro=$CLAVE_RO" \
         --file "$DIR/$1"
}

ejecutar 01-esquema.sql
ejecutar 02-permisos.sql
ejecutar 03-revocaciones.sql
ejecutar 04-datos.sql

echo ">>> init: completado sin errores."

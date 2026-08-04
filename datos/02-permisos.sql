-- =====================================================================
-- 02-permisos.sql — CAPA 1 (privilegios) y CAPA 2 (alcance)
-- Fuente normativa: F2-diseno/modelo-datos.md rev. 3, §6.4
--
-- Nunca se comenta una linea para que el arranque pase. Ver 01-esquema.sql.
--
-- Requiere la variable de psql :clave_ro, que inyecta docker/00-inicializar.sh
-- desde la variable de entorno CLAVE_RO. Si no esta definida, psql aborta:
-- eso es correcto — un rol de solo lectura sin clave declarada no debe crearse.
-- =====================================================================

-- ============ CAPA 1 · Privilegios. Esto es la capa 1. ============
-- No es `default_transaction_read_only`: ese parametro es sobrescribible
-- desde la propia sesion. Lo que detiene un DELETE es que el rol no tenga
-- el privilegio, y eso no se puede desactivar desde dentro de una consulta.
-- IDEMPOTENTE. `CREATE ROLE` a secas rompia el reintento del despliegue: los
-- roles son del CLUSTER, no de la base, asi que si el arranque fallaba despues
-- de este punto —por ejemplo en las revocaciones— el siguiente intento moria
-- con "role already exists" y el despliegue quedaba atascado para siempre.
-- Se descubrio reproduciendo el despliegue de Render en local el 2026-08-04.
--
-- Se actualiza la clave tambien cuando ya existe: si no, un rol creado en un
-- intento anterior conservaria una clave que ya nadie conoce.
-- La clave viaja por un parametro de sesion y no directamente al bloque.
-- Motivo: psql NO sustituye sus variables dentro de un texto entrecomillado
-- con dolares, asi que `:'clave_ro'` ahi dentro llega literal y es un error de
-- sintaxis. Fuera del bloque si se sustituye, en los dos cargadores: psql en
-- local y `despliegue/preparar.py` en el despliegue.
SET cartera.clave_ro = :'clave_ro';

DO $rol$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'consulta_ro') THEN
        EXECUTE format('ALTER ROLE consulta_ro LOGIN PASSWORD %L',
                       current_setting('cartera.clave_ro'));
    ELSE
        EXECUTE format('CREATE ROLE consulta_ro LOGIN PASSWORD %L',
                       current_setting('cartera.clave_ro'));
    END IF;
END
$rol$;

-- La clave no se queda en la sesion mas de lo necesario.
RESET cartera.clave_ro;

-- ---- MAMPARO DE CONCURRENCIA (R-22) ----
-- Sin pool, nada acota las conexiones concurrentes: cada una se retiene hasta
-- 5 s por statement_timeout y compite por max_connections con el rol dueño,
-- que es quien ejecuta el testigo externo de T-7(c).
-- El 10 es juicio, no medicion (modelo-datos.md §10). La aserción A-9 registra
-- ademas el max_connections real para que el ajuste de F6 sea un dato.
ALTER ROLE consulta_ro CONNECTION LIMIT 10;

-- Cinturon adicional, reversible. NO es una capa, y asi se declara.
ALTER ROLE consulta_ro SET default_transaction_read_only = on;

-- Capa 4 aplicada por el motor.
ALTER ROLE consulta_ro SET statement_timeout = '5s';

-- Resolucion de nombres. Fragil ante set_config('search_path', ...):
-- por eso set_config se revoca en 03-revocaciones.sql.
ALTER ROLE consulta_ro SET search_path = consulta;

-- ============ CAPA 2 · Solo existe el esquema `consulta`. ============
REVOKE ALL ON SCHEMA public  FROM PUBLIC;
REVOKE ALL ON SCHEMA cartera FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA cartera FROM PUBLIC;

GRANT USAGE  ON SCHEMA consulta                  TO consulta_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA consulta    TO consulta_ro;   -- las 4 vistas, SOLO SELECT
GRANT EXECUTE ON FUNCTION consulta.fecha_corte() TO consulta_ro;

-- information_schema SI filtra por privilegios; se revoca igual porque es
-- gratis. El efecto exacto queda comprobado por la aserción A-6.
REVOKE USAGE ON SCHEMA information_schema FROM PUBLIC;

-- Nota deliberada: NO se concede INSERT/UPDATE/DELETE sobre ninguna vista.
-- `consulta.propietarios` es una vista de una sola tabla sin JOIN ni agregados
-- y por tanto seria auto-actualizable: la AUSENCIA de GRANT es lo unico que
-- cierra esa puerta, y por eso la aserción A-1 exige exactamente 4 privilegios.

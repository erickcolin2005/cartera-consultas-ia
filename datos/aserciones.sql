-- =====================================================================
-- aserciones.sql — A-1 ... A-9 · la prueba T-8
-- Fuente normativa: F2-diseno/modelo-datos.md rev. 3, §6.6
--
-- QUE PRUEBA T-8 Y POR QUE ES LA PRIMERA DEL REPOSITORIO
--   El DDL CREA el rol pero no AFIRMA nada sobre el. "Por defecto no
--   pertenece a ningun rol predefinido" es probablemente cierto, pero
--   "por defecto" no es una garantia verificable: un solo
--   GRANT pg_read_all_data anula la capa 2 entera.
--   T-8 es la prueba que detectara esa erosion dentro de seis meses.
--
-- SON ASERCIONES, NO CORRECCIONES
--   Si una falla, el problema NO es que falte un GRANT: es que alguien
--   concedio algo que no debia. Eso hay que verlo, no repararlo en silencio.
--
-- COMO SE EJECUTA
--   - A mano:  psql -f datos/aserciones.sql   (imprime los resultados)
--   - En CI:   tests/test_t8_privilegios.py lee ESTE fichero, ejecuta cada
--              bloque y compara con el valor exigido. El SQL vive aqui y solo
--              aqui; el test no tiene una segunda copia que se desincronice.
--
-- FORMATO PARA EL LECTOR AUTOMATICO
--   Cada aserción empieza con una linea `-- @asercion A-n | titulo` y
--   contiene UNA sola sentencia terminada en `;`.
-- =====================================================================

-- @asercion A-1 | Privilegios de tabla/vista del rol, por (esquema, objeto, privilegio)
-- Exigido: EXACTAMENTE 4 filas, SELECT sobre las cuatro vistas de `consulta`.
-- Ni una mas. Se miran tambien los privilegios de COLUMNA: un GRANT de
-- columna no aparece en el ACL de la relacion y dejaria un hueco invisible.
SELECT n.nspname AS esquema, c.relname AS objeto, a.privilege_type AS privilegio
FROM   pg_class c
JOIN   pg_namespace n ON n.oid = c.relnamespace
CROSS  JOIN LATERAL aclexplode(c.relacl) a
WHERE  a.grantee = 'consulta_ro'::regrole
UNION ALL
SELECT n.nspname, c.relname || '.' || att.attname, a.privilege_type
FROM   pg_attribute att
JOIN   pg_class c     ON c.oid = att.attrelid
JOIN   pg_namespace n ON n.oid = c.relnamespace
CROSS  JOIN LATERAL aclexplode(att.attacl) a
WHERE  a.grantee = 'consulta_ro'::regrole
ORDER  BY 1, 2, 3;

-- @asercion A-2 | Pertenencia del rol a otros roles
-- Exigido: conjunto VACIO. Explicitamente ni pg_read_all_data,
-- pg_write_all_data, pg_read_server_files, pg_write_server_files,
-- pg_execute_server_program, pg_monitor ni pg_signal_backend.
SELECT r.rolname AS rol_del_que_es_miembro
FROM   pg_auth_members m
JOIN   pg_roles r ON r.oid = m.roleid
WHERE  m.member = 'consulta_ro'::regrole
ORDER  BY 1;

-- @asercion A-3 | Atributos del rol
-- Exigido: los cinco en false.
SELECT rolsuper, rolcreatedb, rolcreaterole, rolbypassrls, rolreplication
FROM   pg_roles
WHERE  rolname = 'consulta_ro';

-- @asercion A-4 | Propiedad de objetos
-- Exigido: conjunto VACIO. Es lo que hace imposible M-15: quien no es dueño
-- de nada no puede conceder nada.
SELECT n.nspname AS esquema, c.relname AS objeto, c.relkind::text AS clase
FROM   pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE  c.relowner = 'consulta_ro'::regrole
UNION ALL
SELECT n.nspname, p.proname, 'rutina'
FROM   pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE  p.proowner = 'consulta_ro'::regrole
UNION ALL
SELECT nspname, nspname, 'esquema' FROM pg_namespace WHERE nspowner = 'consulta_ro'::regrole
UNION ALL
SELECT datname, datname, 'base'    FROM pg_database  WHERE datdba   = 'consulta_ro'::regrole
ORDER  BY 1, 2;

-- @asercion A-5 | EXECUTE sobre la lista revocada, en TODAS las sobrecargas
-- Exigido: conjunto VACIO.
-- Comprueba POR NOMBRE Y POR PREFIJO contra cartera.politica_revocacion, que
-- es la misma lista que uso 03-revocaciones.sql, y con la MISMA traduccion
-- glob->LIKE. Nunca por firma escrita a mano: la version anterior de esta
-- aserción comprobaba firmas concretas y por tanto habria dado verde con una
-- sobrecarga sin revocar.
SELECT (pr.oid::regprocedure)::text AS firma_todavia_ejecutable
FROM   pg_proc pr
JOIN   pg_namespace ns ON ns.oid = pr.pronamespace
WHERE  ns.nspname <> 'consulta'
  AND  EXISTS (
         SELECT 1
         FROM   cartera.politica_revocacion p
         WHERE  (p.clase = 'nombre'  AND pr.proname = p.patron)
            OR  (p.clase = 'prefijo' AND pr.proname LIKE cartera.glob_a_like(p.patron) ESCAPE '\')
       )
  AND  has_function_privilege('consulta_ro', pr.oid, 'EXECUTE')
ORDER  BY 1;

-- @asercion A-6 | Privilegios de esquema, medidos por su EFECTO
-- Exigido: USAGE solo sobre `consulta`.
--   cartera            -> false
--   consulta           -> true
--   information_schema -> false
--   public             -> false
--   pg_catalog         -> TRUE, y es la limitacion declarada de §6.7:
--                         pg_catalog no se puede revocar de forma fiable.
--                         Esta fila esta aqui a proposito: una aserción que
--                         solo muestra lo que sale bien no verifica nada.
SELECT nspname AS esquema,
       has_schema_privilege('consulta_ro', nspname, 'USAGE') AS usage_efectivo
FROM   pg_namespace
WHERE  nspname IN ('cartera','consulta','information_schema','public','pg_catalog')
ORDER  BY 1;

-- @asercion A-7 | Extensiones instaladas
-- Exigido: solo las de la imagen por defecto, ENUMERADAS.
-- Cierra dblink, postgres_fdw y los lenguajes procedurales.
SELECT extname FROM pg_extension ORDER BY 1;

-- @asercion A-8 | Parametros fijados en el rol
-- Exigido, exactamente estos tres:
--   default_transaction_read_only=on, search_path=consulta, statement_timeout=5s
SELECT cfg AS parametro
FROM   pg_roles r, LATERAL unnest(r.rolconfig) AS cfg
WHERE  r.rolname = 'consulta_ro'
ORDER  BY 1;

-- @asercion A-10 | Cobertura de la revocacion, familia por familia
-- Exigido: coincidir EXACTAMENTE con datos/linea-base-revocaciones.json.
--
-- QUE HUECO CIERRA — es el hallazgo de Q-6 convertido en control.
--   La regla dice: nombre exacto sin coincidencias = ERROR; prefijo sin
--   coincidencias = AVISO. Correcto, pero deja un hueco: un prefijo MAL
--   ESCRITO (`pg_slee_*` en vez de `pg_sleep*`) produce un AVISO, y quien lo
--   lea creera que la familia esta cubierta. El aviso no distingue "esta
--   familia no existe en este motor" de "escribi mal el prefijo".
--   Con la linea base, `pg_sleep*` = 3 y `pg_slee_*` = 0: el error de
--   escritura se ve. Es la misma idea que A-1 —CONJUNTO EXACTO, no ausencia—
--   aplicada a las revocaciones, y es lo que detecta la erosion en seis meses.
--
-- DOS NUMEROS, Y NO SIGNIFICAN LO MISMO
--   Las filas por patron cuentan COINCIDENCIAS EN EL CATALOGO. Su suma es 326.
--   La ultima fila cuenta RUTINAS DISTINTAS revocadas: 324. La diferencia son
--   inet_server_addr e inet_client_addr, cubiertas a la vez por nombre exacto
--   y por el prefijo inet_*_addr. Versionar 326 como "rutinas" seria repetir
--   el error de atribucion que esta ronda vino a corregir.
--
-- A-10 mide COBERTURA (cuantas hay que revocar). A-5 mide EFECTO (que ninguna
-- siga siendo ejecutable). Hacen falta las dos: A-5 pasaria en verde si la
-- lista se quedara vacia por un prefijo mal escrito, porque no habria nada
-- que comprobar.
SELECT p.clase, p.patron, count(pr.oid)::int AS rutinas
FROM   cartera.politica_revocacion p
LEFT   JOIN pg_proc pr
       ON   pr.pronamespace <> 'consulta'::regnamespace
       AND  ( (p.clase = 'nombre'  AND pr.proname = p.patron)
           OR (p.clase = 'prefijo' AND pr.proname LIKE cartera.glob_a_like(p.patron) ESCAPE '\') )
GROUP  BY p.clase, p.patron
UNION ALL
SELECT 'total', 'rutinas_distintas_revocadas', count(*)::int
FROM   cartera.revocacion_aplicada
ORDER  BY 1, 2;

-- @asercion A-9 | CONNECTION LIMIT del rol, y el max_connections de la instancia
-- Exigido: limite FINITO y <= 10. Fallo si es -1 (sin limite).
-- El max_connections NO se afirma: se registra, para que el ajuste de F6
-- contra la plataforma sea un dato y no una intuicion.
SELECT r.rolconnlimit                        AS connection_limit_del_rol,
       current_setting('max_connections')::int AS max_connections_instancia
FROM   pg_roles r
WHERE  r.rolname = 'consulta_ro';

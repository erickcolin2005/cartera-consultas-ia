-- =====================================================================
-- verificacion-manual.sql — criterio de terminado de I-1
-- Fuente normativa: F2-diseno/modelo-datos.md rev. 3, §6.8
--
-- SE EJECUTA CONECTADO COMO `consulta_ro`, NO como el rol dueño.
--   psql "$DATABASE_URL_RO" -f datos/verificacion-manual.sql
--   (sin ON_ERROR_STOP: aqui los errores SON el resultado esperado)
--
-- OCHO LINEAS DEBEN FALLAR. DOS DEBEN FUNCIONAR.
--   Un guion de verificacion que solo enseña lo que sale bien no verifica
--   nada. Este enseña tambien el limite que el proyecto declara.
--
-- ⚠ LA AUTORIDAD SOBRE PRIVILEGIOS LA TIENE T-8, NO ESTE GUION.
--   Este guion comprueba que ciertas sentencias no prosperan. NO comprueba
--   POR QUE no prosperan, y la corrida del 2026-08-02 demostro que en varias
--   lineas el motivo real no era el que estos comentarios decian.
--   Consecuencia concreta: si alguien concediera DELETE sobre `consulta.pagos`
--   por error, ESTE GUION SEGUIRIA FALLANDO IGUAL —la forma de la vista lo
--   impide— y un revisor concluiria que "la capa 1 funciona" mientras hay un
--   privilegio mal concedido. LA FORMA ENMASCARA UNA REGRESION DE PRIVILEGIOS.
--   Quien detecta ese caso es la asercion A-1 (conjunto exacto, en T-8), que
--   corre en cada push. El control esta; lo que engaña es este guion.
--
-- REGLA QUE SALE DE AHI, y aplica a toda prueba negativa del proyecto:
--   UNA PRUEBA NEGATIVA DEBE AFIRMAR LA *CLASE* DEL FALLO, NO SOLO QUE HUBO
--   FALLO. "DELETE falla" no vale. "DELETE falla con un error de permiso" si.
--   Sin eso, una prueba pasa por el motivo equivocado y enmascara la regresion
--   del control que dice estar midiendo.
--
-- LAS DOS LINEAS QUE MERECEN ATENCION:
--   · current_setting('data_directory', true) usa la sobrecarga de DOS
--     argumentos. Esta aqui a proposito: si esta linea FUNCIONA, se revoco
--     una firma y no la familia, y la correccion de la rev. 3 no se aplico.
--   · SELECT relname FROM pg_class FUNCIONA a proposito. Es la excepcion de
--     §6.7: pg_catalog no filtra por privilegios y no se puede revocar de
--     forma fiable. Es incumplimiento literal de RNF-02 y se declara.
-- =====================================================================

-- CORREGIDO 2026-08-02 [V-motor]. El comentario anterior decia "falla: sin
-- privilegio DELETE (capa 1 real)" y ERA FALSO: el privilegio no llega a
-- comprobarse. PostgreSQL rechaza en la reescritura, antes del control de
-- permisos. El privilegio ESTA puesto, pero esta linea no lo prueba.
-- Quien lo prueba es la linea A1 del anexo, sobre `propietarios`.
\echo '=== 1/10 · DELETE FROM pagos  -> DEBE FALLAR: la vista no es auto-actualizable ==='
\echo '        NO PRUEBA EL PRIVILEGIO. Ver la linea A1 del anexo, que si lo prueba.'
DELETE FROM pagos;

-- CORREGIDO 2026-08-02 [V-motor]. El comentario anterior decia "falla: no es
-- dueño, sin privilegios". Lo que lo detiene es el CINTURON REVERSIBLE, es
-- decir, el parametro que el propio diseño degrada de "capa" a "cinturon".
-- Que los privilegios lo detengan IGUALMENTE esta razonado (el rol no es dueño
-- —A-4— y no tiene USAGE sobre `cartera` —A-6—) y PENDIENTE DE PROBAR: es la
-- condicion G4-SEC-1, con el cinturon quitado. No se ejecuta aqui.
\echo '=== 2/10 · DROP TABLE cartera.cuotas  -> DEBE FALLAR: transaccion de solo lectura ==='
\echo '        Lo detiene el cinturon, NO el privilegio. Lo de debajo esta sin probar (G4-SEC-1).'
DROP TABLE cartera.cuotas;

\echo '=== 3/10 · SELECT * FROM cartera.propietarios  -> DEBE FALLAR (esquema no alcanzable) ==='
SELECT * FROM cartera.propietarios;

\echo '=== 4/10 · SELECT documento FROM propietarios  -> DEBE FALLAR (columna no publicada) ==='
SELECT documento FROM propietarios;

\echo '=== 5/10 · set_config(...)  -> DEBE FALLAR (EXECUTE revocado) ==='
SELECT set_config('default_transaction_read_only','off',false);

\echo '=== 6/10 · query_to_xml(...)  -> DEBE FALLAR (EXECUTE revocado) ==='
SELECT query_to_xml('SELECT 1', true, false, '');

\echo '=== 7/10 · has_table_privilege(...)  -> DEBE FALLAR (EXECUTE revocado) ==='
SELECT has_table_privilege('cartera.propietarios','SELECT');

\echo '=== 8/10 · current_setting(text, boolean)  -> DEBE FALLAR (SOBRECARGA revocada) ==='
SELECT current_setting('data_directory', true);

\echo '=== 9/10 · SELECT relname FROM pg_class  -> DEBE FUNCIONAR (excepcion declarada, §6.7) ==='
SELECT relname FROM pg_class LIMIT 5;

\echo '=== 10/10 · SELECT * FROM consulta.cuotas  -> DEBE FUNCIONAR ==='
SELECT id, unidad_codigo, periodo, valor, saldo, estado, dias_vencida
FROM consulta.cuotas ORDER BY id LIMIT 5;


-- =====================================================================
-- ANEXO · Ejecucion del 2026-08-02 contra PostgreSQL 16.10
--
-- Las diez lineas de arriba salieron como el diseño exigia: ocho fallan, dos
-- funcionan. Pero DOS DE ELLAS NO FALLAN POR EL MOTIVO QUE EL COMENTARIO
-- DECIA, y eso importa mas que el resultado.
--
--   Linea 1 · DELETE FROM pagos
--     Esperado: "sin privilegio DELETE (capa 1 real)".
--     Real:     ERROR: cannot delete from view "pagos"
--               DETAIL: Views that do not select from a single table or view
--               are not automatically updatable.
--     Lo detuvo la FORMA de la vista (lleva JOIN), no el privilegio. El
--     privilegio nunca se llego a comprobar. Si alguien simplificara
--     `consulta.pagos` a una vista de una sola tabla, esta linea cambiaria de
--     mecanismo sin cambiar de resultado — y nadie se enteraria.
--
--   Linea 2 · DROP TABLE cartera.cuotas
--     Esperado: "no es dueño, sin privilegios".
--     Real:     ERROR: cannot execute DROP TABLE in a read-only transaction
--     Lo detuvo `default_transaction_read_only`, que el propio diseño declara
--     como CINTURON REVERSIBLE Y NO COMO CAPA. La comprobacion de privilegios
--     nunca se ejecuto.
--
--   M-10 · TRUNCATE TABLE cuotas  (ejecutado aparte, 2026-08-02)
--     `security-agent` predijo una TERCERA atribucion equivocada distinta:
--     que con `search_path = consulta`, `cuotas` resolveria a una VISTA y el
--     error seria de tipo de objeto ("cuotas is not a table").
--     Real:     ERROR: cannot execute TRUNCATE TABLE in a read-only transaction
--     LA PREDICCION TAMBIEN ERA INCORRECTA. El cinturon actua ANTES que la
--     comprobacion de tipo de objeto. Y ocurre igual en las tres variantes:
--     sobre la vista con JOIN (`cuotas`), sobre la tabla base
--     (`cartera.cuotas`) y sobre la vista auto-actualizable (`propietarios`).
--     Es decir: M-02 y M-10 —dos de las quince filas de C2— hoy las detiene
--     en el motor el mismo parametro reversible. Lo que hay debajo sigue sin
--     medirse en los dos casos (G4-SEC-1).
--
-- Consecuencia: tal como estan escritas, estas lineas NO demuestran que
-- la capa 1 sean los privilegios. Demuestran que algo lo detuvo.
--
-- El bloque de abajo SI lo demuestra, y por eso se añade. No sustituye a
-- ninguna de las diez: las diez se conservan literales.
-- =====================================================================

\echo ''
\echo '=== ANEXO · con el cinturon QUITADO: que detiene la escritura de verdad ==='
SET default_transaction_read_only = off;

\echo '--- A1 · DELETE sobre consulta.propietarios (vista AUTO-ACTUALIZABLE) ---'
\echo '    Esta es la prueba buena: la vista SI acepta DELETE por su forma, asi'
\echo '    que lo unico que puede detenerlo es el privilegio que no se concedio.'
\echo '    Resultado 2026-08-02: ERROR: permission denied for view propietarios'
DELETE FROM propietarios;

\echo '--- A2 · UPDATE sobre la misma vista ---'
UPDATE propietarios SET nombre = 'x';

\echo '--- A3 · DELETE directo sobre la tabla base -> capa 2 ---'
DELETE FROM cartera.pagos;

\echo '--- A4 · DROP con el cinturon quitado -> capa 2, no el parametro ---'
DROP TABLE cartera.cuotas;

\echo '--- A5 · M-15 · GRANT. ATENCION: NO da error, da WARNING y no concede nada ---'
\echo '    Resultado 2026-08-02: WARNING: no privileges were granted ... y luego GRANT.'
\echo '    La sentencia se ejecuta CON EXITO y no surte efecto. Para T-2 esto'
\echo '    significa que la asercion de M-15 debe ser "ningun privilegio cambio",'
\echo '    NO "la sentencia fallo": esperar un error dejaria la prueba en rojo'
\echo '    con un sistema que se comporta correctamente.'
GRANT ALL PRIVILEGES ON propietarios TO PUBLIC;

\echo '--- A6 · §6.7 es peor de lo escrito: el nombre del INDICE filtra la columna ---'
\echo '    `documento` no se publica en ninguna vista, pero el indice UNIQUE que'
\echo '    la protege se llama propietarios_documento_key y pg_class lo enseña.'
SELECT relname FROM pg_class WHERE relname LIKE '%documento%';

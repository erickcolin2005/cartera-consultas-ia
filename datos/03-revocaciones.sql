-- =====================================================================
-- 03-revocaciones.sql — REVOKE EXECUTE sobre TODAS las sobrecargas
-- Fuente normativa: F2-diseno/modelo-datos.md rev. 3, §6.5 y §7.5
--
-- POR QUE ESTE ARCHIVO EXISTE
--   PostgreSQL concede EXECUTE a PUBLIC por defecto. Sin esto, toda la
--   familia de funciones peligrosas del motor dependeria unicamente de la
--   regla S4 del guardian, que es codigo — y S4 seria el unico control de
--   toda la arquitectura sin ninguna capa debajo.
--   Esto es capa 1, no capa 3.
--
-- POR QUE NO HAY NI UNA FIRMA ESCRITA A MANO
--   `current_setting(text)` y `current_setting(text, boolean)` son DOS
--   funciones distintas: revocar una deja la otra viva. Escribir firmas de
--   memoria produce exactamente ese fallo. El procedimiento normativo de
--   tres pasos de §6.5 dice: (1) para cada NOMBRE, consultar el catalogo y
--   obtener TODAS sus sobrecargas; (2) emitir un REVOKE por cada sobrecarga;
--   (3) verificar con la aserción A-5, que comprueba por nombre y por
--   prefijo, nunca por firma.
--   Este archivo implementa los pasos 1 y 2. El 3 vive en aserciones.sql.
--
-- REGLA QUE NO SE NEGOCIA
--   Si un NOMBRE de la lista no existe en este motor, el script FALLA EN VOZ
--   ALTA al final, con la lista de nombres huerfanos. Se corrige el nombre y
--   se vuelve a ejecutar. NUNCA se comenta la linea para que el arranque pase.
--
-- CONTRADICCION DECLARADA, NO RESUELTA AQUI (Q-6 del plan de construccion)
--   `modelo-datos.md` §6.5 exige fallar en voz alta ante una funcion que no
--   existe; la aserción A-5 de §6.6 dice que una funcion inexistente "se
--   declara y no rompe la prueba". Los dos modos de fallo no coinciden.
--   Criterio aplicado aqui, y es una decision de ingenieria que hay que
--   ratificar en G3-SEC-1:
--     - clase 'nombre'  -> cero coincidencias = ERROR. Un nombre exacto que
--       no existe es casi siempre un nombre mal escrito.
--     - clase 'prefijo' -> cero coincidencias = AVISO. Un prefijo existe
--       precisamente para cubrir lo que aun no existe (§7.5); exigirle
--       coincidencias contradiria su razon de ser. `dblink*` es el ejemplo:
--       sin la extension instalada no hay nada que revocar, y eso es correcto.
--
-- DESVIACION DEL DISEÑO, DECLARADA (para `architect-agent`)
--   Se crean dos tablas de apoyo en el esquema `cartera`:
--     - cartera.politica_revocacion : la lista, como DATO y no duplicada en
--       dos ficheros. Sin ella, la lista viviria escrita dos veces (aqui y en
--       la aserción A-5) y se desincronizaria en silencio — que es el modo de
--       fallo R-20 que este proyecto critica.
--     - cartera.revocacion_aplicada : la salida real de la ejecucion, para
--       que G3-SEC-1 (D23) pueda registrarla con la evidencia y no con un
--       "se comprobo".
--   Ninguna de las dos es alcanzable por `consulta_ro`: viven en `cartera`,
--   sobre el que el rol no tiene ningun privilegio (aserciones A-1 y A-6).
-- =====================================================================

CREATE TABLE cartera.politica_revocacion (
    clase      text NOT NULL CHECK (clase IN ('nombre','prefijo')),
    patron     text NOT NULL,
    grupo      text NOT NULL,
    comentario text,
    PRIMARY KEY (clase, patron)
);

CREATE TABLE cartera.revocacion_aplicada (
    oid_funcion oid  PRIMARY KEY,
    firma       text NOT NULL,
    esquema     text NOT NULL,
    clase       text NOT NULL,
    patron      text NOT NULL,
    aplicada_en timestamptz NOT NULL DEFAULT now()
);

-- Traduccion glob -> LIKE, en un solo sitio. `_` y `%` son literales dentro
-- del nombre de una funcion; `*` es el comodin. Sin escapar `_`, el patron
-- `pg_sleep*` coincidiria con cualquier caracter en esa posicion.
-- Vive aqui para que la revocacion y la aserción A-5 usen EXACTAMENTE la
-- misma traduccion. Dos copias divergen; una no puede.
CREATE FUNCTION cartera.glob_a_like(patron text) RETURNS text
    LANGUAGE sql IMMUTABLE
    AS $$ SELECT replace(replace(replace(replace($1,'\','\\'),'_','\_'),'%','\%'),'*','%') $$;

-- ---------------------------------------------------------------------
-- La lista de §6.5, transcrita literalmente. Ni un nombre inventado.
-- ---------------------------------------------------------------------

-- Grupo 1 — cambian el estado de la sesion. Es el grupo critico.
INSERT INTO cartera.politica_revocacion (clase, patron, grupo, comentario) VALUES
 ('nombre','set_config','1 · estado de sesion','M-16. Desactiva la capa 1 y el search_path desde dentro de un SELECT impecable');

-- Grupo 2 — leen la estructura sin nombrar ninguna relacion.
INSERT INTO cartera.politica_revocacion (clase, patron, grupo, comentario) VALUES
 ('prefijo','pg_get_*','2 · estructura','pg_get_viewdef (M-18) revela el SQL de las vistas y con el cartera.*; incluye functiondef, constraintdef, indexdef, expr, userbyid'),
 ('nombre','to_regclass','2 · estructura','M-32. Oraculo de existencia silencioso: devuelve NULL en vez de error'),
 ('nombre','obj_description','2 · estructura','lee comentarios del catalogo'),
 ('nombre','col_description','2 · estructura','lee comentarios del catalogo'),
 ('nombre','shobj_description','2 · estructura','lee comentarios del catalogo'),
 ('prefijo','has_*_privilege','2 · estructura','M-34. LA MAS AFILADA: booleano + error si no existe + argumentos de TEXTO PLANO. Ni S3 ni S7a la ven'),
 ('nombre','pg_relation_filepath','2 · estructura','ruta fisica de una relacion'),
 ('prefijo','pg_*_size','2 · estructura','pg_relation_size, pg_total_relation_size, pg_database_size...: revelan que existe y cuanto ocupa'),
 ('prefijo','pg_stat_get_*','2 · estructura','la FORMA DE FUNCION de las vistas de estadisticas: alcanza lo mismo sin nombrar ninguna relacion');

-- Grupo 3 — leen el entorno.
INSERT INTO cartera.politica_revocacion (clase, patron, grupo, comentario) VALUES
 ('nombre','current_setting','3 · entorno','M-21. Introspeccion GENERICA: permitir una entrada no abre un dato, abre TODOS los parametros'),
 ('nombre','version','3 · entorno','huella del despliegue (M-22)'),
 ('nombre','current_database','3 · entorno','huella del despliegue'),
 ('nombre','current_schemas','3 · entorno','huella del despliegue'),
 ('nombre','inet_server_addr','3 · entorno','M-22. red interna del contenedor'),
 ('nombre','inet_server_port','3 · entorno','red interna del contenedor'),
 ('nombre','inet_client_addr','3 · entorno','red interna del contenedor'),
 ('nombre','inet_client_port','3 · entorno','red interna del contenedor'),
 ('nombre','pg_backend_pid','3 · entorno','huella del proceso'),
 ('nombre','pg_postmaster_start_time','3 · entorno','huella del despliegue'),
 ('nombre','pg_conf_load_time','3 · entorno','huella del despliegue'),
 ('nombre','pg_current_logfile','3 · entorno','ruta del fichero de log');

-- Grupo 4 — leen ficheros o ejecutan.
INSERT INTO cartera.politica_revocacion (clase, patron, grupo, comentario) VALUES
 ('prefijo','pg_read_*','4 · ficheros','pg_read_file, pg_read_binary_file'),
 ('prefijo','pg_ls_*','4 · ficheros','pg_ls_dir, pg_ls_logdir, pg_ls_waldir'),
 ('nombre','pg_stat_file','4 · ficheros','metadatos de un fichero del servidor'),
 ('prefijo','lo_*','4 · ficheros','lo_import y lo_export escriben/leen ficheros y NO son DML: no esta claro que una transaccion de solo lectura las detenga');

-- Grupo 5 — la evasion estructural: SQL como literal de texto.
INSERT INTO cartera.politica_revocacion (clase, patron, grupo, comentario) VALUES
 ('prefijo','*_to_xml*','5 · SQL como literal','M-20. query_to_xml ATRAVIESA TODO EL ANALISIS ESTRUCTURAL: para el guardian el argumento es una cadena, no un subarbol. Este grupo y S4 son el unico control');

-- Grupo 6 — disponibilidad.
INSERT INTO cartera.politica_revocacion (clase, patron, grupo, comentario) VALUES
 ('prefijo','pg_sleep*','6 · disponibilidad','M-23. pg_sleep, pg_sleep_for y pg_sleep_until: las tres, no solo la primera');

-- Prefijos de §7.5 que no aparecen por nombre en §6.5 pero que la lista de
-- prohibidos-siempre del guardian declara. Se revocan tambien: los prefijos
-- envejecen mejor que los nombres sueltos porque cubren lo que aun no existe.
INSERT INTO cartera.politica_revocacion (clase, patron, grupo, comentario) VALUES
 ('prefijo','dblink*','7 · §7.5 prohibidos siempre','conexion saliente a otra base. Sin la extension instalada no habra coincidencias, y eso es correcto'),
 ('prefijo','inet_*_addr','7 · §7.5 prohibidos siempre','redundante con los nombres del grupo 3; se deja porque la lista del guardian lo declara asi'),
 ('nombre','generate_series','7 · §7.5 prohibidos siempre','generador de filas arbitrario: amplifica M-13');

-- ---------------------------------------------------------------------
-- Pasos 1 y 2 del procedimiento normativo
-- ---------------------------------------------------------------------
DO $revocar$
DECLARE
    p             record;
    f             record;
    patron_like   text;
    n_coincide    integer;
    total         integer := 0;
    n_distintas   integer;
    huerfanos     text[]  := '{}';
    -- Cuantas revocaciones NO se pudieron aplicar por falta de privilegio.
    -- En local, con superusuario, vale 0 y ese 0 es una asercion: si subiera,
    -- algo cambio en el motor. En una base gestionada sera >0, y ese numero es
    -- exactamente lo que la demo publica tiene que declarar.
    sin_privilegio integer := 0;
BEGIN
    FOR p IN SELECT clase, patron FROM cartera.politica_revocacion ORDER BY clase, patron
    LOOP
        patron_like := cartera.glob_a_like(p.patron);
        n_coincide  := 0;

        FOR f IN
            SELECT pr.oid,
                   pr.oid::regprocedure::text AS firma,
                   ns.nspname                 AS esquema
            FROM   pg_proc pr
            JOIN   pg_namespace ns ON ns.oid = pr.pronamespace
            WHERE  ( (p.clase = 'nombre'  AND pr.proname = p.patron)
                  OR (p.clase = 'prefijo' AND pr.proname LIKE patron_like ESCAPE '\') )
              -- Guarda de seguridad: nunca se toca lo que este proyecto publica.
              AND  ns.nspname <> 'consulta'
            ORDER BY 2
        LOOP
            -- ROUTINE cubre funciones y procedimientos sin tener que saber
            -- de antemano cual es cada una.
            -- REVOKE exige ser DUEÑO del objeto o superusuario. En una base
            -- gestionada —Render, y cualquier otra— el usuario que te dan no
            -- es superusuario, y las funciones de pg_catalog las posee el
            -- superusuario del motor: `pg_sleep`, `has_table_privilege`,
            -- `pg_read_file`... Ahi esto NO puede aplicarse.
            --
            -- Se captura ESE error y solo ese, y se CUENTA. Tragarlo en
            -- silencio dejaria un despliegue que parece completo y no lo esta;
            -- abortar impediria publicar la demo. Contarlo permite lo unico
            -- honesto: publicar declarando cuantas capas hay de verdad.
            --
            -- Cualquier otro error SIGUE PROPAGANDOSE. La tolerancia es a la
            -- falta de privilegio, no a que algo salga mal.
            -- La COINCIDENCIA se cuenta siempre, aunque la revocacion no se
            -- pueda aplicar: mide que el patron encontro la funcion, no que
            -- tuvieramos permiso. Contarla dentro del bloque protegido dejaba
            -- `n_coincide` en cero cuando faltaba privilegio, y el guardia de
            -- patrones huerfanos —el de mas abajo— concluia que la funcion NO
            -- EXISTE en el motor. Un control gritando la causa equivocada es
            -- peor que no tenerlo: manda a investigar al sitio que no es.
            n_coincide := n_coincide + 1;

            BEGIN
                EXECUTE format('REVOKE EXECUTE ON ROUTINE %s FROM PUBLIC', f.firma);

                INSERT INTO cartera.revocacion_aplicada (oid_funcion, firma, esquema, clase, patron)
                VALUES (f.oid, f.firma, f.esquema, p.clase, p.patron)
                ON CONFLICT (oid_funcion) DO NOTHING;

                total := total + 1;
            EXCEPTION WHEN insufficient_privilege THEN
                sin_privilegio := sin_privilegio + 1;
            END;
        END LOOP;

        IF n_coincide = 0 THEN
            IF p.clase = 'nombre' THEN
                huerfanos := array_append(huerfanos, p.patron);
                RAISE WARNING 'REVOCACION · nombre SIN COINCIDENCIAS: % (se acumula para fallar al final)', p.patron;
            ELSE
                RAISE NOTICE  'REVOCACION · prefijo sin coincidencias: %  (correcto: un prefijo cubre lo que aun no existe)', p.patron;
            END IF;
        ELSE
            RAISE NOTICE 'REVOCACION · % "%": % sobrecarga(s)', p.clase, p.patron, n_coincide;
        END IF;
    END LOOP;

    -- DOS NUMEROS DISTINTOS, Y CONFUNDIRLOS SERIA EL MISMO ERROR QUE ESTA
    -- SECCION VIENE A CORREGIR: un numero que dice una cosa y mide otra.
    --   operaciones = cuantos REVOKE se emitieron.
    --   distintas   = cuantas RUTINAS quedaron revocadas.
    -- No coinciden porque dos rutinas (inet_server_addr, inet_client_addr)
    -- estan cubiertas a la vez por un nombre exacto y por el prefijo
    -- `inet_*_addr`, asi que se revocan dos veces. La redundancia es
    -- deliberada —la lista de §6.5 y la de §7.5 se declararon por separado— y
    -- es inofensiva: revocar dos veces no revoca menos.
    SELECT count(*) INTO n_distintas FROM cartera.revocacion_aplicada;
    RAISE NOTICE 'REVOCACION · operaciones emitidas: %  ·  RUTINAS DISTINTAS revocadas: %',
                 total, n_distintas;

    -- La linea que el despliegue lee para saber que capa tiene de verdad.
    -- Se emite SIEMPRE, tambien cuando vale 0: un contador que solo aparece
    -- cuando hay problema entrena a no buscarlo.
    RAISE NOTICE 'REVOCACION · SIN PRIVILEGIO: %', sin_privilegio;
    IF sin_privilegio > 0 THEN
        RAISE WARNING 'REVOCACION · % rutinas NO se pudieron revocar: este motor no da superusuario. La capa 2 de este despliegue es MENOR que la que mide el repositorio.', sin_privilegio;
    END IF;

    IF array_length(huerfanos, 1) IS NOT NULL THEN
        RAISE EXCEPTION
            'Hay % nombre(s) de funcion en la politica que NO existen en este motor: %. '
            'Corrige el nombre y vuelve a ejecutar. NUNCA comentes la linea para que el arranque pase.',
            array_length(huerfanos, 1), array_to_string(huerfanos, ', ');
    END IF;
END
$revocar$;

-- ---------------------------------------------------------------------
-- La red por debajo de la lista: lo que se cree DESPUES
-- ---------------------------------------------------------------------
-- No sustituye a lo anterior: solo cubre funciones futuras creadas por este
-- mismo rol. No alcanza a las que ya existen ni a las que cree otro rol.
ALTER DEFAULT PRIVILEGES REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;

-- Lo que este archivo NO hace, y es deliberado:
--   No revoca EXECUTE sobre todas las funciones del motor. Romperia el
--   sistema y no hace falta: el guardian solo permite una lista blanca corta
--   (catalogo.yaml §7.5), asi que esta revocacion es la RED DEBAJO de esa
--   lista, no un sustituto de ella.

-- =====================================================================
-- huella.sql — invariancia de los datos sinteticos (D9)
-- Fuente normativa: F2-diseno/modelo-datos.md rev. 3, §5.2
--
-- "Si los datos cambian, la respuesta esperada de cada pregunta cambia y C1
-- deja de ser medible." Esta huella es lo que convierte esa frase en algo
-- comprobable: los conteos exactos y una suma de comprobacion contra un
-- valor versionado (datos/huella.json).
--
-- Es tambien la afirmacion de invariancia que usara la prueba de degradacion
-- T-2: con la capa 3 apagada, el conteo y la suma tienen que ser IDENTICOS
-- antes y despues. Si cambian, una carga destructiva llego a ejecutarse.
--
-- Las fechas se formatean explicitamente: `date::text` depende de DateStyle,
-- y una huella que cambia con la configuracion del cliente no sirve de nada.
-- =====================================================================

-- @huella conteos
SELECT 'propietarios' AS tabla, count(*) AS filas FROM cartera.propietarios
UNION ALL SELECT 'unidades', count(*) FROM cartera.unidades
UNION ALL SELECT 'cuotas',   count(*) FROM cartera.cuotas
UNION ALL SELECT 'pagos',    count(*) FROM cartera.pagos
ORDER BY 1;

-- @huella suma
SELECT md5(string_agg(linea, E'\n' ORDER BY linea)) AS suma_de_comprobacion
FROM (
    SELECT 'p:' || id || ';' || nombre || ';' || documento || ';' ||
           coalesce(email, '') || ';' || coalesce(telefono, '') || ';' ||
           to_char(fecha_alta, 'YYYY-MM-DD') AS linea
    FROM cartera.propietarios
    UNION ALL
    SELECT 'u:' || id || ';' || codigo || ';' || torre || ';' || tipo || ';' ||
           area_m2::text || ';' || coeficiente::text || ';' || propietario_id
    FROM cartera.unidades
    UNION ALL
    SELECT 'c:' || id || ';' || unidad_id || ';' || to_char(periodo, 'YYYY-MM-DD') || ';' ||
           concepto || ';' || valor::text || ';' ||
           to_char(fecha_emision, 'YYYY-MM-DD') || ';' ||
           to_char(fecha_vencimiento, 'YYYY-MM-DD')
    FROM cartera.cuotas
    UNION ALL
    SELECT 'g:' || id || ';' || cuota_id || ';' || to_char(fecha_pago, 'YYYY-MM-DD') || ';' ||
           valor::text || ';' || medio_pago || ';' || referencia
    FROM cartera.pagos
) AS t;

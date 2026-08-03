-- =====================================================================
-- 01-esquema.sql — dos esquemas, cuatro tablas base, cuatro vistas
-- Fuente normativa: F2-diseno/modelo-datos.md rev. 3, §6.1, §6.2, §6.3
--
-- REGLA QUE GOBIERNA ESTE ARCHIVO Y LOS TRES SIGUIENTES:
--   Si una linea falla, se corrige la linea. NUNCA se comenta para que el
--   arranque pase. Un arranque verde con una revocacion comentada es peor
--   que un arranque rojo: convierte un hueco visible en un hueco invisible.
--   El init corre con ON_ERROR_STOP=1 justamente para eso.
-- =====================================================================

-- Los dos esquemas separan lo que existe de lo que se publica.
-- `cartera` guarda el dato; `consulta` es lo unico que alcanza el rol
-- restringido. Esa separacion ES la capa 2 de contencion.
CREATE SCHEMA cartera;
CREATE SCHEMA consulta;

-- ---------------------------------------------------------------------
-- Tablas base
-- ---------------------------------------------------------------------

CREATE TABLE cartera.propietarios (
    id          integer PRIMARY KEY,
    nombre      text NOT NULL,
    documento   text NOT NULL UNIQUE,   -- sintetico. NO se publica en consulta.*
    email       text,                   -- sintetico. NO se publica
    telefono    text,                   -- sintetico. NO se publica
    fecha_alta  date NOT NULL
);

CREATE TABLE cartera.unidades (
    id             integer PRIMARY KEY,
    codigo         text    NOT NULL UNIQUE,
    torre          text    NOT NULL CHECK (torre IN ('A','B','C')),
    tipo           text    NOT NULL CHECK (tipo IN ('apartamento','local','parqueadero')),
    area_m2        numeric(7,2)  NOT NULL CHECK (area_m2 > 0),
    coeficiente    numeric(8,6)  NOT NULL CHECK (coeficiente > 0),
    -- RN-06: una unidad tiene exactamente un propietario responsable.
    propietario_id integer NOT NULL REFERENCES cartera.propietarios(id)
);

CREATE TABLE cartera.cuotas (
    id                integer PRIMARY KEY,
    unidad_id         integer NOT NULL REFERENCES cartera.unidades(id),
    periodo           date    NOT NULL,           -- primer dia del mes
    concepto          text    NOT NULL CHECK (concepto IN ('administracion','extraordinaria')),
    valor             numeric(12,2) NOT NULL CHECK (valor > 0),
    fecha_emision     date    NOT NULL,
    -- RN-02: el vencimiento se guarda en la fila, no se calcula. Asi una
    -- cuota extraordinaria puede vencer otro dia sin excepciones en el codigo.
    fecha_vencimiento date    NOT NULL,
    CONSTRAINT cuota_unica UNIQUE (unidad_id, periodo, concepto),
    CONSTRAINT vence_despues_de_emitir CHECK (fecha_vencimiento >= fecha_emision)
);

CREATE TABLE cartera.pagos (
    id          integer PRIMARY KEY,
    -- RN-05: un registro de pago se imputa a exactamente una cuota.
    cuota_id    integer NOT NULL REFERENCES cartera.cuotas(id),
    -- RN-03: una sola fecha, la de recepcion del dinero.
    fecha_pago  date    NOT NULL,
    valor       numeric(12,2) NOT NULL CHECK (valor > 0),
    medio_pago  text    NOT NULL CHECK (medio_pago IN ('transferencia','pse','efectivo','cheque')),
    -- RN-05: conserva el hecho de que varios abonos fueron un solo giro.
    referencia  text    NOT NULL
);

CREATE INDEX ON cartera.cuotas (unidad_id, periodo);
CREATE INDEX ON cartera.pagos  (cuota_id);
CREATE INDEX ON cartera.pagos  (fecha_pago);

-- ---------------------------------------------------------------------
-- RN-07 · Fecha de corte fija
-- ---------------------------------------------------------------------
-- Sin esto, "quien debe mas de tres meses" cambia de respuesta cada dia y
-- C1 deja de ser reproducible. El sistema nunca usa el reloj del motor.
CREATE FUNCTION consulta.fecha_corte() RETURNS date
    LANGUAGE sql IMMUTABLE
    AS $$ SELECT DATE '2026-07-05' $$;
-- Sin COMMENT ON: obj_description lee comentarios del catalogo y seria
-- informacion gratuita para quien enumera (modelo-datos.md §6.2).

-- ---------------------------------------------------------------------
-- Vistas publicadas — lo unico que el rol restringido alcanza
-- ---------------------------------------------------------------------

CREATE VIEW consulta.propietarios AS
SELECT p.id, p.nombre, p.fecha_alta
FROM   cartera.propietarios p;
-- documento, email y telefono NO se publican: no son alcanzables por valor.

CREATE VIEW consulta.unidades AS
SELECT u.id, u.codigo, u.torre, u.tipo, u.area_m2, u.coeficiente,
       u.propietario_id, p.nombre AS propietario_nombre
FROM   cartera.unidades u
JOIN   cartera.propietarios p ON p.id = u.propietario_id;

-- Aqui vive la regla de negocio: saldo, estado y dias_vencida se calculan en
-- SQL versionado, no en el texto que se envia al modelo. Es CD1 aplicado al
-- dominio: si estuvieran en el prompt, serian una sugerencia.
CREATE VIEW consulta.cuotas AS
SELECT c.id,
       c.unidad_id,
       u.codigo AS unidad_codigo,
       c.periodo,
       c.concepto,
       c.valor,
       c.fecha_emision,
       c.fecha_vencimiento,
       COALESCE(ab.pagado, 0)                     AS valor_pagado,
       c.valor - COALESCE(ab.pagado, 0)           AS saldo,               -- RN-05
       CASE
         WHEN c.valor - COALESCE(ab.pagado, 0) <= 0                     THEN 'pagada'
         WHEN c.fecha_vencimiento < consulta.fecha_corte()              THEN 'vencida'
         ELSE                                                                'corriente'
       END                                        AS estado,
       CASE
         WHEN c.valor - COALESCE(ab.pagado, 0) > 0
              AND c.fecha_vencimiento < consulta.fecha_corte()
         THEN (consulta.fecha_corte() - c.fecha_vencimiento)
         ELSE 0
       END                                        AS dias_vencida
FROM   cartera.cuotas c
JOIN   cartera.unidades u ON u.id = c.unidad_id
LEFT JOIN (
    SELECT cuota_id, SUM(valor) AS pagado
    FROM   cartera.pagos
    GROUP  BY cuota_id
) ab ON ab.cuota_id = c.id;

CREATE VIEW consulta.pagos AS
SELECT pa.id,
       pa.cuota_id,
       c.unidad_id,
       u.codigo   AS unidad_codigo,
       c.periodo  AS periodo_cuota,     -- RN-03: la otra lectura de "el mes del pago" (A-04)
       c.concepto AS concepto_cuota,
       pa.fecha_pago,                   -- RN-03: cuando entro el dinero
       pa.valor,
       pa.medio_pago,
       pa.referencia                    -- RN-05: agrupa el giro
FROM   cartera.pagos pa
JOIN   cartera.cuotas c   ON c.id = pa.cuota_id
JOIN   cartera.unidades u ON u.id = c.unidad_id;

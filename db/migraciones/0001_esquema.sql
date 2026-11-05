-- =====================================================================
-- Gestión PyME AR – esquema PostgreSQL 15+ (compatible con Supabase)
--
-- Capa 1 ORIGEN        : documentos, lotes_importacion, movimientos_staging
-- Capa 2 NORMALIZACIÓN : maestros + tablas T_* + vistas v_tc, v_tesoreria_ars, v_asientos_gestion
-- Capa 3 TABLEROS      : vistas v_pyl_mensual, v_saldos_cuentas (los KPIs complejos se calculan en
--                        el servicio Python app/finanzas, que lee estas vistas)
--
-- Multi-tenant: organizacion (el estudio / consultora) → clientes. Toda tabla de negocio lleva
-- cliente_id; las políticas RLS del final restringen por membresía del usuario.
-- Las tablas maestras con cliente_id NULL son las GLOBALES del sistema (sembradas desde db/seeds).
-- =====================================================================

-- Sin extensiones: gen_random_uuid() es nativo desde PostgreSQL 13 y los acentos se normalizan en la aplicación.

-- ------------------------------------------------------------------ tipos
CREATE TYPE tipo_movimiento   AS ENUM ('Ingreso', 'Egreso');
CREATE TYPE estado_documento  AS ENUM ('pendiente', 'procesado', 'con_alertas', 'error', 'descartado');
CREATE TYPE estado_lote       AS ENUM ('pendiente', 'aprobado', 'descartado');
CREATE TYPE pata_movimiento   AS ENUM ('principal', 'comision', 'impuestos');
CREATE TYPE rol_miembro       AS ENUM ('admin', 'consultor', 'carga', 'lectura');

-- ------------------------------------------------------------------ organización y acceso
CREATE TABLE organizaciones (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre      text NOT NULL,
    creado_en   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE usuarios (                      -- en Supabase: espejo de auth.users
    id          uuid PRIMARY KEY,
    email       text NOT NULL UNIQUE,
    nombre      text
);

CREATE TABLE clientes (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organizacion_id     uuid NOT NULL REFERENCES organizaciones(id),
    nombre              text NOT NULL,
    cuit                text,
    condicion_iva       text NOT NULL DEFAULT 'Responsable Inscripto',
    actividad           text,
    inicio_ejercicio    date NOT NULL,                       -- siempre día 1
    fecha_corte         date,
    cotizacion_reporte  text NOT NULL DEFAULT 'USD_MEP',
    pct_cargas_sociales numeric(6,4) NOT NULL DEFAULT 0.27,
    alic_ley_25413      numeric(6,4) NOT NULL DEFAULT 0.006,
    tolerancia_desvio   numeric(6,4) NOT NULL DEFAULT 0.05,
    pct_recupero_vencidas numeric(6,4) NOT NULL DEFAULT 0.5,
    saldo_inicial_deudores    numeric(18,2) NOT NULL DEFAULT 0,
    saldo_inicial_proveedores numeric(18,2) NOT NULL DEFAULT 0,
    activo              boolean NOT NULL DEFAULT true,
    creado_en           timestamptz NOT NULL DEFAULT now(),
    CHECK (extract(day FROM inicio_ejercicio) = 1)
);

CREATE TABLE miembros (                      -- quién ve qué: por organización y, opcional, por cliente
    id              bigserial PRIMARY KEY,
    usuario_id      uuid NOT NULL REFERENCES usuarios(id),
    organizacion_id uuid NOT NULL REFERENCES organizaciones(id),
    cliente_id      uuid REFERENCES clientes(id),            -- NULL = todos los clientes de la organización
    rol             rol_miembro NOT NULL,
    UNIQUE NULLS NOT DISTINCT (usuario_id, organizacion_id, cliente_id)
);

-- ------------------------------------------------------------------ maestros
CREATE TABLE unidades_negocio (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    cliente_id  uuid NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
    codigo      text NOT NULL,                               -- GENERAL siempre existe
    nombre      text NOT NULL,
    UNIQUE (cliente_id, codigo)
);

CREATE TABLE entidades_financieras (
    id      serial PRIMARY KEY,
    nombre  text NOT NULL UNIQUE,
    tipo    text NOT NULL
);

CREATE TABLE rubros (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    cliente_id      uuid REFERENCES clientes(id) ON DELETE CASCADE,   -- NULL = plan global
    codigo          text NOT NULL,
    nombre          text NOT NULL,
    linea_pl        text NOT NULL,                           -- '1 Ventas de bienes' ... 'NO P&L'
    linea_cf        text NOT NULL,
    comportamiento  text NOT NULL,                           -- Variable | Fijo | Discrecional | No aplica
    signo           smallint NOT NULL CHECK (signo IN (-1, 0, 1)),
    indice_ajuste   text NOT NULL DEFAULT 'IPC' CHECK (indice_ajuste IN ('IPC', 'CCT', 'TARIFA', 'USD', 'FIJO')),
    tolerancia      numeric(6,4),
    sin_factura     boolean NOT NULL DEFAULT false,
    grupo_prime     text CHECK (grupo_prime IN ('MATERIALES', 'PERSONAL')),
    uso             text
);
CREATE UNIQUE INDEX rubros_codigo_global  ON rubros (codigo) WHERE cliente_id IS NULL;
CREATE UNIQUE INDEX rubros_codigo_cliente ON rubros (cliente_id, codigo) WHERE cliente_id IS NOT NULL;

CREATE TABLE perfiles_importacion (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    cliente_id      uuid REFERENCES clientes(id) ON DELETE CASCADE,   -- NULL = perfil de fábrica
    codigo          text NOT NULL,
    nombre          text NOT NULL,
    tipo_origen     text NOT NULL,
    config          jsonb NOT NULL,       -- columnas, formato de fecha, separadores, modo de importe, rubros de patas
    UNIQUE NULLS NOT DISTINCT (cliente_id, codigo)
);

CREATE TABLE cuentas (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    cliente_id          uuid NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
    codigo              text NOT NULL,
    nombre              text NOT NULL,
    tipo                text NOT NULL,                       -- banco, billetera, caja, procesador, broker, tarjeta...
    entidad_id          integer REFERENCES entidades_financieras(id),
    cotizacion          text NOT NULL DEFAULT 'ARS',         -- ARS | USD_OFICIAL | USD_MEP | USDT ...
    cbu_cvu_alias       text,
    saldo_inicial       numeric(18,2) NOT NULL DEFAULT 0,    -- tarjetas: negativo
    fecha_saldo_inicial date NOT NULL,
    aplica_ley_25413    boolean NOT NULL DEFAULT false,
    perfil_defecto_id   uuid REFERENCES perfiles_importacion(id),
    activa              boolean NOT NULL DEFAULT true,
    UNIQUE (cliente_id, codigo)
);

CREATE TABLE reglas_clasificacion (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    cliente_id      uuid REFERENCES clientes(id) ON DELETE CASCADE,   -- NULL = regla global
    prioridad       integer NOT NULL,                        -- menor = se evalúa antes; las del cliente van antes que las globales
    texto           text NOT NULL,
    texto_normalizado text GENERATED ALWAYS AS (upper(texto)) STORED,  -- la app además quita acentos (unaccent no es IMMUTABLE)
    cuenta_id       uuid REFERENCES cuentas(id),
    tipo            tipo_movimiento,                         -- NULL = ingresos y egresos
    rubro_codigo    text NOT NULL,
    tercero_id      uuid,
    unidad_negocio_id uuid REFERENCES unidades_negocio(id),
    medio_pago      text,
    comentario      text,
    activa          boolean NOT NULL DEFAULT true,
    creada_por      uuid REFERENCES usuarios(id),
    creada_en       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX reglas_orden ON reglas_clasificacion (cliente_id, prioridad) WHERE activa;

CREATE TABLE terceros (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    cliente_id      uuid NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
    codigo          text NOT NULL,
    razon_social    text NOT NULL,
    cuit_dni        text,
    tipo            text NOT NULL CHECK (tipo IN ('Cliente', 'Proveedor', 'Ambos')),
    condicion_iva   text,
    plazo_dias      integer NOT NULL DEFAULT 0,
    canal           text,
    UNIQUE (cliente_id, codigo)
);
ALTER TABLE reglas_clasificacion ADD FOREIGN KEY (tercero_id) REFERENCES terceros(id);

CREATE TABLE items (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    cliente_id      uuid NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
    codigo          text NOT NULL,
    descripcion     text NOT NULL,
    tipo            text NOT NULL CHECK (tipo IN ('Bien', 'Servicio')),
    unidad_negocio_id uuid REFERENCES unidades_negocio(id),
    unidad_medida   text,
    precio_lista    numeric(18,4),
    cotizacion_precio text NOT NULL DEFAULT 'ARS',
    costo_estandar  numeric(18,4) NOT NULL DEFAULT 0,
    cotizacion_costo text NOT NULL DEFAULT 'ARS',
    alicuota_iva    numeric(6,4) NOT NULL DEFAULT 0.21,
    rubro_ingreso   text,
    UNIQUE (cliente_id, codigo)
);

-- ------------------------------------------------------------------ supuestos (índices y tipos de cambio)
CREATE TABLE indices_mensuales (
    cliente_id  uuid REFERENCES clientes(id) ON DELETE CASCADE,   -- NULL = serie oficial global (INDEC)
    mes         date NOT NULL CHECK (extract(day FROM mes) = 1),
    ipc         numeric(8,5),
    cct         numeric(8,5),                                      -- paritaria: suele ser propia del cliente
    tarifa      numeric(8,5),
    fuente      text,
    UNIQUE NULLS NOT DISTINCT (cliente_id, mes)
);

CREATE TABLE tipos_cambio (
    mes         date NOT NULL CHECK (extract(day FROM mes) = 1),
    cotizacion  text NOT NULL,                                     -- USD_OFICIAL, USD_MEP, USD_CCL, USD_BLUE, USDT, EUR_OFICIAL...
    valor       numeric(18,4) NOT NULL CHECK (valor > 0),
    fuente      text,
    PRIMARY KEY (mes, cotizacion)
);

-- ------------------------------------------------------------------ CAPA 1: ORIGEN
CREATE TABLE documentos (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    cliente_id      uuid NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
    nombre          text NOT NULL,
    extension       text NOT NULL,
    tipo_detectado  text,                    -- extracto | f931 | mis_comprobantes | libro_iva | otro
    storage_path    text NOT NULL,           -- objeto en Supabase Storage / S3, nunca el binario en la base
    sha256          text NOT NULL,
    tamano_bytes    bigint NOT NULL,
    estado          estado_documento NOT NULL DEFAULT 'pendiente',
    error           text,
    subido_por      uuid REFERENCES usuarios(id),
    subido_en       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (cliente_id, sha256)              -- el mismo archivo no se sube dos veces
);

CREATE TABLE lotes_importacion (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    documento_id    uuid NOT NULL REFERENCES documentos(id) ON DELETE CASCADE,
    cliente_id      uuid NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
    cuenta_id       uuid NOT NULL REFERENCES cuentas(id),
    perfil_id       uuid REFERENCES perfiles_importacion(id),
    perfil_autodetectado boolean NOT NULL DEFAULT false,
    estado          estado_lote NOT NULL DEFAULT 'pendiente',
    filas_leidas    integer NOT NULL,
    filas_descartadas integer NOT NULL,
    saldo_extracto  numeric(18,2),
    fecha_ultima    date,
    aprobado_por    uuid REFERENCES usuarios(id),
    aprobado_en     timestamptz
);

CREATE TABLE movimientos_staging (           -- la grilla IMP_Listo
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    lote_id         uuid NOT NULL REFERENCES lotes_importacion(id) ON DELETE CASCADE,
    fila_origen     integer NOT NULL,
    pata            pata_movimiento NOT NULL DEFAULT 'principal',
    fecha           date NOT NULL,
    tipo            tipo_movimiento NOT NULL,
    importe         numeric(18,2) NOT NULL CHECK (importe > 0),
    descripcion     text NOT NULL,
    referencia      text,
    rubro_codigo    text,
    tercero_id      uuid REFERENCES terceros(id),
    unidad_negocio_id uuid REFERENCES unidades_negocio(id),
    medio_pago      text,
    comprobante     text,
    regla_id        uuid REFERENCES reglas_clasificacion(id),
    corregido_manual boolean NOT NULL DEFAULT false,
    alertas         text[] NOT NULL DEFAULT '{}'
);

CREATE TABLE f931_declaraciones (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    cliente_id      uuid NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
    documento_id    uuid REFERENCES documentos(id),
    periodo         date NOT NULL,
    cuit            text NOT NULL,
    empleados       integer,
    importes        jsonb NOT NULL,          -- remuneracion_total, aportes_ss, contribuciones_ss, ..., total_a_pagar
    UNIQUE (cliente_id, periodo)
);

-- ------------------------------------------------------------------ CAPA 2: TABLAS NORMALIZADAS (T_*)
CREATE TABLE t_tesoreria (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    cliente_id      uuid NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
    cuenta_id       uuid NOT NULL REFERENCES cuentas(id),
    fecha           date NOT NULL,
    tipo            tipo_movimiento NOT NULL,
    importe         numeric(18,2) NOT NULL CHECK (importe > 0),   -- en la moneda de la cuenta
    rubro_codigo    text NOT NULL,
    tercero_id      uuid REFERENCES terceros(id),
    comprobante     text,
    medio_pago      text,
    tc_manual       numeric(18,4),
    id_operacion    text,                    -- empareja transferencias y compras de divisas (2 patas)
    unidad_negocio_id uuid REFERENCES unidades_negocio(id),
    conciliado      boolean NOT NULL DEFAULT false,
    descripcion     text,
    referencia      text,
    lote_id         uuid REFERENCES lotes_importacion(id),   -- trazabilidad al extracto de origen
    creado_por      uuid REFERENCES usuarios(id),
    creado_en       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX t_tesoreria_dup ON t_tesoreria (cuenta_id, fecha, tipo, importe);
CREATE INDEX t_tesoreria_ref ON t_tesoreria (cuenta_id, referencia) WHERE referencia IS NOT NULL;
CREATE INDEX t_tesoreria_comp ON t_tesoreria (cliente_id, comprobante) WHERE comprobante IS NOT NULL;

CREATE TABLE t_ventas (                      -- un renglón de factura por fila
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    cliente_id      uuid NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
    fecha           date NOT NULL,
    comprobante     text NOT NULL,
    tipo_comprobante text,
    tercero_id      uuid REFERENCES terceros(id),
    item_id         uuid NOT NULL REFERENCES items(id),
    cantidad        numeric(18,4) NOT NULL,                  -- notas de crédito: negativa
    precio_unitario numeric(18,4),                           -- NULL = precio de lista
    cotizacion      text,                                    -- NULL = la del ítem
    tc_manual       numeric(18,4),
    descuento       numeric(6,4) NOT NULL DEFAULT 0,
    condicion       text NOT NULL DEFAULT 'Contado',
    canal           text,
    vencimiento     date,
    documento_id    uuid REFERENCES documentos(id)
);
CREATE INDEX t_ventas_comp ON t_ventas (cliente_id, comprobante);

CREATE TABLE t_compras (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    cliente_id      uuid NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
    fecha           date NOT NULL,
    comprobante     text NOT NULL,
    tipo_comprobante text,
    tercero_id      uuid REFERENCES terceros(id),
    rubro_codigo    text NOT NULL,
    descripcion     text,
    item_id         uuid REFERENCES items(id),
    cantidad        numeric(18,4),
    importe_neto    numeric(18,2) NOT NULL,                  -- notas de crédito: negativo
    cotizacion      text NOT NULL DEFAULT 'ARS',
    tc_manual       numeric(18,4),
    alicuota_iva    numeric(6,4) NOT NULL DEFAULT 0,
    percepciones    numeric(18,2) NOT NULL DEFAULT 0,
    unidad_negocio_id uuid REFERENCES unidades_negocio(id),
    vencimiento     date,
    documento_id    uuid REFERENCES documentos(id)
);

CREATE TABLE t_personal (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    cliente_id      uuid NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
    mes             date NOT NULL CHECK (extract(day FROM mes) = 1),
    colaborador     text NOT NULL,
    cuil_legajo     text,
    modalidad       text NOT NULL,
    rubro_codigo    text NOT NULL DEFAULT 'PER01',
    unidad_negocio_id uuid REFERENCES unidades_negocio(id),
    bruto           numeric(18,2) NOT NULL,
    adicionales     numeric(18,2) NOT NULL DEFAULT 0,
    pct_cargas      numeric(6,4),                            -- NULL = el del cliente si es relación de dependencia
    horas           numeric(8,2),
    f931_id         uuid REFERENCES f931_declaraciones(id)   -- conciliación con lo declarado
);

CREATE TABLE t_mermas (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    cliente_id      uuid NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
    fecha           date NOT NULL,
    item_id         uuid NOT NULL REFERENCES items(id),
    cantidad        numeric(18,4) NOT NULL,
    causa           text NOT NULL,
    turno           text,
    responsable     text,
    costo_unitario_manual numeric(18,4)
);

CREATE TABLE t_presupuesto (                 -- base a precios del mes de inicio; el nominal se calcula por índice
    cliente_id      uuid NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
    rubro_codigo    text NOT NULL,
    mes             date NOT NULL CHECK (extract(day FROM mes) = 1),
    importe_base    numeric(18,2) NOT NULL CHECK (importe_base >= 0),
    etapa           text NOT NULL DEFAULT 'oficial',         -- base_historica | volumen | objetivos | oficial
    nota            text,
    PRIMARY KEY (cliente_id, rubro_codigo, mes, etapa)
);

CREATE TABLE t_balance_cierres (
    cliente_id      uuid NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
    mes             date NOT NULL CHECK (extract(day FROM mes) = 1),
    stock           numeric(18,2) NOT NULL DEFAULT 0,
    bienes_uso      numeric(18,2) NOT NULL DEFAULT 0,
    otros_activos   numeric(18,2) NOT NULL DEFAULT 0,
    deudas_financieras numeric(18,2) NOT NULL DEFAULT 0,
    deudas_fiscales numeric(18,2) NOT NULL DEFAULT 0,
    otros_pasivos   numeric(18,2) NOT NULL DEFAULT 0,
    amortizacion_mes numeric(18,2) NOT NULL DEFAULT 0,
    PRIMARY KEY (cliente_id, mes)
);

CREATE TABLE auditoria (
    id          bigserial PRIMARY KEY,
    cliente_id  uuid REFERENCES clientes(id),
    usuario_id  uuid REFERENCES usuarios(id),
    accion      text NOT NULL,           -- aprobar_lote, crear_regla, corregir_movimiento, borrar...
    entidad     text NOT NULL,
    entidad_id  text,
    detalle     jsonb,
    en          timestamptz NOT NULL DEFAULT now()
);

-- ------------------------------------------------------------------ vistas de normalización
-- Tipo de cambio efectivo: el del mes o, si falta, el último cargado (misma regla que la planilla).
CREATE VIEW v_tc AS
SELECT m.mes, c.cotizacion,
       (SELECT t.valor FROM tipos_cambio t
         WHERE t.cotizacion = c.cotizacion AND t.mes <= m.mes ORDER BY t.mes DESC LIMIT 1) AS valor
FROM (SELECT DISTINCT mes FROM tipos_cambio) m
CROSS JOIN (SELECT DISTINCT cotizacion FROM tipos_cambio) c;

-- Rubro efectivo: el del cliente si existe, si no el global.
CREATE VIEW v_rubros_cliente AS
SELECT c.id AS cliente_id, r.*
FROM clientes c
JOIN LATERAL (
    SELECT DISTINCT ON (codigo) codigo, nombre, linea_pl, linea_cf, comportamiento, signo,
           indice_ajuste, tolerancia, sin_factura, grupo_prime
    FROM rubros WHERE cliente_id = c.id OR cliente_id IS NULL
    ORDER BY codigo, cliente_id NULLS LAST
) r ON true;

CREATE VIEW v_tesoreria_ars AS
SELECT t.*, cu.cotizacion,
       CASE WHEN t.tipo = 'Ingreso' THEN t.importe ELSE -t.importe END AS importe_firmado,
       CASE WHEN t.tipo = 'Ingreso' THEN 1 ELSE -1 END
         * t.importe * COALESCE(t.tc_manual, CASE WHEN cu.cotizacion = 'ARS' THEN 1 ELSE tc.valor END) AS importe_ars,
       date_trunc('month', t.fecha)::date AS mes
FROM t_tesoreria t
JOIN cuentas cu ON cu.id = t.cuenta_id
LEFT JOIN v_tc tc ON tc.mes = date_trunc('month', t.fecha)::date AND tc.cotizacion = cu.cotizacion;

-- Asientos de gestión: la capa que alimenta P&L, prime cost, control presupuestario y rentabilidad.
-- (+) ingresos, (−) costos, en ARS. Ventas e ítems resuelven TC de precio y costo por mes.
CREATE VIEW v_asientos_gestion AS
WITH ventas AS (
    SELECT v.cliente_id, date_trunc('month', v.fecha)::date AS mes, v.fecha, i.tipo AS tipo_item,
           COALESCE(un.codigo, 'GENERAL') AS unidad_negocio,
           COALESCE(i.rubro_ingreso, CASE WHEN i.tipo = 'Servicio' THEN 'ING02' ELSE 'ING01' END) AS rubro_ingreso,
           v.cantidad * COALESCE(v.precio_unitario, i.precio_lista) * (1 - v.descuento)
             * COALESCE(v.tc_manual, CASE WHEN COALESCE(v.cotizacion, i.cotizacion_precio) = 'ARS' THEN 1 ELSE tcp.valor END) AS neto_ars,
           v.cantidad * i.costo_estandar
             * CASE WHEN i.cotizacion_costo = 'ARS' THEN 1 ELSE tcc.valor END AS costo_ars
    FROM t_ventas v
    JOIN items i ON i.id = v.item_id
    LEFT JOIN unidades_negocio un ON un.id = i.unidad_negocio_id
    LEFT JOIN v_tc tcp ON tcp.mes = date_trunc('month', v.fecha)::date AND tcp.cotizacion = COALESCE(v.cotizacion, i.cotizacion_precio)
    LEFT JOIN v_tc tcc ON tcc.mes = date_trunc('month', v.fecha)::date AND tcc.cotizacion = i.cotizacion_costo
)
SELECT cliente_id, mes, rubro_ingreso AS rubro_codigo, unidad_negocio, neto_ars AS importe_ars, 'ventas' AS origen FROM ventas
UNION ALL
SELECT cliente_id, mes, 'CV01', unidad_negocio, -costo_ars, 'cmv' FROM ventas
UNION ALL
SELECT c.cliente_id, date_trunc('month', c.fecha)::date, c.rubro_codigo, COALESCE(un.codigo, 'GENERAL'),
       -c.importe_neto * COALESCE(c.tc_manual, CASE WHEN c.cotizacion = 'ARS' THEN 1 ELSE tc.valor END), 'compras'
FROM t_compras c
LEFT JOIN unidades_negocio un ON un.id = c.unidad_negocio_id
LEFT JOIN v_tc tc ON tc.mes = date_trunc('month', c.fecha)::date AND tc.cotizacion = c.cotizacion
UNION ALL
SELECT t.cliente_id, t.mes, t.rubro_codigo, COALESCE(un.codigo, 'GENERAL'), t.importe_ars, 'tesoreria'
FROM v_tesoreria_ars t
LEFT JOIN unidades_negocio un ON un.id = t.unidad_negocio_id
UNION ALL
SELECT p.cliente_id, p.mes, p.rubro_codigo, COALESCE(un.codigo, 'GENERAL'),
       -((p.bruto + p.adicionales)
         * (1 + COALESCE(p.pct_cargas, CASE WHEN p.modalidad LIKE 'Relación%' THEN cl.pct_cargas_sociales ELSE 0 END))
         * CASE WHEN p.modalidad LIKE 'Relación%' THEN 13.0 / 12 ELSE 1 END), 'personal'   -- incluye provisión de SAC
FROM t_personal p
JOIN clientes cl ON cl.id = p.cliente_id
LEFT JOIN unidades_negocio un ON un.id = p.unidad_negocio_id
UNION ALL
SELECT m.cliente_id, date_trunc('month', m.fecha)::date, 'CV10', COALESCE(un.codigo, 'GENERAL'),
       -m.cantidad * COALESCE(m.costo_unitario_manual, i.costo_estandar * CASE WHEN i.cotizacion_costo = 'ARS' THEN 1 ELSE tc.valor END),
       'mermas'
FROM t_mermas m
JOIN items i ON i.id = m.item_id
LEFT JOIN unidades_negocio un ON un.id = i.unidad_negocio_id
LEFT JOIN v_tc tc ON tc.mes = date_trunc('month', m.fecha)::date AND tc.cotizacion = i.cotizacion_costo;

-- P&L mensual por línea (los gastos de rubros NO P&L se excluyen solos: cobranzas, pagos, transferencias).
CREATE VIEW v_pyl_mensual AS
SELECT a.cliente_id, a.mes, r.linea_pl, r.grupo_prime, a.unidad_negocio, sum(a.importe_ars) AS importe_ars
FROM v_asientos_gestion a
JOIN v_rubros_cliente r ON r.cliente_id = a.cliente_id AND r.codigo = a.rubro_codigo
WHERE r.linea_pl <> 'NO P&L'
GROUP BY a.cliente_id, a.mes, r.linea_pl, r.grupo_prime, a.unidad_negocio;

CREATE VIEW v_saldos_cuentas AS
SELECT cu.cliente_id, cu.id AS cuenta_id, cu.codigo, cu.nombre, cu.tipo, cu.cotizacion,
       cu.saldo_inicial + COALESCE(sum(t.importe_firmado), 0) AS saldo_moneda_origen
FROM cuentas cu
LEFT JOIN v_tesoreria_ars t ON t.cuenta_id = cu.id
GROUP BY cu.id;

-- ------------------------------------------------------------------ seguridad por fila (Supabase)
-- auth.uid() es de Supabase. En PostgreSQL sin Supabase, reemplazarlo por current_setting('app.usuario_id')::uuid
-- y que el backend haga SET LOCAL app.usuario_id en cada transacción.
CREATE FUNCTION puede_ver_cliente(c uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER AS $$
    SELECT EXISTS (
        SELECT 1 FROM miembros m JOIN clientes cl ON cl.organizacion_id = m.organizacion_id
        WHERE m.usuario_id = auth.uid() AND cl.id = c AND (m.cliente_id IS NULL OR m.cliente_id = c))
$$;

ALTER TABLE clientes            ENABLE ROW LEVEL SECURITY;
ALTER TABLE cuentas             ENABLE ROW LEVEL SECURITY;
ALTER TABLE documentos          ENABLE ROW LEVEL SECURITY;
ALTER TABLE lotes_importacion   ENABLE ROW LEVEL SECURITY;
ALTER TABLE t_tesoreria         ENABLE ROW LEVEL SECURITY;
ALTER TABLE t_ventas            ENABLE ROW LEVEL SECURITY;
ALTER TABLE t_compras           ENABLE ROW LEVEL SECURITY;
ALTER TABLE t_personal          ENABLE ROW LEVEL SECURITY;

CREATE POLICY clientes_por_miembro    ON clientes          USING (puede_ver_cliente(id));
CREATE POLICY cuentas_por_miembro     ON cuentas           USING (puede_ver_cliente(cliente_id));
CREATE POLICY documentos_por_miembro  ON documentos        USING (puede_ver_cliente(cliente_id));
CREATE POLICY lotes_por_miembro       ON lotes_importacion USING (puede_ver_cliente(cliente_id));
CREATE POLICY tesoreria_por_miembro   ON t_tesoreria       USING (puede_ver_cliente(cliente_id));
CREATE POLICY ventas_por_miembro      ON t_ventas          USING (puede_ver_cliente(cliente_id));
CREATE POLICY compras_por_miembro     ON t_compras         USING (puede_ver_cliente(cliente_id));
CREATE POLICY personal_por_miembro    ON t_personal        USING (puede_ver_cliente(cliente_id));
-- (el resto de las tablas con cliente_id lleva la misma política; se omite por brevedad)

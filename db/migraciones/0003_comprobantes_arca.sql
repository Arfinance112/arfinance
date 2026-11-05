-- Comprobantes importados de ARCA (Mis Comprobantes emitidos y recibidos), a nivel cabecera.
-- t_ventas / t_compras quedan para la carga con detalle por ítem (CMV con stock, rentabilidad por ítem).
CREATE TABLE comprobantes_arca (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    cliente_id      uuid NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
    documento_id    uuid REFERENCES documentos(id),
    sentido         text NOT NULL CHECK (sentido IN ('emitido', 'recibido')),
    fecha           date NOT NULL,
    tipo            text NOT NULL,
    comprobante     text NOT NULL,
    cuit            text NOT NULL DEFAULT '',
    contraparte     text NOT NULL DEFAULT '',
    moneda          text NOT NULL DEFAULT '$',
    tipo_cambio     numeric(18,6) NOT NULL DEFAULT 1,
    neto            numeric(18,2) NOT NULL,       -- en moneda del comprobante; notas de crédito en negativo
    iva             numeric(18,2) NOT NULL DEFAULT 0,
    total           numeric(18,2) NOT NULL,
    rubro_codigo    text,                         -- recibidos: obligatorio para entrar al resultado
    UNIQUE (cliente_id, sentido, tipo, comprobante, cuit)
);
CREATE INDEX comprobantes_arca_mes ON comprobantes_arca (cliente_id, fecha);
CREATE INDEX comprobantes_arca_sin_rubro ON comprobantes_arca (cliente_id) WHERE rubro_codigo IS NULL AND sentido = 'recibido';

-- Rubro recordado por proveedor: se asigna una vez y se aplica a todas sus facturas, actuales y futuras.
CREATE TABLE rubros_por_tercero (
    cliente_id      uuid NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
    cuit            text NOT NULL,
    rubro_codigo    text NOT NULL,
    PRIMARY KEY (cliente_id, cuit)
);

ALTER TABLE comprobantes_arca ENABLE ROW LEVEL SECURITY;
CREATE POLICY comprobantes_por_miembro ON comprobantes_arca USING (puede_ver_cliente(cliente_id));

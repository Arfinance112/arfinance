-- Paso 4: detalle de compras por ítem (exportación del sistema de compras / proveedor).
-- Sirve para stock teórico y costo real contra el estándar. NO entra al resultado: las compras ya entran
-- por Mis Comprobantes recibidos, y sumarlas acá las contaría dos veces.
CREATE TABLE IF NOT EXISTS compras_por_item (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    cliente_id      uuid NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
    fecha           date NOT NULL,
    comprobante     text NOT NULL DEFAULT '',
    proveedor       text NOT NULL DEFAULT '',
    item_codigo     text NOT NULL,
    cantidad        numeric(18,4) NOT NULL,                 -- notas de crédito: negativa
    costo_unitario  numeric(18,4) NOT NULL,                 -- neto sin IVA, ARS
    documento_id    uuid REFERENCES documentos(id) ON DELETE CASCADE,
    creado_en       timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS compras_por_item_sin_duplicados
    ON compras_por_item (cliente_id, fecha, comprobante, proveedor, item_codigo, cantidad, costo_unitario);
ALTER TABLE compras_por_item ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS lectura_propia ON compras_por_item;
CREATE POLICY lectura_propia ON compras_por_item FOR SELECT USING (puede_ver_cliente(cliente_id));
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON compras_por_item FROM anon;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON compras_por_item FROM authenticated;
    END IF;
END $$;

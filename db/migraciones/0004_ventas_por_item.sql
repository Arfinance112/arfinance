-- Detalle de ventas por ítem importado del punto de venta / facturador.
-- Se guarda el código tal como viene: si el ítem todavía no está en el maestro, la venta se conserva y el CMV
-- se calcula en cuanto se da de alta (la app avisa los códigos desconocidos).
ALTER TABLE t_ventas ALTER COLUMN item_id DROP NOT NULL;
ALTER TABLE t_ventas ADD COLUMN item_codigo text;
UPDATE t_ventas v SET item_codigo = i.codigo FROM items i WHERE i.id = v.item_id;
ALTER TABLE t_ventas ALTER COLUMN item_codigo SET NOT NULL;

-- reimportar el mismo detalle (otro archivo, mismas líneas) no duplica ventas
CREATE UNIQUE INDEX t_ventas_sin_duplicados
    ON t_ventas (cliente_id, fecha, comprobante, item_codigo, cantidad, precio_unitario);

ALTER TABLE t_mermas ADD COLUMN creado_en timestamptz NOT NULL DEFAULT now();
ALTER TABLE items ENABLE ROW LEVEL SECURITY;
ALTER TABLE t_mermas ENABLE ROW LEVEL SECURITY;
CREATE POLICY items_por_miembro ON items USING (puede_ver_cliente(cliente_id));
CREATE POLICY mermas_por_miembro ON t_mermas USING (puede_ver_cliente(cliente_id));

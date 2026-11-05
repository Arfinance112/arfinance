-- Metas del tablero por cliente: pisan las metas por defecto (las de la hoja Tablero de la planilla).
CREATE TABLE metas_tablero (
    cliente_id  uuid NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
    kpi         text NOT NULL,
    meta        numeric(18,4),                 -- NULL = sin meta para ese indicador
    direccion   text NOT NULL CHECK (direccion IN ('≥', '≤')),
    PRIMARY KEY (cliente_id, kpi)
);
ALTER TABLE metas_tablero ENABLE ROW LEVEL SECURITY;
CREATE POLICY metas_por_miembro ON metas_tablero USING (puede_ver_cliente(cliente_id));
ALTER TABLE t_balance_cierres ENABLE ROW LEVEL SECURITY;
CREATE POLICY cierres_por_miembro ON t_balance_cierres USING (puede_ver_cliente(cliente_id));

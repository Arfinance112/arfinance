-- Paso 5: clientes archivados (se recuperan durante 30 días) e inversiones (FCI, plazos fijos, cauciones, títulos).
ALTER TABLE clientes ADD COLUMN IF NOT EXISTS archivado_en timestamptz;

CREATE TABLE IF NOT EXISTS inversiones_movimientos (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    cliente_id  uuid NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
    fecha       date NOT NULL,
    instrumento text NOT NULL CHECK (instrumento IN ('FCI', 'Plazo fijo', 'Caución', 'Acciones', 'Bonos', 'Cedears', 'Otro')),
    nombre      text NOT NULL CHECK (char_length(nombre) BETWEEN 1 AND 80),
    tipo        text NOT NULL CHECK (tipo IN ('aporte', 'rescate', 'valuacion')),
    importe     numeric(18,2) NOT NULL CHECK (importe >= 0),
    moneda      text NOT NULL DEFAULT 'ARS' CHECK (moneda IN ('ARS', 'USD')),
    creado_en   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS inversiones_por_cliente ON inversiones_movimientos (cliente_id, fecha);
ALTER TABLE inversiones_movimientos ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS lectura_propia ON inversiones_movimientos;
CREATE POLICY lectura_propia ON inversiones_movimientos FOR SELECT USING (puede_ver_cliente(cliente_id));
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON inversiones_movimientos FROM anon;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON inversiones_movimientos FROM authenticated;
    END IF;
END $$;

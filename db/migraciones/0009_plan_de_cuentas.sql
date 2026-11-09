-- Plan de cuentas contable por cliente (se inicia con la plantilla db/seeds/plan_cuentas.json) y vínculo con los
-- rubros de gestión: cada rubro se imputa a una cuenta del plan (una sola por cliente).
CREATE TABLE plan_cuentas (
    cliente_id  uuid NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
    codigo      text NOT NULL CHECK (codigo ~ '^[0-9]{1,12}$'),
    nombre      text NOT NULL,
    imputable   boolean NOT NULL DEFAULT true,
    ajustable   boolean NOT NULL DEFAULT false,      -- ajustable por inflación
    expuesta    boolean NOT NULL DEFAULT false,      -- expuesta a la inflación (monetaria)
    clase       smallint NOT NULL CHECK (clase BETWEEN 1 AND 5),
    padre       text,                                -- cuenta agrupadora (NULL = raíz)
    comentario  text NOT NULL DEFAULT '',
    PRIMARY KEY (cliente_id, codigo),
    FOREIGN KEY (cliente_id, padre) REFERENCES plan_cuentas(cliente_id, codigo)
);
CREATE TABLE rubro_cuenta (
    cliente_id  uuid NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
    rubro       text NOT NULL,
    cuenta      text NOT NULL,
    PRIMARY KEY (cliente_id, rubro),
    FOREIGN KEY (cliente_id, cuenta) REFERENCES plan_cuentas(cliente_id, codigo) ON DELETE CASCADE
);
-- misma regla que 0008: RLS siempre, lectura solo de lo propio y ninguna escritura por la API REST
ALTER TABLE plan_cuentas ENABLE ROW LEVEL SECURITY;
ALTER TABLE rubro_cuenta ENABLE ROW LEVEL SECURITY;
CREATE POLICY lectura_propia ON plan_cuentas FOR SELECT USING (puede_ver_cliente(cliente_id));
CREATE POLICY lectura_propia ON rubro_cuenta FOR SELECT USING (puede_ver_cliente(cliente_id));
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON plan_cuentas, rubro_cuenta FROM anon;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON plan_cuentas, rubro_cuenta FROM authenticated;
    END IF;
END $$;

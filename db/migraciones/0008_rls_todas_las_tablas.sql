-- RLS en TODAS las tablas de public. En Supabase el esquema public se publica solo como API REST (PostgREST) y
-- la clave pública viaja en el navegador: una tabla sin RLS (por ejemplo f931_declaraciones, con sueldos) se
-- podría leer con esa clave. El backend se conecta como dueño de las tablas y no pasa por RLS: nada cambia para
-- la app. Por la API REST: lectura solo de lo propio y NINGUNA escritura (todo se escribe por el backend).

-- 1) RLS activo en todas las tablas que no lo tengan (también en las que se agreguen sin acordarse: ver verificador)
DO $$
DECLARE t record;
BEGIN
    FOR t IN SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'public' AND c.relkind = 'r' AND NOT c.relrowsecurity LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t.relname);
    END LOOP;
END $$;

-- 2) Lectura para usuarios con sesión: lo de sus clientes, y los maestros globales (cliente_id NULL)
CREATE POLICY lectura_propia ON auditoria            FOR SELECT USING (puede_ver_cliente(cliente_id));
CREATE POLICY lectura_propia ON f931_declaraciones   FOR SELECT USING (puede_ver_cliente(cliente_id));
CREATE POLICY lectura_propia ON rubros_por_tercero   FOR SELECT USING (puede_ver_cliente(cliente_id));
CREATE POLICY lectura_propia ON t_presupuesto        FOR SELECT USING (puede_ver_cliente(cliente_id));
CREATE POLICY lectura_propia ON terceros             FOR SELECT USING (puede_ver_cliente(cliente_id));
CREATE POLICY lectura_propia ON unidades_negocio     FOR SELECT USING (puede_ver_cliente(cliente_id));
CREATE POLICY lectura_propia ON indices_mensuales    FOR SELECT USING (cliente_id IS NULL OR puede_ver_cliente(cliente_id));
CREATE POLICY lectura_propia ON perfiles_importacion FOR SELECT USING (cliente_id IS NULL OR puede_ver_cliente(cliente_id));
CREATE POLICY lectura_propia ON reglas_clasificacion FOR SELECT USING (cliente_id IS NULL OR puede_ver_cliente(cliente_id));
CREATE POLICY lectura_propia ON rubros               FOR SELECT USING (cliente_id IS NULL OR puede_ver_cliente(cliente_id));
CREATE POLICY lectura_propia ON movimientos_staging  FOR SELECT USING (
    EXISTS (SELECT 1 FROM lotes_importacion l WHERE l.id = movimientos_staging.lote_id AND puede_ver_cliente(l.cliente_id)));
CREATE POLICY lectura_propia ON usuarios             FOR SELECT USING (id = auth.uid());
CREATE POLICY lectura_propia ON miembros             FOR SELECT USING (usuario_id = auth.uid());
CREATE POLICY lectura_propia ON organizaciones       FOR SELECT USING (
    EXISTS (SELECT 1 FROM miembros m WHERE m.organizacion_id = organizaciones.id AND m.usuario_id = auth.uid()));
CREATE POLICY lectura_global ON entidades_financieras FOR SELECT USING (auth.uid() IS NOT NULL);
CREATE POLICY lectura_global ON tipos_cambio          FOR SELECT USING (auth.uid() IS NOT NULL);
-- schema_migraciones: sin política = nadie por la API

-- 3) Solo en Supabase (existen los roles de la API): el rol anónimo no toca nada y el de sesión solo lee.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon;
        REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM anon;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM anon;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA public FROM authenticated;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON TABLES FROM authenticated;
    END IF;
END $$;

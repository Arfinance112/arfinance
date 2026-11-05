-- Bucket PRIVADO para los archivos originales que suben los clientes (extractos, F.931, comprobantes, planillas).
-- Solo existe en Supabase (esquema storage); en un PostgreSQL común esta migración no hace nada.
-- El backend lee y escribe con la service key; no se crean políticas para la clave anónima: nadie accede
-- a los archivos desde el navegador directamente.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'storage')
       AND EXISTS (SELECT 1 FROM pg_tables WHERE schemaname = 'storage' AND tablename = 'buckets') THEN
        INSERT INTO storage.buckets (id, name, public, file_size_limit)
        VALUES ('documentos', 'documentos', false, 20 * 1024 * 1024)
        ON CONFLICT (id) DO UPDATE SET public = false, file_size_limit = EXCLUDED.file_size_limit;
    END IF;
END $$;

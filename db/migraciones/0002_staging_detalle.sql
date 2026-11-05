-- La grilla de conciliación necesita conservar el orden del extracto, el texto de la regla aplicada
-- (las reglas globales viven en código y en esta tabla) y los códigos tal como los propone el motor,
-- antes de resolverlos a ids al aprobar.
ALTER TABLE movimientos_staging
    ADD COLUMN orden integer NOT NULL DEFAULT 0,
    ADD COLUMN regla_texto text,
    ADD COLUMN tercero_codigo text,
    ADD COLUMN unidad_negocio_codigo text;

CREATE INDEX movimientos_staging_lote ON movimientos_staging (lote_id, orden);
CREATE INDEX documentos_estado ON documentos (cliente_id, estado);

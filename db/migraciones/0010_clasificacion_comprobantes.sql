-- Paso 4: cada comprobante (emitido o recibido) se clasifica además por unidad de negocio y centro de costo,
-- para abrir el resultado de gestión por esas dimensiones. Códigos libres del cliente (texto corto).
ALTER TABLE comprobantes_arca ADD COLUMN IF NOT EXISTS unidad_negocio text CHECK (char_length(unidad_negocio) <= 40);
ALTER TABLE comprobantes_arca ADD COLUMN IF NOT EXISTS centro_costo   text CHECK (char_length(centro_costo) <= 40);

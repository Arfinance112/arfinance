-- Cola de trabajos en segundo plano (archivos grandes; en 4b, OCR). Los workers toman con FOR UPDATE SKIP LOCKED.
CREATE TABLE trabajos (
    id           uuid PRIMARY KEY,
    cliente_id   uuid NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
    tipo         text NOT NULL,
    parametros   jsonb NOT NULL DEFAULT '{}',
    estado       text NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente', 'procesando', 'hecho', 'error')),
    intentos     int NOT NULL DEFAULT 0,
    resultado    jsonb,
    error        text,
    tomado_por   text,
    creado       timestamptz NOT NULL DEFAULT now(),
    actualizado  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX trabajos_pendientes ON trabajos (creado) WHERE estado = 'pendiente';
ALTER TABLE trabajos ENABLE ROW LEVEL SECURITY;
CREATE POLICY trabajos_por_miembro ON trabajos USING (puede_ver_cliente(cliente_id));

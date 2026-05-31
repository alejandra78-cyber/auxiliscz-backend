-- CU32: cotizaciones multiples y seleccion de taller sin tabla nueva de candidatos.
-- Cambios seguros: solo agrega columnas nullable/default, no elimina datos.

ALTER TABLE asignaciones
  ADD COLUMN IF NOT EXISTS tipo_asignacion VARCHAR(30) DEFAULT 'candidata';

ALTER TABLE asignaciones
  ADD COLUMN IF NOT EXISTS es_definitiva BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE asignaciones
  ADD COLUMN IF NOT EXISTS fecha_confirmacion TIMESTAMP WITHOUT TIME ZONE NULL;

ALTER TABLE cotizaciones
  ADD COLUMN IF NOT EXISTS tiempo_estimado VARCHAR(120) NULL;

CREATE INDEX IF NOT EXISTS idx_asignaciones_solicitud_estado
  ON asignaciones(solicitud_id, estado);

CREATE INDEX IF NOT EXISTS idx_cotizaciones_solicitud_estado
  ON cotizaciones(solicitud_id, estado);

BEGIN;

-- CU15: trazabilidad explícita de evaluación taller sobre asignación
ALTER TABLE asignaciones
  ADD COLUMN IF NOT EXISTS fecha_asignacion TIMESTAMP WITHOUT TIME ZONE,
  ADD COLUMN IF NOT EXISTS motivo_rechazo TEXT;

UPDATE asignaciones
SET fecha_asignacion = COALESCE(fecha_asignacion, asignado_en)
WHERE fecha_asignacion IS NULL;

CREATE INDEX IF NOT EXISTS idx_asignaciones_estado_taller_fecha
  ON asignaciones(taller_id, estado, fecha_asignacion DESC);

COMMIT;


BEGIN;

-- CU14: soporte de trazabilidad de respuesta de taller sobre asignación
ALTER TABLE asignaciones
  ADD COLUMN IF NOT EXISTS fecha_respuesta_taller TIMESTAMP WITHOUT TIME ZONE;

CREATE INDEX IF NOT EXISTS idx_asignaciones_fecha_respuesta_taller
  ON asignaciones(fecha_respuesta_taller);

COMMIT;


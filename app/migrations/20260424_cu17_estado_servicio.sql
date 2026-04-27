BEGIN;

ALTER TABLE asignaciones
  ADD COLUMN IF NOT EXISTS fecha_aceptacion TIMESTAMP WITHOUT TIME ZONE,
  ADD COLUMN IF NOT EXISTS fecha_inicio_camino TIMESTAMP WITHOUT TIME ZONE,
  ADD COLUMN IF NOT EXISTS fecha_inicio_servicio TIMESTAMP WITHOUT TIME ZONE,
  ADD COLUMN IF NOT EXISTS fecha_finalizacion TIMESTAMP WITHOUT TIME ZONE,
  ADD COLUMN IF NOT EXISTS observacion_estado TEXT;

UPDATE asignaciones
SET fecha_aceptacion = COALESCE(fecha_aceptacion, fecha_respuesta_taller)
WHERE fecha_aceptacion IS NULL
  AND (estado ILIKE 'aceptada' OR estado ILIKE 'asignada');

CREATE INDEX IF NOT EXISTS idx_asignaciones_estado_fechas
  ON asignaciones(estado, fecha_asignacion, fecha_respuesta_taller);

COMMIT;


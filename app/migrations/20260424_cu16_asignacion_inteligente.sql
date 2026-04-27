BEGIN;

ALTER TABLE asignaciones
  ADD COLUMN IF NOT EXISTS origen_asignacion VARCHAR(30);

UPDATE asignaciones
SET origen_asignacion = CASE
  WHEN motivo_asignacion ILIKE '%autom%' OR motivo_asignacion ILIKE '%reasign%' THEN 'automatica'
  ELSE 'manual'
END
WHERE origen_asignacion IS NULL;

ALTER TABLE asignaciones
  ALTER COLUMN origen_asignacion SET DEFAULT 'manual';

CREATE INDEX IF NOT EXISTS idx_asignaciones_incidente_estado
  ON asignaciones(incidente_id, estado);

COMMIT;


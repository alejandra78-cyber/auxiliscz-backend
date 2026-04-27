BEGIN;

-- CU07: Gestionar disponibilidad operativa del taller (incremental, backward compatible)

ALTER TABLE talleres
  ADD COLUMN IF NOT EXISTS estado_operativo VARCHAR(30) NOT NULL DEFAULT 'disponible',
  ADD COLUMN IF NOT EXISTS capacidad_maxima INTEGER NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS radio_cobertura_km DOUBLE PRECISION NOT NULL DEFAULT 10,
  ADD COLUMN IF NOT EXISTS observaciones_operativas TEXT;

UPDATE talleres
SET
  estado_operativo = COALESCE(NULLIF(estado_operativo, ''), CASE WHEN disponible THEN 'disponible' ELSE 'ocupado' END),
  capacidad_maxima = COALESCE(capacidad_maxima, 1),
  radio_cobertura_km = COALESCE(radio_cobertura_km, 10)
WHERE estado_operativo IS NULL
   OR estado_operativo = ''
   OR capacidad_maxima IS NULL
   OR radio_cobertura_km IS NULL;

ALTER TABLE asignaciones
  ADD COLUMN IF NOT EXISTS distancia_km DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS puntaje DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS motivo_asignacion TEXT;

CREATE INDEX IF NOT EXISTS idx_talleres_estado_operativo ON talleres(estado_operativo);
CREATE INDEX IF NOT EXISTS idx_talleres_capacidad_maxima ON talleres(capacidad_maxima);
CREATE INDEX IF NOT EXISTS idx_talleres_radio_cobertura_km ON talleres(radio_cobertura_km);
CREATE INDEX IF NOT EXISTS idx_asignaciones_taller_estado ON asignaciones(taller_id, estado);

COMMIT;


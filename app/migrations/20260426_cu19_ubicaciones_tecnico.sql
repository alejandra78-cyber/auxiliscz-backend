BEGIN;

ALTER TABLE IF EXISTS ubicaciones
  ADD COLUMN IF NOT EXISTS tecnico_id UUID NULL;

ALTER TABLE IF EXISTS ubicaciones
  ADD COLUMN IF NOT EXISTS asignacion_id UUID NULL;

ALTER TABLE IF EXISTS ubicaciones
  ADD COLUMN IF NOT EXISTS incidente_id UUID NULL;

ALTER TABLE IF EXISTS ubicaciones
  ADD COLUMN IF NOT EXISTS tipo VARCHAR(30) NULL;

CREATE INDEX IF NOT EXISTS idx_ubicaciones_incidente_creado
  ON ubicaciones (incidente_id, registrado_en DESC);

CREATE INDEX IF NOT EXISTS idx_ubicaciones_tecnico_creado
  ON ubicaciones (tecnico_id, registrado_en DESC);

CREATE INDEX IF NOT EXISTS idx_ubicaciones_asignacion_creado
  ON ubicaciones (asignacion_id, registrado_en DESC);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'fk_ubicaciones_tecnico_id'
  ) THEN
    ALTER TABLE ubicaciones
      ADD CONSTRAINT fk_ubicaciones_tecnico_id
      FOREIGN KEY (tecnico_id) REFERENCES tecnicos(id) NOT VALID;
  END IF;
END$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'fk_ubicaciones_asignacion_id'
  ) THEN
    ALTER TABLE ubicaciones
      ADD CONSTRAINT fk_ubicaciones_asignacion_id
      FOREIGN KEY (asignacion_id) REFERENCES asignaciones(id) NOT VALID;
  END IF;
END$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'fk_ubicaciones_incidente_id'
  ) THEN
    ALTER TABLE ubicaciones
      ADD CONSTRAINT fk_ubicaciones_incidente_id
      FOREIGN KEY (incidente_id) REFERENCES incidentes(id) NOT VALID;
  END IF;
END$$;

COMMIT;


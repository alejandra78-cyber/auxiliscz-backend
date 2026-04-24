BEGIN;

ALTER TABLE tecnicos
  ADD COLUMN IF NOT EXISTS email VARCHAR(150),
  ADD COLUMN IF NOT EXISTS telefono VARCHAR(20),
  ADD COLUMN IF NOT EXISTS especialidad VARCHAR(120),
  ADD COLUMN IF NOT EXISTS estado_operativo VARCHAR(30),
  ADD COLUMN IF NOT EXISTS activo BOOLEAN,
  ADD COLUMN IF NOT EXISTS latitud_actual DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS longitud_actual DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS ultima_actualizacion_ubicacion TIMESTAMP WITHOUT TIME ZONE,
  ADD COLUMN IF NOT EXISTS creado_en TIMESTAMP WITHOUT TIME ZONE,
  ADD COLUMN IF NOT EXISTS actualizado_en TIMESTAMP WITHOUT TIME ZONE;

UPDATE tecnicos
SET
  estado_operativo = COALESCE(estado_operativo, CASE WHEN disponible THEN 'disponible' ELSE 'ocupado' END),
  activo = COALESCE(activo, TRUE),
  email = COALESCE(email, (
    SELECT u.email FROM usuarios u WHERE u.id = tecnicos.usuario_id
  )),
  telefono = COALESCE(telefono, (
    SELECT u.telefono FROM usuarios u WHERE u.id = tecnicos.usuario_id
  )),
  latitud_actual = COALESCE(latitud_actual, lat_actual),
  longitud_actual = COALESCE(longitud_actual, lng_actual),
  creado_en = COALESCE(creado_en, NOW()),
  actualizado_en = COALESCE(actualizado_en, NOW())
WHERE
  estado_operativo IS NULL
  OR activo IS NULL
  OR email IS NULL
  OR telefono IS NULL
  OR latitud_actual IS NULL
  OR longitud_actual IS NULL
  OR creado_en IS NULL
  OR actualizado_en IS NULL;

ALTER TABLE tecnicos
  ALTER COLUMN estado_operativo SET DEFAULT 'disponible';

ALTER TABLE tecnicos
  ALTER COLUMN activo SET DEFAULT TRUE;

ALTER TABLE tecnicos
  ALTER COLUMN creado_en SET DEFAULT NOW();

ALTER TABLE tecnicos
  ALTER COLUMN actualizado_en SET DEFAULT NOW();

CREATE INDEX IF NOT EXISTS idx_tecnicos_taller_activo_estado
  ON tecnicos(taller_id, activo, estado_operativo, disponible);

CREATE INDEX IF NOT EXISTS idx_tecnicos_usuario_id
  ON tecnicos(usuario_id);

COMMIT;


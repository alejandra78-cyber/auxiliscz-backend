BEGIN;

CREATE TABLE IF NOT EXISTS solicitudes_taller (
  id UUID PRIMARY KEY,
  nombre_taller VARCHAR(120) NOT NULL,
  responsable_nombre VARCHAR(120) NOT NULL,
  responsable_email VARCHAR(150) NOT NULL,
  responsable_telefono VARCHAR(30) NOT NULL,
  direccion VARCHAR(255),
  latitud DOUBLE PRECISION,
  longitud DOUBLE PRECISION,
  servicios TEXT,
  descripcion TEXT,
  estado VARCHAR(20) NOT NULL DEFAULT 'pendiente',
  observaciones TEXT,
  creado_en TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
  revisado_en TIMESTAMP WITHOUT TIME ZONE,
  revisado_por UUID NULL,
  usuario_id UUID NULL,
  taller_id UUID NULL
);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname='fk_solicitudes_taller_revisado_por'
  ) THEN
    ALTER TABLE solicitudes_taller
      ADD CONSTRAINT fk_solicitudes_taller_revisado_por
      FOREIGN KEY (revisado_por) REFERENCES usuarios(id) NOT VALID;
  END IF;
END$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname='fk_solicitudes_taller_usuario_id'
  ) THEN
    ALTER TABLE solicitudes_taller
      ADD CONSTRAINT fk_solicitudes_taller_usuario_id
      FOREIGN KEY (usuario_id) REFERENCES usuarios(id) NOT VALID;
  END IF;
END$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname='fk_solicitudes_taller_taller_id'
  ) THEN
    ALTER TABLE solicitudes_taller
      ADD CONSTRAINT fk_solicitudes_taller_taller_id
      FOREIGN KEY (taller_id) REFERENCES talleres(id) NOT VALID;
  END IF;
END$$;

CREATE INDEX IF NOT EXISTS ix_solicitudes_taller_estado_creado_en
  ON solicitudes_taller(estado, creado_en DESC);

CREATE INDEX IF NOT EXISTS ix_solicitudes_taller_email
  ON solicitudes_taller(lower(responsable_email));

COMMIT;

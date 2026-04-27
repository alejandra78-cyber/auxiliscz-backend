BEGIN;

ALTER TABLE talleres
  ADD COLUMN IF NOT EXISTS estado_aprobacion VARCHAR(20) NOT NULL DEFAULT 'pendiente';

ALTER TABLE talleres
  ADD COLUMN IF NOT EXISTS aprobado_por UUID;

ALTER TABLE talleres
  ADD COLUMN IF NOT EXISTS aprobado_en TIMESTAMP WITHOUT TIME ZONE;

ALTER TABLE talleres
  ADD COLUMN IF NOT EXISTS creado_en TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW();

ALTER TABLE talleres
  ADD COLUMN IF NOT EXISTS actualizado_en TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW();

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'fk_talleres_aprobado_por'
  ) THEN
    ALTER TABLE talleres
      ADD CONSTRAINT fk_talleres_aprobado_por
      FOREIGN KEY (aprobado_por) REFERENCES usuarios(id) NOT VALID;
  END IF;
END$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE c.relkind = 'i'
      AND c.relname = 'ux_talleres_usuario_id'
      AND n.nspname = 'public'
  ) AND NOT EXISTS (
    SELECT usuario_id
    FROM talleres
    WHERE usuario_id IS NOT NULL
    GROUP BY usuario_id
    HAVING COUNT(*) > 1
  ) THEN
    CREATE UNIQUE INDEX ux_talleres_usuario_id ON talleres(usuario_id);
  END IF;
END$$;

COMMIT;

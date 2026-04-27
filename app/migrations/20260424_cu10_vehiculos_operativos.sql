BEGIN;

ALTER TABLE vehiculos
  ADD COLUMN IF NOT EXISTS cliente_id uuid;

ALTER TABLE vehiculos
  ADD COLUMN IF NOT EXISTS tipo varchar(40);

ALTER TABLE vehiculos
  ADD COLUMN IF NOT EXISTS observacion text;

ALTER TABLE vehiculos
  ADD COLUMN IF NOT EXISTS activo boolean DEFAULT true;

ALTER TABLE vehiculos
  ADD COLUMN IF NOT EXISTS creado_en timestamp without time zone DEFAULT now();

ALTER TABLE vehiculos
  ADD COLUMN IF NOT EXISTS actualizado_en timestamp without time zone DEFAULT now();

UPDATE vehiculos v
SET cliente_id = c.id
FROM clientes c
WHERE c.usuario_id = v.usuario_id
  AND v.cliente_id IS NULL;

UPDATE vehiculos
SET activo = COALESCE(activo, true),
    creado_en = COALESCE(creado_en, now()),
    actualizado_en = COALESCE(actualizado_en, now());

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'fk_vehiculos_cliente_id'
  ) THEN
    ALTER TABLE vehiculos
      ADD CONSTRAINT fk_vehiculos_cliente_id
      FOREIGN KEY (cliente_id) REFERENCES clientes(id);
  END IF;
END$$;

CREATE INDEX IF NOT EXISTS ix_vehiculos_usuario_id ON vehiculos(usuario_id);
CREATE INDEX IF NOT EXISTS ix_vehiculos_cliente_id ON vehiculos(cliente_id);
CREATE INDEX IF NOT EXISTS ix_vehiculos_activo ON vehiculos(activo);

COMMIT;

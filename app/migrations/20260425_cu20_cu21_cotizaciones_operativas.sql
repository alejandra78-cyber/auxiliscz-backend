BEGIN;

ALTER TABLE cotizaciones ADD COLUMN IF NOT EXISTS asignacion_id uuid;
ALTER TABLE cotizaciones ADD COLUMN IF NOT EXISTS taller_id uuid;
ALTER TABLE cotizaciones ADD COLUMN IF NOT EXISTS cliente_id uuid;
ALTER TABLE cotizaciones ADD COLUMN IF NOT EXISTS observaciones text;
ALTER TABLE cotizaciones ADD COLUMN IF NOT EXISTS fecha_emision timestamp without time zone;
ALTER TABLE cotizaciones ADD COLUMN IF NOT EXISTS validez_hasta timestamp without time zone;
ALTER TABLE cotizaciones ADD COLUMN IF NOT EXISTS fecha_respuesta_cliente timestamp without time zone;
ALTER TABLE cotizaciones ADD COLUMN IF NOT EXISTS actualizado_en timestamp without time zone;

UPDATE cotizaciones
SET fecha_emision = COALESCE(fecha_emision, creado_en, NOW())
WHERE fecha_emision IS NULL;

UPDATE cotizaciones
SET actualizado_en = COALESCE(actualizado_en, creado_en, NOW())
WHERE actualizado_en IS NULL;

UPDATE cotizaciones c
SET cliente_id = s.cliente_id
FROM solicitudes s
WHERE c.solicitud_id = s.id
  AND c.cliente_id IS NULL;

UPDATE cotizaciones c
SET taller_id = a.taller_id,
    asignacion_id = a.id
FROM (
  SELECT DISTINCT ON (solicitud_id) id, solicitud_id, taller_id
  FROM asignaciones
  ORDER BY solicitud_id, COALESCE(fecha_asignacion, asignado_en) DESC NULLS LAST, id DESC
) a
WHERE c.solicitud_id = a.solicitud_id
  AND (c.taller_id IS NULL OR c.asignacion_id IS NULL);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'fk_cotizaciones_asignacion_id'
  ) THEN
    ALTER TABLE cotizaciones
      ADD CONSTRAINT fk_cotizaciones_asignacion_id
      FOREIGN KEY (asignacion_id) REFERENCES asignaciones(id) NOT VALID;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'fk_cotizaciones_taller_id'
  ) THEN
    ALTER TABLE cotizaciones
      ADD CONSTRAINT fk_cotizaciones_taller_id
      FOREIGN KEY (taller_id) REFERENCES talleres(id) NOT VALID;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'fk_cotizaciones_cliente_id'
  ) THEN
    ALTER TABLE cotizaciones
      ADD CONSTRAINT fk_cotizaciones_cliente_id
      FOREIGN KEY (cliente_id) REFERENCES clientes(id) NOT VALID;
  END IF;
END$$;

CREATE INDEX IF NOT EXISTS ix_cotizaciones_solicitud_estado ON cotizaciones(solicitud_id, estado);
CREATE INDEX IF NOT EXISTS ix_cotizaciones_incidente_estado ON cotizaciones(incidente_id, estado);
CREATE INDEX IF NOT EXISTS ix_cotizaciones_cliente_id ON cotizaciones(cliente_id);
CREATE INDEX IF NOT EXISTS ix_cotizaciones_taller_id ON cotizaciones(taller_id);

COMMIT;


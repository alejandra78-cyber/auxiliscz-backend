BEGIN;

ALTER TABLE incidentes ADD COLUMN IF NOT EXISTS latitud DOUBLE PRECISION;
ALTER TABLE incidentes ADD COLUMN IF NOT EXISTS longitud DOUBLE PRECISION;
ALTER TABLE incidentes ADD COLUMN IF NOT EXISTS direccion_referencia VARCHAR(255);
ALTER TABLE incidentes ADD COLUMN IF NOT EXISTS resumen_ia TEXT;
ALTER TABLE incidentes ADD COLUMN IF NOT EXISTS confianza_ia DOUBLE PRECISION;
ALTER TABLE incidentes ADD COLUMN IF NOT EXISTS transcripcion_audio TEXT;
ALTER TABLE incidentes ADD COLUMN IF NOT EXISTS analisis_imagen TEXT;
ALTER TABLE incidentes ADD COLUMN IF NOT EXISTS ia_estado VARCHAR(30) DEFAULT 'pendiente';

ALTER TABLE evidencias ADD COLUMN IF NOT EXISTS incidente_id UUID;
ALTER TABLE evidencias ADD COLUMN IF NOT EXISTS contenido_texto TEXT;
ALTER TABLE evidencias ADD COLUMN IF NOT EXISTS metadata_json TEXT;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'fk_evidencias_incidente_id'
  ) THEN
    ALTER TABLE evidencias
      ADD CONSTRAINT fk_evidencias_incidente_id
      FOREIGN KEY (incidente_id) REFERENCES incidentes(id) NOT VALID;
  END IF;
END$$;

CREATE INDEX IF NOT EXISTS ix_incidentes_estado_prioridad ON incidentes(estado, prioridad);
CREATE INDEX IF NOT EXISTS ix_incidentes_ia_estado ON incidentes(ia_estado);
CREATE INDEX IF NOT EXISTS ix_evidencias_incidente_id ON evidencias(incidente_id);

COMMIT;

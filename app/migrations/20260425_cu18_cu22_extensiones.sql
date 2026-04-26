BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS trabajos_completados (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  solicitud_id UUID NOT NULL REFERENCES solicitudes(id),
  incidente_id UUID NULL REFERENCES incidentes(id),
  asignacion_id UUID NULL REFERENCES asignaciones(id),
  taller_id UUID NULL REFERENCES talleres(id),
  tecnico_id UUID NULL REFERENCES tecnicos(id),
  descripcion TEXT NOT NULL,
  observaciones TEXT NULL,
  evidencia_url VARCHAR(500) NULL,
  registrado_por_usuario_id UUID NULL REFERENCES usuarios(id),
  creado_en TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_trabajos_solicitud_id ON trabajos_completados(solicitud_id);
CREATE INDEX IF NOT EXISTS ix_trabajos_incidente_id ON trabajos_completados(incidente_id);
CREATE INDEX IF NOT EXISTS ix_trabajos_asignacion_id ON trabajos_completados(asignacion_id);
CREATE INDEX IF NOT EXISTS ix_trabajos_taller_id ON trabajos_completados(taller_id);
CREATE INDEX IF NOT EXISTS ix_trabajos_tecnico_id ON trabajos_completados(tecnico_id);

ALTER TABLE pagos ADD COLUMN IF NOT EXISTS incidente_id UUID NULL REFERENCES incidentes(id);
ALTER TABLE pagos ADD COLUMN IF NOT EXISTS cliente_id UUID NULL REFERENCES clientes(id);
ALTER TABLE pagos ADD COLUMN IF NOT EXISTS taller_id UUID NULL REFERENCES talleres(id);
ALTER TABLE pagos ADD COLUMN IF NOT EXISTS comprobante_url VARCHAR(500) NULL;
ALTER TABLE pagos ADD COLUMN IF NOT EXISTS referencia VARCHAR(120) NULL;
ALTER TABLE pagos ADD COLUMN IF NOT EXISTS monto_taller DOUBLE PRECISION NULL;
ALTER TABLE pagos ADD COLUMN IF NOT EXISTS fecha_verificacion TIMESTAMP WITHOUT TIME ZONE NULL;
ALTER TABLE pagos ADD COLUMN IF NOT EXISTS verificado_por UUID NULL REFERENCES usuarios(id);

CREATE INDEX IF NOT EXISTS ix_pagos_incidente_id ON pagos(incidente_id);
CREATE INDEX IF NOT EXISTS ix_pagos_cliente_id ON pagos(cliente_id);
CREATE INDEX IF NOT EXISTS ix_pagos_taller_id ON pagos(taller_id);

UPDATE pagos p
SET incidente_id = c.incidente_id,
    cliente_id = c.cliente_id,
    taller_id = c.taller_id,
    monto_taller = COALESCE(p.monto - COALESCE(p.comision_plataforma, 0), p.monto)
FROM cotizaciones c
WHERE c.pago_id = p.id
  AND (p.incidente_id IS NULL OR p.cliente_id IS NULL OR p.taller_id IS NULL OR p.monto_taller IS NULL);

COMMIT;

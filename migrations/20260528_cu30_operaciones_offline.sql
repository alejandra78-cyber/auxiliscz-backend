-- CU30 Registrar y sincronizar operaciones sin conexión
-- Migración segura: tenant_id es NULLABLE porque el cliente reporta emergencias
-- antes de que exista taller/tenant asignado.

ALTER TABLE solicitudes
ADD COLUMN IF NOT EXISTS offline_sync_id VARCHAR(120);

CREATE UNIQUE INDEX IF NOT EXISTS ux_solicitudes_offline_sync_id
ON solicitudes(offline_sync_id)
WHERE offline_sync_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS operaciones_offline (
    id UUID PRIMARY KEY,
    offline_sync_id VARCHAR(120) UNIQUE NOT NULL,
    usuario_id UUID NOT NULL REFERENCES usuarios(id),
    tenant_id UUID NULL REFERENCES tenants(id),
    tipo_operacion VARCHAR(80) NOT NULL,
    estado_sync VARCHAR(40) NOT NULL DEFAULT 'pendiente_sincronizacion',
    payload TEXT,
    resultado TEXT,
    error TEXT,
    fecha_local TIMESTAMP WITHOUT TIME ZONE,
    creado_en TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    sincronizado_en TIMESTAMP WITHOUT TIME ZONE
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_operaciones_offline_sync_id
ON operaciones_offline(offline_sync_id);

CREATE INDEX IF NOT EXISTS idx_operaciones_offline_usuario_estado
ON operaciones_offline(usuario_id, estado_sync);

CREATE INDEX IF NOT EXISTS idx_operaciones_offline_tenant_estado
ON operaciones_offline(tenant_id, estado_sync);

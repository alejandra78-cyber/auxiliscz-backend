-- CU29 Gestionar tenants
-- Migracion incremental y no destructiva para preparar arquitectura SaaS multi-tenant.

CREATE TABLE IF NOT EXISTS tenants (
    id UUID PRIMARY KEY,
    codigo VARCHAR(80) UNIQUE NOT NULL,
    nombre VARCHAR(150) NOT NULL,
    descripcion TEXT,
    estado VARCHAR(30) NOT NULL DEFAULT 'activo',
    contacto_email VARCHAR(150),
    contacto_telefono VARCHAR(30),
    creado_en TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    actualizado_en TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

INSERT INTO tenants (id, codigo, nombre, descripcion, estado, creado_en, actualizado_en)
VALUES (
    '00000000-0000-4000-8000-000000000001',
    'auxiliscz',
    'AuxilioSCZ',
    'Tenant por defecto para datos existentes',
    'activo',
    NOW(),
    NOW()
)
ON CONFLICT (codigo) DO NOTHING;

DO $$
DECLARE
    table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'usuarios',
        'clientes',
        'solicitudes_taller',
        'talleres',
        'tecnicos',
        'vehiculos',
        'incidentes',
        'solicitudes',
        'emergencias',
        'ubicaciones',
        'asignaciones',
        'evaluaciones',
        'trabajos_completados',
        'pagos',
        'cotizaciones',
        'historial',
        'evidencias',
        'notificaciones',
        'mensajes',
        'metricas',
        'auditorias'
    ]
    LOOP
        IF to_regclass(table_name) IS NOT NULL THEN
            EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS tenant_id UUID', table_name);
            EXECUTE format(
                'UPDATE %I SET tenant_id = %L WHERE tenant_id IS NULL',
                table_name,
                '00000000-0000-4000-8000-000000000001'
            );
            EXECUTE format(
                'CREATE INDEX IF NOT EXISTS idx_%s_tenant_id ON %I(tenant_id)',
                table_name,
                table_name
            );
        END IF;
    END LOOP;
END $$;

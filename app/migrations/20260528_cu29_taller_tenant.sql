-- CU29 Taller como tenant
-- Migracion incremental no destructiva.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

ALTER TABLE tenants ADD COLUMN IF NOT EXISTS taller_id UUID NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_tenants_taller_id ON tenants(taller_id) WHERE taller_id IS NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_tenants_taller_id'
    ) THEN
        ALTER TABLE tenants
        ADD CONSTRAINT fk_tenants_taller_id
        FOREIGN KEY (taller_id) REFERENCES talleres(id) NOT VALID;
    END IF;
END $$;

-- Los clientes son externos al tenant.
UPDATE clientes SET tenant_id = NULL;
UPDATE usuarios SET tenant_id = NULL WHERE id IN (SELECT usuario_id FROM clientes);
UPDATE vehiculos SET tenant_id = NULL;

-- Asociar tenants existentes a su unico taller cuando sea posible.
WITH unico_taller AS (
    SELECT tenant_id, MIN(id) AS taller_id, COUNT(*) AS total
    FROM talleres
    WHERE tenant_id IS NOT NULL
    GROUP BY tenant_id
)
UPDATE tenants t
SET taller_id = u.taller_id
FROM unico_taller u
WHERE t.id = u.tenant_id
  AND u.total = 1
  AND t.taller_id IS NULL;

-- Crear tenants para talleres aprobados que aun no tengan tenant.
DO $$
DECLARE
    r RECORD;
    base_codigo TEXT;
    codigo_final TEXT;
    idx INTEGER;
    nuevo_tenant UUID;
BEGIN
    FOR r IN
        SELECT ta.id, ta.nombre, ta.usuario_id, u.email, u.telefono
        FROM talleres ta
        LEFT JOIN usuarios u ON u.id = ta.usuario_id
        WHERE ta.estado_aprobacion = 'aprobado'
          AND ta.tenant_id IS NULL
    LOOP
        base_codigo := lower(regexp_replace(coalesce(r.nombre, 'tenant-' || left(r.id::text, 8)), '[^a-zA-Z0-9]+', '-', 'g'));
        base_codigo := trim(both '-' from base_codigo);
        IF base_codigo = '' THEN
            base_codigo := 'tenant-' || left(r.id::text, 8);
        END IF;
        codigo_final := base_codigo;
        idx := 2;
        WHILE EXISTS (SELECT 1 FROM tenants WHERE codigo = codigo_final) LOOP
            codigo_final := base_codigo || '-' || idx;
            idx := idx + 1;
        END LOOP;

        nuevo_tenant := gen_random_uuid();
        INSERT INTO tenants (id, taller_id, codigo, nombre, descripcion, estado, contacto_email, contacto_telefono, creado_en, actualizado_en)
        VALUES (nuevo_tenant, r.id, codigo_final, r.nombre, 'Tenant operativo generado desde taller aprobado', 'activo', r.email, r.telefono, NOW(), NOW());

        UPDATE talleres SET tenant_id = nuevo_tenant WHERE id = r.id;
        UPDATE usuarios SET tenant_id = nuevo_tenant WHERE id = r.usuario_id;
        UPDATE tecnicos SET tenant_id = nuevo_tenant WHERE taller_id = r.id;
        UPDATE usuarios SET tenant_id = nuevo_tenant WHERE id IN (SELECT usuario_id FROM tecnicos WHERE taller_id = r.id AND usuario_id IS NOT NULL);
    END LOOP;
END $$;

-- Separar datos legacy: antes varios talleres aprobados podían apuntar al
-- mismo tenant por defecto. En CU29 cada taller aprobado es su propio tenant.
DO $$
DECLARE
    r RECORD;
    base_codigo TEXT;
    codigo_final TEXT;
    idx INTEGER;
    nuevo_tenant UUID;
    total_talleres INTEGER;
    tenant_codigo TEXT;
    tenant_taller_id UUID;
BEGIN
    FOR r IN
        SELECT ta.id, ta.nombre, ta.usuario_id, ta.tenant_id, u.email, u.telefono
        FROM talleres ta
        LEFT JOIN usuarios u ON u.id = ta.usuario_id
        WHERE ta.estado_aprobacion = 'aprobado'
          AND ta.tenant_id IS NOT NULL
    LOOP
        SELECT COUNT(*) INTO total_talleres
        FROM talleres
        WHERE tenant_id = r.tenant_id;

        SELECT codigo, taller_id INTO tenant_codigo, tenant_taller_id
        FROM tenants
        WHERE id = r.tenant_id;

        IF total_talleres > 1
           OR tenant_codigo = 'auxiliscz'
           OR (tenant_taller_id IS NOT NULL AND tenant_taller_id <> r.id)
        THEN
            IF tenant_taller_id = r.id THEN
                UPDATE tenants SET taller_id = NULL WHERE id = r.tenant_id;
            END IF;

            base_codigo := lower(regexp_replace(coalesce(r.nombre, 'tenant-' || left(r.id::text, 8)), '[^a-zA-Z0-9]+', '-', 'g'));
            base_codigo := trim(both '-' from base_codigo);
            IF base_codigo = '' THEN
                base_codigo := 'tenant-' || left(r.id::text, 8);
            END IF;
            codigo_final := base_codigo;
            idx := 2;
            WHILE EXISTS (SELECT 1 FROM tenants WHERE codigo = codigo_final) LOOP
                codigo_final := base_codigo || '-' || idx;
                idx := idx + 1;
            END LOOP;

            nuevo_tenant := gen_random_uuid();
            INSERT INTO tenants (id, taller_id, codigo, nombre, descripcion, estado, contacto_email, contacto_telefono, creado_en, actualizado_en)
            VALUES (nuevo_tenant, r.id, codigo_final, r.nombre, 'Tenant operativo generado desde taller aprobado', 'activo', r.email, r.telefono, NOW(), NOW());

            UPDATE talleres SET tenant_id = nuevo_tenant WHERE id = r.id;
            UPDATE usuarios SET tenant_id = nuevo_tenant WHERE id = r.usuario_id;
            UPDATE tecnicos SET tenant_id = nuevo_tenant WHERE taller_id = r.id;
            UPDATE usuarios SET tenant_id = nuevo_tenant WHERE id IN (SELECT usuario_id FROM tecnicos WHERE taller_id = r.id AND usuario_id IS NOT NULL);
        ELSIF tenant_taller_id IS NULL THEN
            UPDATE tenants SET taller_id = r.id WHERE id = r.tenant_id;
        END IF;
    END LOOP;
END $$;

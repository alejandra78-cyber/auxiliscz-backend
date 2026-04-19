BEGIN;

-- 1) Romper dependencias residuales del esquema viejo
ALTER TABLE IF EXISTS solicitudes DROP CONSTRAINT IF EXISTS solicitudes_incidente_id_fkey;
ALTER TABLE IF EXISTS evidencias DROP CONSTRAINT IF EXISTS evidencias_incidente_id_fkey;
ALTER TABLE IF EXISTS evidencias DROP COLUMN IF EXISTS incidente_id;

-- 2) Eliminar tablas antiguas
DROP TABLE IF EXISTS analisis_ia CASCADE;
DROP TABLE IF EXISTS historial_estados CASCADE;
DROP TABLE IF EXISTS dispositivos_push CASCADE;
DROP TABLE IF EXISTS calificaciones CASCADE;
DROP TABLE IF EXISTS incidentes CASCADE;

COMMIT;

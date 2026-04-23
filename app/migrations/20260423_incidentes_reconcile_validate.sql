-- Reconciliación y validación de referencias a incidentes (PostgreSQL)
-- Ejecutar después de 20260422_incidentes_backfill.sql

BEGIN;

UPDATE emergencias e
SET incidente_id = s.incidente_id
FROM solicitudes s
WHERE e.solicitud_id = s.id
  AND e.incidente_id IS NULL
  AND s.incidente_id IS NOT NULL;

UPDATE historial h
SET incidente_id = s.incidente_id
FROM solicitudes s
WHERE h.solicitud_id = s.id
  AND h.incidente_id IS NULL
  AND s.incidente_id IS NOT NULL;

UPDATE asignaciones a
SET incidente_id = s.incidente_id
FROM solicitudes s
WHERE a.solicitud_id = s.id
  AND a.incidente_id IS NULL
  AND s.incidente_id IS NOT NULL;

UPDATE notificaciones n
SET incidente_id = s.incidente_id
FROM solicitudes s
WHERE n.solicitud_id = s.id
  AND n.incidente_id IS NULL
  AND s.incidente_id IS NOT NULL;

UPDATE cotizaciones c
SET incidente_id = s.incidente_id
FROM solicitudes s
WHERE c.solicitud_id = s.id
  AND c.incidente_id IS NULL
  AND s.incidente_id IS NOT NULL;

UPDATE mensajes m
SET incidente_id = s.incidente_id
FROM solicitudes s
WHERE m.solicitud_id = s.id
  AND m.incidente_id IS NULL
  AND s.incidente_id IS NOT NULL;

COMMIT;

-- Checks de consistencia
SELECT COUNT(*) AS solicitudes_sin_incidente
FROM solicitudes
WHERE incidente_id IS NULL;

SELECT COUNT(*) AS emergencias_sin_incidente
FROM emergencias
WHERE solicitud_id IS NOT NULL AND incidente_id IS NULL;

SELECT COUNT(*) AS historial_sin_incidente
FROM historial
WHERE solicitud_id IS NOT NULL AND incidente_id IS NULL;

SELECT COUNT(*) AS asignaciones_sin_incidente
FROM asignaciones
WHERE solicitud_id IS NOT NULL AND incidente_id IS NULL;

SELECT COUNT(*) AS notificaciones_sin_incidente
FROM notificaciones
WHERE solicitud_id IS NOT NULL AND incidente_id IS NULL;

SELECT COUNT(*) AS cotizaciones_sin_incidente
FROM cotizaciones
WHERE solicitud_id IS NOT NULL AND incidente_id IS NULL;

SELECT COUNT(*) AS mensajes_sin_incidente
FROM mensajes
WHERE solicitud_id IS NOT NULL AND incidente_id IS NULL;

-- Validar constraints una vez los conteos anteriores estén en 0.
-- ALTER TABLE solicitudes    VALIDATE CONSTRAINT fk_solicitudes_incidente_id;
-- ALTER TABLE emergencias    VALIDATE CONSTRAINT fk_emergencias_incidente_id;
-- ALTER TABLE historial      VALIDATE CONSTRAINT fk_historial_incidente_id;
-- ALTER TABLE asignaciones   VALIDATE CONSTRAINT fk_asignaciones_incidente_id;
-- ALTER TABLE notificaciones VALIDATE CONSTRAINT fk_notificaciones_incidente_id;
-- ALTER TABLE cotizaciones   VALIDATE CONSTRAINT fk_cotizaciones_incidente_id;
-- ALTER TABLE mensajes       VALIDATE CONSTRAINT fk_mensajes_incidente_id;

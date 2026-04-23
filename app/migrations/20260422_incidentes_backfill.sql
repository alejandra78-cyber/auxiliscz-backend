-- Backfill seguro para poblar incidentes desde solicitudes/emergencias (PostgreSQL)
-- Fase 2: convivencia.

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Mapeo determinístico: una fila por solicitud con su incidente final.
CREATE TEMP TABLE tmp_solicitudes_incidentes (
  solicitud_id uuid PRIMARY KEY,
  incidente_id uuid NOT NULL,
  cliente_id uuid NOT NULL,
  vehiculo_id uuid NOT NULL,
  estado varchar(50) NOT NULL,
  prioridad integer NOT NULL,
  tipo varchar(50) NOT NULL,
  descripcion text,
  creado_en timestamp without time zone NOT NULL,
  actualizado_en timestamp without time zone NOT NULL
) ON COMMIT DROP;

INSERT INTO tmp_solicitudes_incidentes (
  solicitud_id, incidente_id, cliente_id, vehiculo_id, estado, prioridad, tipo, descripcion, creado_en, actualizado_en
)
SELECT
  s.id AS solicitud_id,
  COALESCE(s.incidente_id, gen_random_uuid()) AS incidente_id,
  s.cliente_id,
  s.vehiculo_id,
  COALESCE(s.estado, 'pendiente') AS estado,
  COALESCE(s.prioridad, 2) AS prioridad,
  COALESCE(e.tipo, 'incierto') AS tipo,
  e.descripcion,
  COALESCE(s.creado_en, now()) AS creado_en,
  COALESCE(s.actualizado_en, COALESCE(s.creado_en, now())) AS actualizado_en
FROM solicitudes s
LEFT JOIN emergencias e ON e.solicitud_id = s.id;

-- Inserta incidentes faltantes (incluye IDs ya presentes en solicitudes.incidente_id y los generados nuevos).
INSERT INTO incidentes (
  id, cliente_id, vehiculo_id, estado, prioridad, tipo, descripcion, canal_origen, creado_en, actualizado_en
)
SELECT
  t.incidente_id,
  t.cliente_id,
  t.vehiculo_id,
  t.estado,
  t.prioridad,
  t.tipo,
  t.descripcion,
  'api',
  t.creado_en,
  t.actualizado_en
FROM tmp_solicitudes_incidentes t
WHERE NOT EXISTS (
  SELECT 1 FROM incidentes i WHERE i.id = t.incidente_id
);

-- Asegura referencia en solicitudes.
UPDATE solicitudes s
SET incidente_id = t.incidente_id
FROM tmp_solicitudes_incidentes t
WHERE s.id = t.solicitud_id
  AND (s.incidente_id IS NULL OR s.incidente_id <> t.incidente_id);

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

-- Fase final opcional: validar constraints cuando se confirme consistencia.
-- ALTER TABLE solicitudes    VALIDATE CONSTRAINT fk_solicitudes_incidente_id;
-- ALTER TABLE emergencias    VALIDATE CONSTRAINT fk_emergencias_incidente_id;
-- ALTER TABLE historial      VALIDATE CONSTRAINT fk_historial_incidente_id;
-- ALTER TABLE asignaciones   VALIDATE CONSTRAINT fk_asignaciones_incidente_id;
-- ALTER TABLE notificaciones VALIDATE CONSTRAINT fk_notificaciones_incidente_id;
-- ALTER TABLE cotizaciones   VALIDATE CONSTRAINT fk_cotizaciones_incidente_id;
-- ALTER TABLE mensajes       VALIDATE CONSTRAINT fk_mensajes_incidente_id;

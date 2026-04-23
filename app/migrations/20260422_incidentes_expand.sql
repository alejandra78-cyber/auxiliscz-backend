-- Expansión segura para introducir incidentes (PostgreSQL)
-- Fase 1: agregar estructuras sin romper comportamiento existente.

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS incidentes (
  id uuid PRIMARY KEY,
  cliente_id uuid NOT NULL REFERENCES clientes(id),
  vehiculo_id uuid NOT NULL REFERENCES vehiculos(id),
  estado varchar(50) NOT NULL DEFAULT 'pendiente',
  prioridad integer NOT NULL DEFAULT 2,
  tipo varchar(50) NOT NULL DEFAULT 'incierto',
  descripcion text,
  canal_origen varchar(20) NOT NULL DEFAULT 'api',
  creado_en timestamp without time zone DEFAULT now(),
  actualizado_en timestamp without time zone DEFAULT now(),
  cerrado_en timestamp without time zone
);

ALTER TABLE solicitudes    ADD COLUMN IF NOT EXISTS incidente_id uuid;
ALTER TABLE emergencias    ADD COLUMN IF NOT EXISTS incidente_id uuid;
ALTER TABLE historial      ADD COLUMN IF NOT EXISTS incidente_id uuid;
ALTER TABLE asignaciones   ADD COLUMN IF NOT EXISTS incidente_id uuid;
ALTER TABLE notificaciones ADD COLUMN IF NOT EXISTS incidente_id uuid;
ALTER TABLE cotizaciones   ADD COLUMN IF NOT EXISTS incidente_id uuid;
ALTER TABLE mensajes       ADD COLUMN IF NOT EXISTS incidente_id uuid;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'fk_solicitudes_incidente_id'
  ) THEN
    ALTER TABLE solicitudes
    ADD CONSTRAINT fk_solicitudes_incidente_id
    FOREIGN KEY (incidente_id) REFERENCES incidentes(id) NOT VALID;
  END IF;
END$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'fk_emergencias_incidente_id'
  ) THEN
    ALTER TABLE emergencias
    ADD CONSTRAINT fk_emergencias_incidente_id
    FOREIGN KEY (incidente_id) REFERENCES incidentes(id) NOT VALID;
  END IF;
END$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'fk_historial_incidente_id'
  ) THEN
    ALTER TABLE historial
    ADD CONSTRAINT fk_historial_incidente_id
    FOREIGN KEY (incidente_id) REFERENCES incidentes(id) NOT VALID;
  END IF;
END$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'fk_asignaciones_incidente_id'
  ) THEN
    ALTER TABLE asignaciones
    ADD CONSTRAINT fk_asignaciones_incidente_id
    FOREIGN KEY (incidente_id) REFERENCES incidentes(id) NOT VALID;
  END IF;
END$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'fk_notificaciones_incidente_id'
  ) THEN
    ALTER TABLE notificaciones
    ADD CONSTRAINT fk_notificaciones_incidente_id
    FOREIGN KEY (incidente_id) REFERENCES incidentes(id) NOT VALID;
  END IF;
END$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'fk_cotizaciones_incidente_id'
  ) THEN
    ALTER TABLE cotizaciones
    ADD CONSTRAINT fk_cotizaciones_incidente_id
    FOREIGN KEY (incidente_id) REFERENCES incidentes(id) NOT VALID;
  END IF;
END$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'fk_mensajes_incidente_id'
  ) THEN
    ALTER TABLE mensajes
    ADD CONSTRAINT fk_mensajes_incidente_id
    FOREIGN KEY (incidente_id) REFERENCES incidentes(id) NOT VALID;
  END IF;
END$$;

COMMIT;

-- Crear índices concurrentemente fuera de transacción.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_incidentes_cliente ON incidentes(cliente_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_incidentes_vehiculo ON incidentes(vehiculo_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_incidentes_estado ON incidentes(estado);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_incidentes_estado_prioridad_creado
ON incidentes(estado, prioridad, creado_en DESC);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_solicitudes_incidente_id_new ON solicitudes(incidente_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_emergencias_incidente_id_new ON emergencias(incidente_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_historial_incidente_id_new ON historial(incidente_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_asignaciones_incidente_id_new ON asignaciones(incidente_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_notificaciones_incidente_id_new ON notificaciones(incidente_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_cotizaciones_incidente_id_new ON cotizaciones(incidente_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_mensajes_incidente_id_new ON mensajes(incidente_id);

-- Rollback del ajuste histórico de timezone.
-- Revierte sumando 4 horas.

BEGIN;

UPDATE usuarios SET creado_en = creado_en + INTERVAL '4 hours' WHERE creado_en IS NOT NULL;
UPDATE usuarios_roles SET asignado_en = asignado_en + INTERVAL '4 hours' WHERE asignado_en IS NOT NULL;
UPDATE roles_permisos SET asignado_en = asignado_en + INTERVAL '4 hours' WHERE asignado_en IS NOT NULL;
UPDATE clientes SET creado_en = creado_en + INTERVAL '4 hours' WHERE creado_en IS NOT NULL;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='incidentes') THEN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='incidentes' AND column_name='actualizado_en')
       AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='incidentes' AND column_name='cerrado_en') THEN
      EXECUTE '
        UPDATE incidentes
        SET creado_en = creado_en + INTERVAL ''4 hours'',
            actualizado_en = actualizado_en + INTERVAL ''4 hours'',
            cerrado_en = CASE WHEN cerrado_en IS NOT NULL THEN cerrado_en + INTERVAL ''4 hours'' ELSE NULL END
        WHERE creado_en IS NOT NULL OR actualizado_en IS NOT NULL OR cerrado_en IS NOT NULL
      ';
    ELSIF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='incidentes' AND column_name='actualizado_en') THEN
      EXECUTE '
        UPDATE incidentes
        SET creado_en = creado_en + INTERVAL ''4 hours'',
            actualizado_en = actualizado_en + INTERVAL ''4 hours''
        WHERE creado_en IS NOT NULL OR actualizado_en IS NOT NULL
      ';
    ELSE
      EXECUTE '
        UPDATE incidentes
        SET creado_en = creado_en + INTERVAL ''4 hours''
        WHERE creado_en IS NOT NULL
      ';
    END IF;
  END IF;
END$$;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='solicitudes' AND column_name='actualizado_en') THEN
    EXECUTE '
      UPDATE solicitudes
      SET creado_en = creado_en + INTERVAL ''4 hours'',
          actualizado_en = actualizado_en + INTERVAL ''4 hours''
      WHERE creado_en IS NOT NULL OR actualizado_en IS NOT NULL
    ';
  ELSE
    EXECUTE '
      UPDATE solicitudes
      SET creado_en = creado_en + INTERVAL ''4 hours''
      WHERE creado_en IS NOT NULL
    ';
  END IF;
END$$;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='emergencias' AND column_name='actualizado_en') THEN
    EXECUTE '
      UPDATE emergencias
      SET creado_en = creado_en + INTERVAL ''4 hours'',
          actualizado_en = actualizado_en + INTERVAL ''4 hours''
      WHERE creado_en IS NOT NULL OR actualizado_en IS NOT NULL
    ';
  ELSE
    EXECUTE '
      UPDATE emergencias
      SET creado_en = creado_en + INTERVAL ''4 hours''
      WHERE creado_en IS NOT NULL
    ';
  END IF;
END$$;

UPDATE ubicaciones SET registrado_en = registrado_en + INTERVAL '4 hours' WHERE registrado_en IS NOT NULL;
UPDATE asignaciones SET asignado_en = asignado_en + INTERVAL '4 hours' WHERE asignado_en IS NOT NULL;
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='disponibilidades' AND column_name='hasta') THEN
    EXECUTE '
      UPDATE disponibilidades
      SET desde = desde + INTERVAL ''4 hours'',
          hasta = CASE WHEN hasta IS NOT NULL THEN hasta + INTERVAL ''4 hours'' ELSE NULL END
      WHERE desde IS NOT NULL OR hasta IS NOT NULL
    ';
  ELSE
    EXECUTE '
      UPDATE disponibilidades
      SET desde = desde + INTERVAL ''4 hours''
      WHERE desde IS NOT NULL
    ';
  END IF;
END$$;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='turnos' AND column_name='fin') THEN
    EXECUTE '
      UPDATE turnos
      SET inicio = inicio + INTERVAL ''4 hours'',
          fin = CASE WHEN fin IS NOT NULL THEN fin + INTERVAL ''4 hours'' ELSE NULL END
      WHERE inicio IS NOT NULL OR fin IS NOT NULL
    ';
  ELSE
    EXECUTE '
      UPDATE turnos
      SET inicio = inicio + INTERVAL ''4 hours''
      WHERE inicio IS NOT NULL
    ';
  END IF;
END$$;

UPDATE evaluaciones SET creado_en = creado_en + INTERVAL '4 hours' WHERE creado_en IS NOT NULL;
UPDATE cotizaciones SET creado_en = creado_en + INTERVAL '4 hours' WHERE creado_en IS NOT NULL;
UPDATE comisiones SET creado_en = creado_en + INTERVAL '4 hours' WHERE creado_en IS NOT NULL;
UPDATE historial SET creado_en = creado_en + INTERVAL '4 hours' WHERE creado_en IS NOT NULL;
UPDATE evidencias SET subido_en = subido_en + INTERVAL '4 hours' WHERE subido_en IS NOT NULL;
UPDATE solicitudes_evidencias SET creado_en = creado_en + INTERVAL '4 hours' WHERE creado_en IS NOT NULL;
UPDATE notificaciones SET creada_en = creada_en + INTERVAL '4 hours' WHERE creada_en IS NOT NULL;
UPDATE mensajes SET creado_en = creado_en + INTERVAL '4 hours' WHERE creado_en IS NOT NULL;
UPDATE metricas SET creado_en = creado_en + INTERVAL '4 hours' WHERE creado_en IS NOT NULL;
UPDATE auditorias SET fecha = fecha + INTERVAL '4 hours' WHERE fecha IS NOT NULL;

COMMIT;

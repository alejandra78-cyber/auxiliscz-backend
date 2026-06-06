-- Corrige duplicados activos de cotizaciones por solicitud/taller y evita que vuelvan a crearse.

WITH ranked AS (
    SELECT
        id,
        ROW_NUMBER() OVER (
            PARTITION BY solicitud_id, taller_id
            ORDER BY
                CASE WHEN estado = 'aceptada' THEN 0 ELSE 1 END,
                COALESCE(fecha_respuesta_cliente, actualizado_en, creado_en, fecha_emision) DESC NULLS LAST,
                id DESC
        ) AS rn
    FROM cotizaciones
    WHERE solicitud_id IS NOT NULL
      AND taller_id IS NOT NULL
      AND estado IN ('pendiente', 'enviada', 'aceptada', 'cotizacion_enviada')
)
UPDATE cotizaciones c
SET estado = 'rechazada',
    actualizado_en = COALESCE(c.actualizado_en, NOW())
FROM ranked r
WHERE c.id = r.id
  AND r.rn > 1;

CREATE UNIQUE INDEX IF NOT EXISTS ux_cotizaciones_activas_solicitud_taller
ON cotizaciones(solicitud_id, taller_id)
WHERE solicitud_id IS NOT NULL
  AND taller_id IS NOT NULL
  AND estado IN ('pendiente', 'enviada', 'aceptada', 'cotizacion_enviada');

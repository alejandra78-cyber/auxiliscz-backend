BEGIN;

DO $$
BEGIN
  -- Compatibilidad con estado legado de pagos
  IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'estado_pago_enum') THEN
    ALTER TYPE estado_pago_enum ADD VALUE IF NOT EXISTS 'pendiente_verificacion';
    ALTER TYPE estado_pago_enum ADD VALUE IF NOT EXISTS 'pagado';
  END IF;
END $$;

-- Backfill semántico sin pérdida de datos
UPDATE pagos
SET estado = 'pendiente_verificacion'
WHERE estado = 'pendiente'
  AND LOWER(COALESCE(metodo, '')) IN ('qr', 'transferencia');

UPDATE pagos
SET estado = 'pagado'
WHERE estado = 'completado';

COMMIT;


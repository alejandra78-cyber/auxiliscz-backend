BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS servicios (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  codigo VARCHAR(80) NOT NULL UNIQUE,
  nombre_visible VARCHAR(120) NOT NULL,
  activo BOOLEAN NOT NULL DEFAULT TRUE,
  creado_en TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS taller_servicios (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  taller_id UUID NOT NULL REFERENCES talleres(id) ON DELETE CASCADE,
  servicio_id UUID NOT NULL REFERENCES servicios(id) ON DELETE RESTRICT,
  creado_en TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tecnico_especialidades (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tecnico_id UUID NOT NULL REFERENCES tecnicos(id) ON DELETE CASCADE,
  servicio_id UUID NOT NULL REFERENCES servicios(id) ON DELETE RESTRICT,
  creado_en TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_taller_servicios_taller_servicio
  ON taller_servicios(taller_id, servicio_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_tecnico_especialidades_tecnico_servicio
  ON tecnico_especialidades(tecnico_id, servicio_id);
CREATE INDEX IF NOT EXISTS idx_servicios_codigo ON servicios(codigo);
CREATE INDEX IF NOT EXISTS idx_taller_servicios_taller ON taller_servicios(taller_id);
CREATE INDEX IF NOT EXISTS idx_tecnico_especialidades_tecnico ON tecnico_especialidades(tecnico_id);

WITH canonical(codigo, nombre_visible) AS (
  VALUES
    ('bateria', 'Batería'),
    ('llanta', 'Cambio de llanta'),
    ('motor', 'Motor'),
    ('choque', 'Choque'),
    ('remolque', 'Remolque / Grúa'),
    ('arranque_de_emergencia', 'Arranque de emergencia'),
    ('auxilio_de_combustible', 'Auxilio de combustible'),
    ('cerrajeria_automotriz', 'Cerrajería automotriz'),
    ('diagnostico_electrico', 'Diagnóstico eléctrico'),
    ('otros', 'Otros')
)
INSERT INTO servicios (codigo, nombre_visible, activo)
SELECT c.codigo, c.nombre_visible, TRUE
FROM canonical c
ON CONFLICT (codigo) DO UPDATE
SET nombre_visible = EXCLUDED.nombre_visible,
    activo = TRUE;

WITH raw_taller AS (
  SELECT
    t.id AS taller_id,
    trim(v.value) AS raw
  FROM talleres t
  CROSS JOIN LATERAL (
    SELECT unnest(
      CASE
        WHEN t.servicios IS NULL OR trim(t.servicios) = '' THEN ARRAY[]::text[]
        WHEN left(trim(t.servicios), 1) = '[' THEN ARRAY(SELECT jsonb_array_elements_text(t.servicios::jsonb))
        ELSE string_to_array(t.servicios, ',')
      END
    ) AS value
  ) v
),
normalized_taller AS (
  SELECT
    taller_id,
    CASE
      WHEN base IN ('bateria') THEN 'bateria'
      WHEN base IN ('llanta', 'cambio_llanta', 'cambio_de_llanta') THEN 'llanta'
      WHEN base IN ('motor') THEN 'motor'
      WHEN base IN ('choque') THEN 'choque'
      WHEN base IN ('remolque', 'remolque_grua', 'remolque_y_grua') THEN 'remolque'
      WHEN base IN ('arranque_de_emergencia') THEN 'arranque_de_emergencia'
      WHEN base IN ('auxilio_de_combustible') THEN 'auxilio_de_combustible'
      WHEN base IN ('cerrajeria_automotriz') THEN 'cerrajeria_automotriz'
      WHEN base IN ('diagnostico_electrico') THEN 'diagnostico_electrico'
      WHEN base IN ('otros') THEN 'otros'
      ELSE NULL
    END AS codigo
  FROM (
    SELECT
      taller_id,
      regexp_replace(
        lower(
          regexp_replace(
            translate(raw, 'ÁÀÄÂáàäâÉÈËÊéèëêÍÌÏÎíìïîÓÒÖÔóòöôÚÙÜÛúùüûÑñ', 'AAAAaaaaEEEEeeeeIIIIiiiiOOOOooooUUUUuuuuNn'),
            '[^a-zA-Z0-9]+',
            '_',
            'g'
          )
        ),
        '^_+|_+$',
        '',
        'g'
      ) AS base
    FROM raw_taller
  ) x
  WHERE base IS NOT NULL AND base <> ''
)
INSERT INTO taller_servicios (taller_id, servicio_id)
SELECT DISTINCT nt.taller_id, s.id
FROM normalized_taller nt
JOIN servicios s ON s.codigo = nt.codigo
ON CONFLICT (taller_id, servicio_id) DO NOTHING;

WITH raw_tecnico AS (
  SELECT
    te.id AS tecnico_id,
    te.taller_id,
    trim(v.value) AS raw
  FROM tecnicos te
  CROSS JOIN LATERAL (
    SELECT unnest(
      CASE
        WHEN te.especialidad IS NULL OR trim(te.especialidad) = '' THEN ARRAY[]::text[]
        ELSE string_to_array(te.especialidad, ',')
      END
    ) AS value
  ) v
),
normalized_tecnico AS (
  SELECT
    tecnico_id,
    taller_id,
    CASE
      WHEN base IN ('bateria') THEN 'bateria'
      WHEN base IN ('llanta', 'cambio_llanta', 'cambio_de_llanta') THEN 'llanta'
      WHEN base IN ('motor') THEN 'motor'
      WHEN base IN ('choque') THEN 'choque'
      WHEN base IN ('remolque', 'remolque_grua', 'remolque_y_grua') THEN 'remolque'
      WHEN base IN ('arranque_de_emergencia') THEN 'arranque_de_emergencia'
      WHEN base IN ('auxilio_de_combustible') THEN 'auxilio_de_combustible'
      WHEN base IN ('cerrajeria_automotriz') THEN 'cerrajeria_automotriz'
      WHEN base IN ('diagnostico_electrico') THEN 'diagnostico_electrico'
      WHEN base IN ('otros') THEN 'otros'
      ELSE NULL
    END AS codigo
  FROM (
    SELECT
      tecnico_id,
      taller_id,
      regexp_replace(
        lower(
          regexp_replace(
            translate(raw, 'ÁÀÄÂáàäâÉÈËÊéèëêÍÌÏÎíìïîÓÒÖÔóòöôÚÙÜÛúùüûÑñ', 'AAAAaaaaEEEEeeeeIIIIiiiiOOOOooooUUUUuuuuNn'),
            '[^a-zA-Z0-9]+',
            '_',
            'g'
          )
        ),
        '^_+|_+$',
        '',
        'g'
      ) AS base
    FROM raw_tecnico
  ) x
  WHERE base IS NOT NULL AND base <> ''
)
INSERT INTO tecnico_especialidades (tecnico_id, servicio_id)
SELECT DISTINCT nt.tecnico_id, s.id
FROM normalized_tecnico nt
JOIN servicios s ON s.codigo = nt.codigo
JOIN taller_servicios ts ON ts.taller_id = nt.taller_id AND ts.servicio_id = s.id
ON CONFLICT (tecnico_id, servicio_id) DO NOTHING;

UPDATE talleres t
SET servicios = (
  SELECT json_agg(s.codigo ORDER BY s.codigo)::text
  FROM taller_servicios ts
  JOIN servicios s ON s.id = ts.servicio_id
  WHERE ts.taller_id = t.id
)
WHERE EXISTS (
  SELECT 1 FROM taller_servicios ts WHERE ts.taller_id = t.id
);

UPDATE tecnicos te
SET especialidad = (
  SELECT string_agg(s.codigo, ', ' ORDER BY s.codigo)
  FROM tecnico_especialidades te2
  JOIN servicios s ON s.id = te2.servicio_id
  WHERE te2.tecnico_id = te.id
)
WHERE EXISTS (
  SELECT 1 FROM tecnico_especialidades te2 WHERE te2.tecnico_id = te.id
);

COMMIT;


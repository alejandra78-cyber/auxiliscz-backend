BEGIN;

CREATE TABLE IF NOT EXISTS dispositivos_push (
    id UUID PRIMARY KEY,
    usuario_id UUID NOT NULL REFERENCES usuarios(id),
    token VARCHAR(512) NOT NULL UNIQUE,
    plataforma VARCHAR(30) DEFAULT 'unknown',
    activo BOOLEAN NOT NULL DEFAULT TRUE,
    creado_en TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    actualizado_en TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dispositivos_push_usuario_id
    ON dispositivos_push(usuario_id);

CREATE INDEX IF NOT EXISTS idx_dispositivos_push_usuario_activo
    ON dispositivos_push(usuario_id, activo);

CREATE INDEX IF NOT EXISTS idx_dispositivos_push_token
    ON dispositivos_push(token);

COMMIT;

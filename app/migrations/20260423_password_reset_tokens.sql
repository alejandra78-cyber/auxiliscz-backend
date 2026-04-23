BEGIN;

CREATE TABLE IF NOT EXISTS password_reset_tokens (
  id UUID PRIMARY KEY,
  usuario_id UUID NOT NULL REFERENCES usuarios(id),
  token_hash VARCHAR(128) NOT NULL UNIQUE,
  scope VARCHAR(40) NOT NULL DEFAULT 'password_recovery',
  expires_en TIMESTAMP WITHOUT TIME ZONE NOT NULL,
  usado_en TIMESTAMP WITHOUT TIME ZONE,
  creado_en TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_password_reset_tokens_usuario_scope
  ON password_reset_tokens(usuario_id, scope);

CREATE INDEX IF NOT EXISTS ix_password_reset_tokens_token_hash
  ON password_reset_tokens(token_hash);

COMMIT;

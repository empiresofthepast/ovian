-- Personal access tokens: long-lived, revocable keys for scripts and AI assistants (the MCP server).
CREATE TABLE IF NOT EXISTS api_tokens (
  id           bigserial PRIMARY KEY,
  player_id    bigint NOT NULL REFERENCES players(id) ON DELETE CASCADE,
  name         text   NOT NULL,
  token_hash   text   NOT NULL UNIQUE,
  prefix       text   NOT NULL,
  created_at   bigint NOT NULL,
  last_used_at bigint,
  revoked_at   bigint
);
CREATE INDEX IF NOT EXISTS api_tokens_player_idx ON api_tokens(player_id);

-- Finds dug up in cities. They outlive their finders: a lost owner or city leaves the record in the catalogue.
CREATE TABLE IF NOT EXISTS finds (
  id          bigserial PRIMARY KEY,
  player_id   bigint REFERENCES players(id) ON DELETE SET NULL,
  village_id  bigint REFERENCES villages(id) ON DELETE SET NULL,   -- the city that keeps it
  name        text   NOT NULL,
  grade       text   NOT NULL,
  culture     double precision NOT NULL DEFAULT 0,
  context     jsonb  NOT NULL,   -- where and in what layer it was found
  found_at    bigint NOT NULL,
  found_by    text   NOT NULL
);
CREATE INDEX IF NOT EXISTS finds_player_idx ON finds(player_id);
CREATE INDEX IF NOT EXISTS finds_village_idx ON finds(village_id);

-- Governors: each rules one city (own or a vassal's), or travels to one.
CREATE TABLE IF NOT EXISTS governors (
  id          bigserial PRIMARY KEY,
  player_id   bigint NOT NULL REFERENCES players(id) ON DELETE CASCADE,
  name        text   NOT NULL,
  tribe       text   NOT NULL,
  traits      jsonb  NOT NULL,
  village_id  bigint REFERENCES villages(id) ON DELETE SET NULL,   -- where they rule
  moving_to   bigint REFERENCES villages(id) ON DELETE SET NULL,   -- where they are going
  arrives_at  bigint,
  hired_at    bigint NOT NULL
);
CREATE INDEX IF NOT EXISTS governors_player_idx ON governors(player_id);
CREATE UNIQUE INDEX IF NOT EXISTS governors_village_idx ON governors(village_id);

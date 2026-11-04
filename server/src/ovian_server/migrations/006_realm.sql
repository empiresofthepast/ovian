-- Medals and rounds, roads and trade routes, espionage, festivals, the chronicle, bans and bots.

ALTER TABLE players ADD COLUMN bot boolean NOT NULL DEFAULT false;
ALTER TABLE players ADD COLUMN banned_until bigint NOT NULL DEFAULT 0;
ALTER TABLE players ADD COLUMN ban_reason text NOT NULL DEFAULT '';
ALTER TABLE movements ADD COLUMN mission text;

-- Counters as they stood when the last medals were handed out; medals go to the biggest gains since.
CREATE TABLE stat_snapshots (
    player_id bigint NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    stat      text NOT NULL,
    value     double precision NOT NULL,
    PRIMARY KEY (player_id, stat)
);

CREATE TABLE medals (
    id        bigserial PRIMARY KEY,
    player_id bigint NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    round     integer NOT NULL DEFAULT 1,
    period    integer NOT NULL,           -- 1, 2, 3 ... within the round
    category  text NOT NULL,
    rank      integer NOT NULL,
    value     double precision NOT NULL,
    at        bigint NOT NULL
);
CREATE INDEX medals_player_idx ON medals (player_id);
CREATE INDEX medals_period_idx ON medals (round, period);

-- One row per finished round: winner, leaders and medals, kept across resets.
CREATE TABLE hall_of_fame (
    round     integer PRIMARY KEY,
    ended_at  bigint NOT NULL,
    data      jsonb NOT NULL
);

CREATE TABLE roads (
    id        bigserial PRIMARY KEY,
    player_id bigint NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    a_id      bigint NOT NULL REFERENCES villages(id) ON DELETE CASCADE,
    b_id      bigint NOT NULL REFERENCES villages(id) ON DELETE CASCADE,
    started_at bigint NOT NULL,
    ready_at  bigint NOT NULL,
    CHECK (a_id < b_id),
    UNIQUE (a_id, b_id)
);

CREATE TABLE trade_routes (
    id         bigserial PRIMARY KEY,
    village_id bigint NOT NULL REFERENCES villages(id) ON DELETE CASCADE,
    to_id      bigint NOT NULL REFERENCES villages(id) ON DELETE CASCADE,
    resources  jsonb NOT NULL,
    every_ms   bigint NOT NULL,
    next_at    bigint NOT NULL,
    last_error text,
    created_at bigint NOT NULL
);
CREATE INDEX trade_routes_village_idx ON trade_routes (village_id);

CREATE TABLE festival_entries (
    festival  integer NOT NULL,
    contest   text NOT NULL,
    player_id bigint NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    village_id bigint,
    score     double precision NOT NULL,
    at        bigint NOT NULL,
    PRIMARY KEY (festival, contest, player_id)
);

CREATE TABLE chronicle (
    id        bigserial PRIMARY KEY,
    round     integer NOT NULL DEFAULT 1,
    at        bigint NOT NULL,
    kind      text NOT NULL,
    title     text NOT NULL,
    x         integer,
    y         integer,
    player_id bigint REFERENCES players(id) ON DELETE SET NULL,
    village_id bigint,
    data      jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX chronicle_round_idx ON chronicle (round, id);

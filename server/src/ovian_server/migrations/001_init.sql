-- Times are epoch milliseconds (bigint), matching the engine.

CREATE TABLE players (
    id              bigserial PRIMARY KEY,
    username        text NOT NULL,
    password_hash   text NOT NULL,
    tribe           text NOT NULL,
    created_at      bigint NOT NULL,
    protected_until bigint NOT NULL DEFAULT 0,
    -- Free-form data for plugins.
    meta            jsonb NOT NULL DEFAULT '{}'
);
CREATE UNIQUE INDEX players_username_key ON players (lower(username));

CREATE TABLE villages (
    id          bigserial PRIMARY KEY,
    player_id   bigint NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    name        text NOT NULL,
    x           integer NOT NULL,
    y           integer NOT NULL,
    -- Engine village state: resources, resources_at, slots, units.
    state       jsonb NOT NULL,
    population  integer NOT NULL DEFAULT 0,
    created_at  bigint NOT NULL,
    meta        jsonb NOT NULL DEFAULT '{}',
    UNIQUE (x, y)
);
CREATE INDEX villages_player_idx ON villages (player_id);

-- Timed work: construction, training, troop arrivals, and anything plugins schedule.
CREATE TABLE jobs (
    id          bigserial PRIMARY KEY,
    kind        text NOT NULL,
    due_at      bigint NOT NULL,
    village_id  bigint REFERENCES villages(id) ON DELETE CASCADE,
    payload     jsonb NOT NULL DEFAULT '{}',
    attempts    integer NOT NULL DEFAULT 0,
    failed      boolean NOT NULL DEFAULT false,
    last_error  text
);
CREATE INDEX jobs_due_idx ON jobs (due_at) WHERE NOT failed;
CREATE INDEX jobs_village_idx ON jobs (village_id, kind);

CREATE TABLE movements (
    id          bigserial PRIMARY KEY,
    kind        text NOT NULL CHECK (kind IN ('attack', 'raid', 'reinforce', 'return')),
    player_id   bigint NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    -- Village the troops belong to.
    home_id     bigint NOT NULL REFERENCES villages(id) ON DELETE CASCADE,
    from_id     bigint NOT NULL REFERENCES villages(id) ON DELETE CASCADE,
    to_id       bigint NOT NULL REFERENCES villages(id) ON DELETE CASCADE,
    units       jsonb NOT NULL,
    loot        jsonb NOT NULL DEFAULT '{}',
    departs_at  bigint NOT NULL,
    arrives_at  bigint NOT NULL
);
CREATE INDEX movements_from_idx ON movements (from_id);
CREATE INDEX movements_to_idx ON movements (to_id);

-- Reinforcements stationed in a village they do not belong to.
CREATE TABLE stationed (
    id          bigserial PRIMARY KEY,
    host_id     bigint NOT NULL REFERENCES villages(id) ON DELETE CASCADE,
    home_id     bigint NOT NULL REFERENCES villages(id) ON DELETE CASCADE,
    units       jsonb NOT NULL,
    UNIQUE (host_id, home_id)
);

CREATE TABLE reports (
    id          bigserial PRIMARY KEY,
    player_id   bigint NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    kind        text NOT NULL,
    title       text NOT NULL,
    data        jsonb NOT NULL,
    read        boolean NOT NULL DEFAULT false,
    created_at  bigint NOT NULL
);
CREATE INDEX reports_player_idx ON reports (player_id, id DESC);

CREATE TABLE chat_messages (
    id          bigserial PRIMARY KEY,
    channel     text NOT NULL,
    player_id   bigint NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    text        text NOT NULL,
    created_at  bigint NOT NULL
);
CREATE INDEX chat_channel_idx ON chat_messages (channel, id DESC);

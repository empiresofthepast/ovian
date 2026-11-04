-- Alliances, trade, heroes, barbarian camps, quests, gods, great buildings, achievements, vacation and the world's end.

ALTER TABLE players ADD COLUMN npc boolean NOT NULL DEFAULT false;
ALTER TABLE players ADD COLUMN vacation_until bigint NOT NULL DEFAULT 0;
ALTER TABLE movements ADD COLUMN hero boolean NOT NULL DEFAULT false;

CREATE TABLE alliances (
    id          bigserial PRIMARY KEY,
    name        text NOT NULL,
    tag         text NOT NULL,
    description text NOT NULL DEFAULT '',
    created_at  bigint NOT NULL
);
CREATE UNIQUE INDEX alliances_tag_key ON alliances (lower(tag));
CREATE UNIQUE INDEX alliances_name_key ON alliances (lower(name));

CREATE TABLE alliance_members (
    player_id   bigint PRIMARY KEY REFERENCES players(id) ON DELETE CASCADE,
    alliance_id bigint NOT NULL REFERENCES alliances(id) ON DELETE CASCADE,
    role        text NOT NULL DEFAULT 'member',   -- leader, officer, member
    joined_at   bigint NOT NULL
);
CREATE INDEX alliance_members_alliance_idx ON alliance_members (alliance_id);

CREATE TABLE alliance_invites (
    alliance_id bigint NOT NULL REFERENCES alliances(id) ON DELETE CASCADE,
    player_id   bigint NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    invited_by  bigint REFERENCES players(id) ON DELETE SET NULL,
    created_at  bigint NOT NULL,
    PRIMARY KEY (alliance_id, player_id)
);

-- One row per direction. Alliances and pacts need the other side to accept; war does not.
CREATE TABLE diplomacy (
    alliance_id bigint NOT NULL REFERENCES alliances(id) ON DELETE CASCADE,
    other_id    bigint NOT NULL REFERENCES alliances(id) ON DELETE CASCADE,
    kind        text NOT NULL,                    -- ally, nap, war
    status      text NOT NULL DEFAULT 'active',   -- proposed, active
    since       bigint NOT NULL,
    PRIMARY KEY (alliance_id, other_id)
);

CREATE TABLE alliance_messages (
    id          bigserial PRIMARY KEY,
    alliance_id bigint NOT NULL REFERENCES alliances(id) ON DELETE CASCADE,
    player_id   bigint REFERENCES players(id) ON DELETE SET NULL,
    text        text NOT NULL,
    created_at  bigint NOT NULL
);
CREATE INDEX alliance_messages_idx ON alliance_messages (alliance_id, id);

CREATE TABLE trade_offers (
    id          bigserial PRIMARY KEY,
    village_id  bigint NOT NULL REFERENCES villages(id) ON DELETE CASCADE,
    give        jsonb NOT NULL,
    want        jsonb NOT NULL,
    merchants   integer NOT NULL,
    created_at  bigint NOT NULL
);

CREATE TABLE heroes (
    player_id   bigint PRIMARY KEY REFERENCES players(id) ON DELETE CASCADE,
    village_id  bigint REFERENCES villages(id) ON DELETE SET NULL,
    template    text NOT NULL DEFAULT '',
    name        text NOT NULL,
    xp          double precision NOT NULL DEFAULT 0,
    points      jsonb NOT NULL DEFAULT '{"attack": 0, "defense": 0, "production": 0}',
    status      text NOT NULL DEFAULT 'home',     -- home, away, dead
    revive_at   bigint NOT NULL DEFAULT 0,
    created_at  bigint NOT NULL
);

CREATE TABLE quests_done (
    player_id   bigint NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    quest_id    text NOT NULL,
    at          bigint NOT NULL,
    PRIMARY KEY (player_id, quest_id)
);

CREATE TABLE achievements (
    player_id   bigint NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    id          text NOT NULL,
    at          bigint NOT NULL,
    PRIMARY KEY (player_id, id)
);

-- Counters for quests and achievements (battles won, camps beaten, ...).
CREATE TABLE player_stats (
    player_id   bigint NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    stat        text NOT NULL,
    value       double precision NOT NULL DEFAULT 0,
    PRIMARY KEY (player_id, stat)
);

CREATE TABLE great_contributions (
    id          bigserial PRIMARY KEY,
    village_id  bigint NOT NULL REFERENCES villages(id) ON DELETE CASCADE,
    building    text NOT NULL,
    level       integer NOT NULL,
    player_id   bigint REFERENCES players(id) ON DELETE SET NULL,
    points      double precision NOT NULL,
    created_at  bigint NOT NULL
);
CREATE INDEX great_contributions_idx ON great_contributions (village_id, building, level);

CREATE TABLE world_state (
    key         text PRIMARY KEY,
    value       jsonb NOT NULL
);

ALTER TABLE movements DROP CONSTRAINT IF EXISTS movements_kind_check;
ALTER TABLE movements ADD CONSTRAINT movements_kind_check CHECK (kind IN ('attack', 'raid', 'reinforce', 'return', 'scout'));

-- Favor starts gathering now in every existing city.
UPDATE villages SET meta = meta || jsonb_build_object('favor_at', (extract(epoch FROM now()) * 1000)::bigint) WHERE NOT meta ? 'favor_at';

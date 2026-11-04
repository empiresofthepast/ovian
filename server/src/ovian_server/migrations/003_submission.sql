-- Submission: a city beaten often enough becomes the vassal of the city that beat it.

-- Battles won in a row by a player against a city. A successful defence clears the count.
CREATE TABLE dominance (
    player_id   bigint NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    target_id   bigint NOT NULL REFERENCES villages(id) ON DELETE CASCADE,
    -- The city that won last; it becomes the overlord on the deciding win.
    village_id  bigint NOT NULL REFERENCES villages(id) ON DELETE CASCADE,
    wins        integer NOT NULL DEFAULT 0,
    PRIMARY KEY (player_id, target_id)
);

-- One overlord per vassal city. `flow` is the hourly tribute currently paid.
CREATE TABLE vassals (
    vassal_id   bigint PRIMARY KEY REFERENCES villages(id) ON DELETE CASCADE,
    overlord_id bigint NOT NULL REFERENCES villages(id) ON DELETE CASCADE,
    since       bigint NOT NULL,
    flow        jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX vassals_overlord_idx ON vassals (overlord_id);

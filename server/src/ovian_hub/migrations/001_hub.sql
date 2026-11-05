-- The hub: one account for every world, founders, badges, Patreon, and the list of worlds.
-- Times are epoch milliseconds (bigint), like the worlds.

CREATE TABLE accounts (
    id             bigserial PRIMARY KEY,
    username       text NOT NULL,
    password_hash  text NOT NULL,
    email          text,
    created_at     bigint NOT NULL,
    last_login_at  bigint,
    is_admin       boolean NOT NULL DEFAULT false,
    -- Founders: the first supporters. founder_no orders them (Founder #1, #2, ...).
    founder        boolean NOT NULL DEFAULT false,
    founder_no     integer,
    founder_since  bigint,
    meta           jsonb NOT NULL DEFAULT '{}'
);
CREATE UNIQUE INDEX accounts_username_key ON accounts (lower(username));
CREATE UNIQUE INDEX accounts_founder_no_key ON accounts (founder_no) WHERE founder_no IS NOT NULL;

-- The badge catalogue. kind: founder (given with founder status), patron (from a Patreon tier), award (by hand).
CREATE TABLE badges (
    id            text PRIMARY KEY,
    name          text NOT NULL,
    description   text NOT NULL DEFAULT '',
    icon          text NOT NULL DEFAULT '',
    color         text NOT NULL DEFAULT '#b8892c',
    kind          text NOT NULL DEFAULT 'award' CHECK (kind IN ('founder', 'patron', 'award')),
    -- patron badges: the Patreon tier id that gives it ('*' = any active pledge)
    patreon_tier  text,
    sort          integer NOT NULL DEFAULT 0,
    created_at    bigint NOT NULL
);

-- source: admin, founder or patreon. Patreon badges come and go with the pledge.
CREATE TABLE account_badges (
    account_id  bigint NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    badge_id    text NOT NULL REFERENCES badges(id) ON DELETE CASCADE,
    source      text NOT NULL,
    granted_at  bigint NOT NULL,
    granted_by  bigint REFERENCES accounts(id) ON DELETE SET NULL,
    note        text NOT NULL DEFAULT '',
    PRIMARY KEY (account_id, badge_id)
);

CREATE TABLE patreon_links (
    account_id       bigint PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
    patreon_user_id  text NOT NULL UNIQUE,
    patron_status    text,
    tier_ids         text[] NOT NULL DEFAULT '{}',
    cents            integer NOT NULL DEFAULT 0,
    linked_at        bigint NOT NULL,
    updated_at       bigint NOT NULL
);

-- Pledges seen by the webhook before their patron linked an account; applied on linking.
CREATE TABLE patreon_members (
    patreon_user_id  text PRIMARY KEY,
    patron_status    text,
    tier_ids         text[] NOT NULL DEFAULT '{}',
    cents            integer NOT NULL DEFAULT 0,
    updated_at       bigint NOT NULL
);

-- status: upcoming (listed, not joinable), open, closed (no new players), ended.
CREATE TABLE worlds (
    id             text PRIMARY KEY,
    name           text NOT NULL,
    description    text NOT NULL DEFAULT '',
    pack           text NOT NULL DEFAULT '',
    speed          real NOT NULL DEFAULT 1,
    -- where browsers reach the world's API: a path on the site (/w/w2) or a full origin
    api_url        text NOT NULL,
    -- where the hub reaches it to push badges (e.g. http://server:8000); empty: no pushes
    internal_url   text NOT NULL DEFAULT '',
    status         text NOT NULL DEFAULT 'open' CHECK (status IN ('upcoming', 'open', 'closed', 'ended')),
    -- early access: only founders (and patrons, if patrons_early) may join while set
    founders_only  boolean NOT NULL DEFAULT false,
    patrons_early  boolean NOT NULL DEFAULT false,
    starts_at      bigint,
    ends_at        bigint,
    sort           integer NOT NULL DEFAULT 0,
    created_at     bigint NOT NULL
);

CREATE TABLE memberships (
    account_id  bigint NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    world_id    text NOT NULL REFERENCES worlds(id) ON DELETE CASCADE,
    player_id   bigint NOT NULL,
    joined_at   bigint NOT NULL,
    PRIMARY KEY (account_id, world_id)
);

INSERT INTO badges(id, name, description, icon, color, kind, patreon_tier, sort, created_at) VALUES
  ('founder', 'Founder', 'Among the first to found Empires of the Past.', '🏛', '#c9962e', 'founder', NULL, 0, 0),
  ('patron', 'Patron', 'Supports Empires of the Past on Patreon.', '🏺', '#9b4d2e', 'patron', '*', 10, 0);

-- Superusers, and when players log in and are last seen.
ALTER TABLE players ADD COLUMN is_admin boolean NOT NULL DEFAULT false;
ALTER TABLE players ADD COLUMN last_login_at bigint;
ALTER TABLE players ADD COLUMN last_seen_at bigint;
ALTER TABLE players ADD COLUMN logins integer NOT NULL DEFAULT 0;

-- Accounts from the hub (one login for many worlds). account_id links a player to its hub account;
-- badges and founder_no mirror the hub so profiles, rankings and chat can show them.
ALTER TABLE players ADD COLUMN account_id bigint;
ALTER TABLE players ADD COLUMN badges jsonb NOT NULL DEFAULT '[]';
ALTER TABLE players ADD COLUMN founder_no integer;
CREATE UNIQUE INDEX players_account_key ON players (account_id) WHERE account_id IS NOT NULL;

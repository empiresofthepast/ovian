-- Culture points of each village, kept next to population so neighbourhood queries stay cheap.
ALTER TABLE villages ADD COLUMN culture double precision NOT NULL DEFAULT 0;
CREATE INDEX villages_culture_idx ON villages (player_id) WHERE culture > 0;

-- Treaties between two players: a pact of peace, with an optional tribute one side pays the other.
CREATE TABLE treaties (
    id           bigserial PRIMARY KEY,
    a_id         bigint NOT NULL REFERENCES players(id) ON DELETE CASCADE,  -- who proposed it
    b_id         bigint NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    status       text NOT NULL CHECK (status IN ('proposed', 'active')),
    tribute      jsonb,           -- {payer: player id, resources: {...}, every_ms}
    created_at   bigint NOT NULL,
    since        bigint,
    ends_at      bigint,          -- notice given: the pact holds until then
    last_paid_at bigint
);
CREATE UNIQUE INDEX treaties_pair_key ON treaties (least(a_id, b_id), greatest(a_id, b_id));

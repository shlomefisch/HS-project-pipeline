-- A phone that saved something without signal sends it later, maybe twice if the
-- signal drops mid-send. Each such request carries a one-time key; the first
-- answer is kept, and any repeat gets that same answer instead of doing it again.
CREATE TABLE idempotency_keys (
    key          TEXT PRIMARY KEY,
    method       TEXT NOT NULL,
    path         TEXT NOT NULL,
    status_code  INTEGER NOT NULL,
    body         TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_idempotency_created ON idempotency_keys (created_at);

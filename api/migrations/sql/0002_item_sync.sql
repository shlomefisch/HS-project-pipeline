-- NetSuite item sync: the items table becomes a real copy of NetSuite's
-- inventory items, refreshed on a timer. Read-only — nothing goes back.

ALTER TABLE items ADD COLUMN is_lot BOOLEAN NOT NULL DEFAULT FALSE;
CREATE INDEX ix_items_sku_trgm ON items USING gin (lower(sku) gin_trgm_ops);

-- One row per sync attempt, so the Team screen can show what happened and when.
CREATE TABLE sync_runs (
    id           SERIAL PRIMARY KEY,
    kind         TEXT NOT NULL CHECK (kind IN ('items')),
    mode         TEXT NOT NULL CHECK (mode IN ('full','changes')),
    started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at  TIMESTAMPTZ,
    status       TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running','ok','failed')),
    rows_seen    INTEGER NOT NULL DEFAULT 0,
    error        TEXT,
    started_by   INTEGER REFERENCES users(id),
    CHECK (status <> 'failed' OR error IS NOT NULL)
);
CREATE INDEX ix_sync_runs_kind ON sync_runs (kind, started_at DESC);

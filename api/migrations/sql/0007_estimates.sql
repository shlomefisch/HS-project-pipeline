-- Order assembly, third part: the estimate, assembled here before it goes to NetSuite.
-- Prices start at NetSuite's Base Price and can always be changed.

CREATE TABLE estimates (
    id            SERIAL PRIMARY KEY,
    job_id        INTEGER NOT NULL REFERENCES jobs(id),
    status        TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','pushed','discarded')),
    note          TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by    INTEGER REFERENCES users(id),
    pushed_at     TIMESTAMPTZ,
    netsuite_estimate_id INTEGER
);
-- One draft per job at a time.
CREATE UNIQUE INDEX ux_estimates_one_draft ON estimates (job_id) WHERE status = 'draft';

CREATE TABLE estimate_areas (
    estimate_id  INTEGER NOT NULL REFERENCES estimates(id),
    area_id      INTEGER NOT NULL REFERENCES areas(id),
    job_id       INTEGER NOT NULL REFERENCES jobs(id),
    PRIMARY KEY (estimate_id, area_id)
);

CREATE TABLE estimate_lines (
    id                SERIAL PRIMARY KEY,
    estimate_id       INTEGER NOT NULL REFERENCES estimates(id),
    job_id            INTEGER NOT NULL REFERENCES jobs(id),
    tag_id            INTEGER REFERENCES candidate_tags(id),
    area_id           INTEGER REFERENCES areas(id),
    netsuite_item_id  INTEGER,
    description       TEXT NOT NULL,
    quantity          NUMERIC(12,2) CHECK (quantity IS NULL OR quantity > 0),
    unit              TEXT,
    base_price        NUMERIC(12,4),
    price             NUMERIC(12,4) CHECK (price IS NULL OR price >= 0),
    price_note        TEXT,
    sort_order        INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX ix_estimate_lines_estimate ON estimate_lines (estimate_id, sort_order);

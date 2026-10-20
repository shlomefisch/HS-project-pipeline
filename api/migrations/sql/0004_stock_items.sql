-- Only items with custitem4 checked are real stocking items; the rest were
-- ordered once for a project. Plus each item's unit of measure (SF, PC, ...).

ALTER TABLE items ADD COLUMN is_stock BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE items ADD COLUMN unit TEXT;
ALTER TABLE items ADD COLUMN unit_id INTEGER;
CREATE INDEX ix_items_stock ON items (is_stock) WHERE is_stock AND active;

-- Forget earlier runs so the next one is a full copy that fills the new columns.
DELETE FROM sync_runs;

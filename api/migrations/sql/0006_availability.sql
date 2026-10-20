-- Order assembly, second part: availability, per tile per area.
-- available   one lot covers it (stock), or nothing to check
-- two_lots    only enough across lots: short by default
-- override    the rep chose to go ahead on two lots, with a reason
-- short       not enough
-- confirmed   local supplier confirmed / overseas lead time confirmed

ALTER TABLE candidate_tags ADD COLUMN avail_status TEXT
    CHECK (avail_status IN ('available','two_lots','override','short','confirmed'));
ALTER TABLE candidate_tags ADD COLUMN avail_lot TEXT;
ALTER TABLE candidate_tags ADD COLUMN avail_free NUMERIC(12,2);
ALTER TABLE candidate_tags ADD COLUMN avail_need NUMERIC(12,2);
ALTER TABLE candidate_tags ADD COLUMN avail_note TEXT;
ALTER TABLE candidate_tags ADD COLUMN avail_summary TEXT;
ALTER TABLE candidate_tags ADD COLUMN avail_checked_at TIMESTAMPTZ;
ALTER TABLE candidate_tags ADD COLUMN avail_checked_by INTEGER REFERENCES users(id);
ALTER TABLE candidate_tags ADD CONSTRAINT ck_tags_override_reason
    CHECK (avail_status IS DISTINCT FROM 'override' OR avail_note IS NOT NULL);

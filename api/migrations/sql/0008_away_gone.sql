-- Away or gone. Away: dates and a cover; everything the person holds, and
-- everything new, goes to the cover, remembered as "covering for". On return,
-- open work goes back and finished work stays credited to the cover.

ALTER TABLE jobs ADD COLUMN covering_for_id INTEGER REFERENCES users(id);
ALTER TABLE tasks ADD COLUMN covering_for_id INTEGER REFERENCES users(id);
ALTER TABLE scheduled_visits ADD COLUMN covering_for_id INTEGER REFERENCES users(id);

CREATE TABLE absences (
    id             SERIAL PRIMARY KEY,
    user_id        INTEGER NOT NULL REFERENCES users(id),
    cover_id       INTEGER NOT NULL REFERENCES users(id),
    starts_on      DATE NOT NULL,
    ends_on        DATE NOT NULL,
    note           TEXT,
    status         TEXT NOT NULL DEFAULT 'planned' CHECK (status IN ('planned','active','ended','cancelled')),
    took_takeoff   BOOLEAN NOT NULL DEFAULT FALSE,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by     INTEGER REFERENCES users(id),
    started_at     TIMESTAMPTZ,
    ended_at       TIMESTAMPTZ,
    CHECK (ends_on >= starts_on),
    CHECK (cover_id <> user_id)
);
-- One current absence per person.
CREATE UNIQUE INDEX ux_absences_one_current ON absences (user_id) WHERE status IN ('planned','active');

-- Order assembly, first part: plans on the job, footage per area, the takeoff task.

-- Footage: one final number per area, waste included, with where it came from.
ALTER TABLE areas ADD COLUMN footage NUMERIC(10,2) CHECK (footage IS NULL OR footage > 0);
ALTER TABLE areas ADD COLUMN footage_source TEXT CHECK (footage_source IN ('customer','designer','installer','takeoff'));
ALTER TABLE areas ADD COLUMN footage_by TEXT;
ALTER TABLE areas ADD COLUMN footage_confidence TEXT CHECK (footage_confidence IN ('approximate','confirmed'));
ALTER TABLE areas ADD COLUMN footage_set_at TIMESTAMPTZ;
ALTER TABLE areas ADD CONSTRAINT ck_areas_footage_parts
    CHECK (footage IS NULL OR (footage_source IS NOT NULL AND footage_confidence IS NOT NULL));

-- Tasks with a special meaning. Only one open takeoff per job.
ALTER TABLE tasks ADD COLUMN kind TEXT CHECK (kind IN ('takeoff'));
CREATE UNIQUE INDEX ux_tasks_one_open_takeoff ON tasks (job_id) WHERE kind = 'takeoff' AND status IN ('open','blocked');

-- Small admin settings, e.g. who does takeoffs by default.
CREATE TABLE app_settings (
    key         TEXT PRIMARY KEY,
    value       TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by  INTEGER REFERENCES users(id)
);

-- Plans, photos, scanned notes. A pasted link is a row too: a single-file link
-- holds the file itself; a folder link holds the files pulled from it (link_id).
CREATE TABLE job_files (
    id            SERIAL PRIMARY KEY,
    job_id        INTEGER NOT NULL REFERENCES jobs(id),
    area_id       INTEGER REFERENCES areas(id),
    kind          TEXT NOT NULL DEFAULT 'plan' CHECK (kind IN ('plan','photo','note','other')),
    name          TEXT NOT NULL,
    content_type  TEXT,
    size_bytes    INTEGER,
    source        TEXT NOT NULL CHECK (source IN ('upload','link','from_link')),
    link_url      TEXT,
    link_id       INTEGER REFERENCES job_files(id),
    status        TEXT NOT NULL DEFAULT 'ready' CHECK (status IN ('ready','fetching','needs_download')),
    problem       TEXT,
    removed       BOOLEAN NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by    INTEGER REFERENCES users(id),
    CHECK (source <> 'link' OR link_url IS NOT NULL),
    CHECK (source <> 'from_link' OR link_id IS NOT NULL),
    CHECK (status <> 'needs_download' OR problem IS NOT NULL)
);
CREATE INDEX ix_job_files_job ON job_files (job_id, created_at);

-- The bytes, kept apart so listing files never loads them.
CREATE TABLE file_blobs (
    file_id  INTEGER PRIMARY KEY REFERENCES job_files(id),
    data     BYTEA NOT NULL
);

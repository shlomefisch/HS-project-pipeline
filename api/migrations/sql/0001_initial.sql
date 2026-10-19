-- 0001 — first slice: people, jobs, selection, timeline, tasks, audit.
-- Every job-scoped table carries job_id so the audit log can attach
-- each change to its job without extra lookups.

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ---------------------------------------------------------------- users
CREATE TABLE users (
    id              SERIAL PRIMARY KEY,
    email           TEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL DEFAULT '',
    role            TEXT NOT NULL DEFAULT 'pending'
                    CHECK (role IN ('pending','rep','back_office','management','viewer')),
    is_admin        BOOLEAN NOT NULL DEFAULT FALSE,
    home_showroom   TEXT,
    default_class   TEXT,
    active          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at   TIMESTAMPTZ
);

-- ------------------------------------------------------------- entities
CREATE TABLE entities (
    id                      SERIAL PRIMARY KEY,
    kind                    TEXT NOT NULL DEFAULT 'person'
                            CHECK (kind IN ('person','company')),
    name                    TEXT NOT NULL,
    company_id              INTEGER REFERENCES entities(id),
    phone                   TEXT,
    email                   TEXT,
    address                 TEXT,
    notes                   TEXT,
    name_norm               TEXT NOT NULL,
    phone_norm              TEXT,
    email_norm              TEXT,
    netsuite_customer_id    TEXT,
    merged_into_id          INTEGER REFERENCES entities(id),
    active                  BOOLEAN NOT NULL DEFAULT TRUE,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by              INTEGER REFERENCES users(id)
);
CREATE INDEX ix_entities_phone_norm ON entities (phone_norm);
CREATE INDEX ix_entities_email_norm ON entities (email_norm);
CREATE INDEX ix_entities_name_trgm  ON entities USING gin (name_norm gin_trgm_ops);

-- ----------------------------------------------------------------- jobs
CREATE TABLE jobs (
    id                  SERIAL PRIMARY KEY,
    name                TEXT NOT NULL,
    address             TEXT,
    class_code          TEXT NOT NULL,
    project_type        TEXT,
    lead_source         TEXT,
    lead_showroom       TEXT,
    rep_id              INTEGER NOT NULL REFERENCES users(id),
    default_contact_id  INTEGER REFERENCES entities(id),
    status              TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active','on_hold','lost','closed')),
    hold_until          DATE,
    hold_reason         TEXT,
    lost_reason         TEXT,
    lost_note           TEXT,
    closed_at           TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by          INTEGER REFERENCES users(id),
    CHECK (status <> 'on_hold' OR (hold_until IS NOT NULL AND hold_reason IS NOT NULL)),
    CHECK (status <> 'lost' OR lost_reason IS NOT NULL)
);
CREATE INDEX ix_jobs_rep ON jobs (rep_id, status);
CREATE INDEX ix_jobs_name_trgm ON jobs USING gin (lower(name) gin_trgm_ops);

CREATE TABLE job_roles (
    id          SERIAL PRIMARY KEY,
    job_id      INTEGER NOT NULL REFERENCES jobs(id),
    entity_id   INTEGER NOT NULL REFERENCES entities(id),
    role        TEXT NOT NULL
                CHECK (role IN ('owner','designer','contractor','installer','pm','other')),
    active      BOOLEAN NOT NULL DEFAULT TRUE,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at    TIMESTAMPTZ,
    created_by  INTEGER REFERENCES users(id)
);
CREATE INDEX ix_job_roles_job ON job_roles (job_id, active);
CREATE INDEX ix_job_roles_entity ON job_roles (entity_id);

-- ------------------------------------------------------------ selection
CREATE TABLE areas (
    id           SERIAL PRIMARY KEY,
    job_id       INTEGER NOT NULL REFERENCES jobs(id),
    name         TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'open'
                 CHECK (status IN ('open','decided','dropped','on_hold')),
    hold_until   DATE,
    hold_reason  TEXT,
    sort_order   INTEGER NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by   INTEGER REFERENCES users(id),
    CHECK (status <> 'on_hold' OR (hold_until IS NOT NULL AND hold_reason IS NOT NULL))
);
CREATE UNIQUE INDEX ux_areas_job_name ON areas (job_id, lower(name));

-- Stand-in for the NetSuite item cache. The real sync fills this table later.
CREATE TABLE items (
    netsuite_id  INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,
    sku          TEXT,
    size         TEXT,
    finish       TEXT,
    image_url    TEXT,
    active       BOOLEAN NOT NULL DEFAULT TRUE,
    synced_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_items_name_trgm ON items USING gin (lower(name) gin_trgm_ops);

-- No foreign key to items on purpose: a scan in a dead corner still
-- creates the candidate with the id, and the name fills in later.
CREATE TABLE candidates (
    id                SERIAL PRIMARY KEY,
    job_id            INTEGER NOT NULL REFERENCES jobs(id),
    source            TEXT NOT NULL CHECK (source IN ('stock','local','overseas')),
    netsuite_item_id  INTEGER,
    name              TEXT,
    supplier          TEXT,
    lead_time_weeks   INTEGER,
    notes             TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by        INTEGER REFERENCES users(id),
    CHECK (name IS NOT NULL OR netsuite_item_id IS NOT NULL),
    CHECK (source <> 'stock' OR netsuite_item_id IS NOT NULL)
);
CREATE INDEX ix_candidates_job ON candidates (job_id);

-- The decision lives here: one tile, one row per area it is considered for.
CREATE TABLE candidate_tags (
    id            SERIAL PRIMARY KEY,
    job_id        INTEGER NOT NULL REFERENCES jobs(id),
    candidate_id  INTEGER NOT NULL REFERENCES candidates(id),
    area_id       INTEGER NOT NULL REFERENCES areas(id),
    status        TEXT NOT NULL DEFAULT 'considering'
                  CHECK (status IN ('considering','chosen','declined')),
    quantity      NUMERIC(12,2),
    unit          TEXT NOT NULL DEFAULT 'sf',
    reason        TEXT,
    decided_at    TIMESTAMPTZ,
    decided_by    INTEGER REFERENCES users(id),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (candidate_id, area_id),
    CHECK (status <> 'declined' OR reason IS NOT NULL)
);
CREATE INDEX ix_tags_area ON candidate_tags (area_id);

CREATE TABLE samples (
    id               SERIAL PRIMARY KEY,
    job_id           INTEGER NOT NULL REFERENCES jobs(id),
    area_id          INTEGER REFERENCES areas(id),
    candidate_id     INTEGER REFERENCES candidates(id),
    description      TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'requested'
                     CHECK (status IN ('requested','sent','replied','cancelled')),
    requested_on     DATE NOT NULL DEFAULT CURRENT_DATE,
    sent_on          DATE,
    expect_reply_by  DATE,
    notes            TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by       INTEGER REFERENCES users(id)
);

-- ------------------------------------------------------------- timeline
CREATE TABLE scheduled_visits (
    id                 SERIAL PRIMARY KEY,
    job_id             INTEGER NOT NULL REFERENCES jobs(id),
    rep_id             INTEGER NOT NULL REFERENCES users(id),
    showroom           TEXT,
    kind               TEXT NOT NULL CHECK (kind IN ('showroom','site')),
    starts_at          TIMESTAMPTZ NOT NULL,
    purpose            TEXT,
    expected           TEXT,
    status             TEXT NOT NULL DEFAULT 'scheduled'
                       CHECK (status IN ('scheduled','happened','no_show','cancelled','rescheduled')),
    resolved_at        TIMESTAMPTZ,
    resolved_by        INTEGER REFERENCES users(id),
    rescheduled_to_id  INTEGER REFERENCES scheduled_visits(id),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by         INTEGER REFERENCES users(id)
);
CREATE INDEX ix_visits_rep_day ON scheduled_visits (rep_id, starts_at);
CREATE INDEX ix_visits_showroom_day ON scheduled_visits (showroom, starts_at);

CREATE TABLE events (
    id                  SERIAL PRIMARY KEY,
    job_id              INTEGER NOT NULL REFERENCES jobs(id),
    kind                TEXT NOT NULL CHECK (kind IN ('contact','showroom_visit','site_visit')),
    occurred_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    channel             TEXT CHECK (channel IN ('phone','text','email','whatsapp','in_person')),
    direction           TEXT CHECK (direction IN ('in','out')),
    showroom            TEXT,
    summary             TEXT NOT NULL,
    notes               TEXT,
    scheduled_visit_id  INTEGER REFERENCES scheduled_visits(id),
    logged_by           INTEGER REFERENCES users(id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_events_job ON events (job_id, occurred_at DESC);

CREATE TABLE event_people (
    event_id   INTEGER NOT NULL REFERENCES events(id),
    entity_id  INTEGER NOT NULL REFERENCES entities(id),
    PRIMARY KEY (event_id, entity_id)
);

-- ---------------------------------------------------------------- tasks
-- The owner is not stored: it is always the rep on the job.
CREATE TABLE tasks (
    id                   SERIAL PRIMARY KEY,
    job_id               INTEGER NOT NULL REFERENCES jobs(id),
    area_id              INTEGER REFERENCES areas(id),
    title                TEXT NOT NULL,
    notes                TEXT,
    assignee_id          INTEGER NOT NULL REFERENCES users(id),
    due_date             DATE NOT NULL,
    status               TEXT NOT NULL DEFAULT 'open'
                         CHECK (status IN ('open','blocked','done','bad_answer','skipped')),
    severity             TEXT NOT NULL DEFAULT 'silent'
                         CHECK (severity IN ('silent','notify','interrupt')),
    outcome_note         TEXT,
    needs_rep_attention  BOOLEAN NOT NULL DEFAULT FALSE,
    parent_task_id       INTEGER REFERENCES tasks(id),
    source_event_id      INTEGER REFERENCES events(id),
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by           INTEGER REFERENCES users(id),
    completed_at         TIMESTAMPTZ,
    completed_by         INTEGER REFERENCES users(id),
    CHECK (status NOT IN ('blocked','bad_answer','skipped') OR outcome_note IS NOT NULL)
);
CREATE INDEX ix_tasks_assignee_open ON tasks (assignee_id, due_date) WHERE status IN ('open','blocked');
CREATE INDEX ix_tasks_job_open ON tasks (job_id) WHERE status IN ('open','blocked');

-- ---------------------------------------------------------------- audit
-- Every change to every table above lands here, field by field.
-- story = shown on the job's "story" tab; everything is on "everything".
CREATE TABLE audit_log (
    id          BIGSERIAL PRIMARY KEY,
    at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    user_id     INTEGER REFERENCES users(id),
    job_id      INTEGER REFERENCES jobs(id),
    table_name  TEXT NOT NULL,
    row_id      TEXT NOT NULL,
    action      TEXT NOT NULL CHECK (action IN ('insert','update','delete')),
    changes     JSONB NOT NULL DEFAULT '{}'::jsonb,
    story       BOOLEAN NOT NULL DEFAULT FALSE,
    summary     TEXT
);
CREATE INDEX ix_audit_job ON audit_log (job_id, at DESC);
CREATE INDEX ix_audit_row ON audit_log (table_name, row_id);

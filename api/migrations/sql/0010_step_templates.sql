-- Step templates: the steps the app adds by itself at set moments in a job.
-- Written and changed by admins on the Team screen; empty until someone fills it.

CREATE TABLE step_templates (
    id                SERIAL PRIMARY KEY,
    trigger           TEXT NOT NULL CHECK (trigger IN ('job_created','takeoff_done','estimate_started','area_decided')),
    playbook          TEXT NOT NULL DEFAULT 'all' CHECK (playbook IN ('all','single_family','projects')),
    title             TEXT NOT NULL,
    notes             TEXT,
    assignee_kind     TEXT NOT NULL DEFAULT 'rep' CHECK (assignee_kind IN ('rep','takeoff','actor','user')),
    assignee_user_id  INTEGER REFERENCES users(id),
    due_days          INTEGER NOT NULL DEFAULT 1 CHECK (due_days BETWEEN 0 AND 365),
    severity          TEXT NOT NULL DEFAULT 'silent' CHECK (severity IN ('silent','notify','interrupt')),
    sort_order        INTEGER NOT NULL DEFAULT 0,
    active            BOOLEAN NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by        INTEGER REFERENCES users(id),
    CHECK (assignee_kind <> 'user' OR assignee_user_id IS NOT NULL)
);

ALTER TABLE tasks ADD COLUMN template_step_id INTEGER REFERENCES step_templates(id);

-- After the estimate: orders. Areas sent out together become an order, and the
-- order carries its own stage until it's closed. A job is done only when every
-- order is closed and every area is delivered or dropped.

CREATE TABLE orders (
    id                    SERIAL PRIMARY KEY,
    job_id                INTEGER NOT NULL REFERENCES jobs(id),
    estimate_id           INTEGER NOT NULL UNIQUE REFERENCES estimates(id),
    stage                 TEXT NOT NULL DEFAULT 'negotiating'
                          CHECK (stage IN ('negotiating','processing','delivery','closing','closed','lost')),
    handler_id            INTEGER REFERENCES users(id),
    netsuite_estimate_ref TEXT,
    netsuite_order_ref    TEXT,
    sent_by_hand          BOOLEAN NOT NULL DEFAULT FALSE,
    chk_delivered         TIMESTAMPTZ,
    chk_returns           TIMESTAMPTZ,
    chk_credits           TIMESTAMPTZ,
    chk_paid              TIMESTAMPTZ,
    lost_reason           TEXT,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by            INTEGER REFERENCES users(id),
    closed_at             TIMESTAMPTZ,
    CHECK (stage NOT IN ('processing','delivery','closing','closed') OR handler_id IS NOT NULL),
    CHECK (stage <> 'closed' OR (chk_delivered IS NOT NULL AND chk_returns IS NOT NULL AND chk_credits IS NOT NULL AND chk_paid IS NOT NULL)),
    CHECK (stage <> 'lost' OR lost_reason IS NOT NULL)
);
CREATE INDEX ix_orders_job ON orders (job_id);

-- A quantity change on something already ordered: old, new, who, when, why.
CREATE TABLE order_changes (
    id           SERIAL PRIMARY KEY,
    order_id     INTEGER NOT NULL REFERENCES orders(id),
    job_id       INTEGER NOT NULL REFERENCES jobs(id),
    line_id      INTEGER NOT NULL REFERENCES estimate_lines(id),
    old_quantity NUMERIC(12,2) NOT NULL,
    new_quantity NUMERIC(12,2) NOT NULL CHECK (new_quantity >= 0),
    reason       TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by   INTEGER REFERENCES users(id)
);

-- Areas now go all the way: ordered when on an order, delivered when it closes.
ALTER TABLE areas DROP CONSTRAINT areas_status_check;
ALTER TABLE areas ADD CONSTRAINT areas_status_check CHECK (status IN ('open','decided','dropped','on_hold','ordered','delivered'));

-- Templates for the order stages, and the handler as an assignee.
ALTER TABLE step_templates DROP CONSTRAINT step_templates_trigger_check;
ALTER TABLE step_templates ADD CONSTRAINT step_templates_trigger_check
    CHECK (trigger IN ('job_created','takeoff_done','estimate_started','area_decided','order_placed','order_approved','order_delivery','order_closing'));
ALTER TABLE step_templates DROP CONSTRAINT step_templates_assignee_kind_check;
ALTER TABLE step_templates ADD CONSTRAINT step_templates_assignee_kind_check CHECK (assignee_kind IN ('rep','takeoff','actor','user','handler'));

-- Nothing is ever hard-deleted: a tile added by mistake is hidden, not removed.
ALTER TABLE candidates ADD COLUMN removed_at TIMESTAMPTZ;
ALTER TABLE candidates ADD COLUMN removed_by INTEGER REFERENCES users(id);

ALTER TABLE tasks ADD COLUMN order_id INTEGER REFERENCES orders(id);

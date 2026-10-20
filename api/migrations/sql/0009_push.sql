-- Phone notifications (web push). One row per phone/browser that said yes.
CREATE TABLE push_subscriptions (
    id            SERIAL PRIMARY KEY,
    user_id       INTEGER NOT NULL REFERENCES users(id),
    endpoint      TEXT NOT NULL UNIQUE,
    p256dh        TEXT NOT NULL,
    auth          TEXT NOT NULL,
    user_agent    TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_sent_at  TIMESTAMPTZ,
    failures      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX ix_push_user ON push_subscriptions (user_id);

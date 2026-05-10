-- Push subscriptions for Web Push (VAPID) notifications.
-- One row per browser/device registration per user.
CREATE TABLE push_subscriptions (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    endpoint    TEXT        NOT NULL UNIQUE,
    p256dh      TEXT        NOT NULL,
    auth        TEXT        NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_push_subscriptions_user_id ON push_subscriptions(user_id);

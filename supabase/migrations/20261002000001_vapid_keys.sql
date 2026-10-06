-- The key pair that signs Web Push notifications (app/push.py), one row. The
-- server makes it the first time it needs one, keeping the pair it used to
-- read from Secret Manager if it has one, so there are no secrets to set up.
CREATE TABLE vapid_keys (
    id          SMALLINT    PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    public_key  TEXT        NOT NULL,
    private_key TEXT        NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Only the server (with the secret key) uses it.
ALTER TABLE vapid_keys ENABLE ROW LEVEL SECURITY;

-- One-time links for resetting a forgotten password.
-- Only a SHA-256 hash of each token is stored; the token itself is only ever
-- in the email. A link works once, for an hour.
CREATE TABLE password_resets (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash  TEXT        NOT NULL UNIQUE,
    expires_at  TIMESTAMPTZ NOT NULL,
    used_at     TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_password_resets_user_id ON password_resets(user_id);

ALTER TABLE password_resets ENABLE ROW LEVEL SECURITY;

-- Players prove they own their email before they can sign in with a password.
-- email_verified_at is set when they click a link emailed to them, sign in
-- with Google (which has checked the email) or reset their password (the link
-- went to the email). Accounts from before this have it null, so they verify
-- on their next password sign-in too.
ALTER TABLE users ADD COLUMN email_verified_at TIMESTAMPTZ;

-- Google checked the email of every account linked to it so far.
UPDATE users SET email_verified_at = now() WHERE google_id IS NOT NULL;

-- One-time links for verifying an email. `email` is the address the link was
-- sent to: the account's own email, or a new one the player is changing to,
-- which only replaces the old one when the link is clicked.
-- Only a SHA-256 hash of each token is stored; the token itself is only ever
-- in the email.
CREATE TABLE email_verifications (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    email       TEXT        NOT NULL,
    token_hash  TEXT        NOT NULL UNIQUE,
    expires_at  TIMESTAMPTZ NOT NULL,
    used_at     TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_email_verifications_user_id ON email_verifications(user_id);

ALTER TABLE email_verifications ENABLE ROW LEVEL SECURITY;

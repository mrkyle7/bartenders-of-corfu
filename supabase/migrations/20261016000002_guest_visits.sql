-- Guests (players without an account, in games that allow them) seen in each
-- game, by game and name: when they were last seen, so the owner is told when
-- one turns up after a long gap, not about everything they do (app/activity.py).
CREATE TABLE guest_visits (
    key          TEXT        PRIMARY KEY,
    last_seen_at TIMESTAMPTZ NOT NULL
);

ALTER TABLE guest_visits ENABLE ROW LEVEL SECURITY;

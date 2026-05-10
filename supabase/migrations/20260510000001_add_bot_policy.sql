-- Persistent storage for ML bot learned policy data.
-- Simple key-value store; the MCTS bot stores its action priors here.
CREATE TABLE IF NOT EXISTS bot_policy (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Insert the initial empty policy row
INSERT INTO bot_policy (key, value) VALUES ('mcts_policy', '{"values": {}, "counts": {}, "games_played": 0}')
ON CONFLICT (key) DO NOTHING;

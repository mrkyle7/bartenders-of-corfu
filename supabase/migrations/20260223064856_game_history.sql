-- Game move history, undo requests, and initial state snapshot.
-- Implements the MoveRecord and UndoRequest entities from game.allium.

-- ─── Initial state snapshot ───────────────────────────────────────────────────
-- Stores the full game state at the moment StartGame is called.
-- Combined with game_moves, this allows reconstruction of state at any turn.

ALTER TABLE games ADD COLUMN IF NOT EXISTS initial_state JSONB;

-- ─── game_moves ───────────────────────────────────────────────────────────────
-- One immutable row per completed turn action.
-- state_before holds the full game state immediately before this move was applied,
-- enabling O(1) undo without replaying from the start.

CREATE TABLE IF NOT EXISTS game_moves (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    game_id UUID NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    turn_number INTEGER NOT NULL,
    player_id UUID NOT NULL,
    action_type TEXT NOT NULL,
    action_payload JSONB NOT NULL DEFAULT '{}',
    state_before JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (game_id, turn_number)
);

CREATE INDEX IF NOT EXISTS idx_game_moves_game_id ON game_moves (game_id);

-- ─── undo_requests ────────────────────────────────────────────────────────────
-- At most one pending undo request per game (enforced by partial unique index).

CREATE TABLE IF NOT EXISTS undo_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    game_id UUID NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    target_turn_number INTEGER NOT NULL,
    proposed_by UUID NOT NULL,
    proposed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    votes JSONB NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_undo_requests_one_pending
    ON undo_requests (game_id)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_undo_requests_game_id ON undo_requests (game_id);

-- Undo takes back one move at a time, not a whole turn: an undo request
-- names the move it takes back (turn_number, move_number). Null on requests
-- made before, which took back the whole turn (back to its first move).
ALTER TABLE undo_requests ADD COLUMN IF NOT EXISTS target_move_number INTEGER;

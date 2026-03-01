-- Drop the old per-turn unique constraint so multiple moves can share a turn_number.
-- The new composite constraint game_moves_unique_move (game_id, turn_number, move_number)
-- was added in 20260301000001_move_number.sql and replaces this.
ALTER TABLE game_moves DROP CONSTRAINT IF EXISTS game_moves_game_id_turn_number_key;

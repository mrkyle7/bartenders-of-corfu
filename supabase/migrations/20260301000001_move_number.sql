-- Refactor game_moves to support multiple moves per turn.
--
-- Previously, one move record was written per completed turn, using the
-- post-action turn_number (i.e. the incremented value). Now every individual
-- action (draw_from_bag, each take-ingredients batch, sell_cup, etc.) creates
-- its own move record, all sharing the same pre-action turn_number.
--
-- Migration steps:
--   1. Convert existing post-action turn_numbers → pre-action (subtract 1).
--   2. Add move_number column (existing rows each had a unique turn_number, so
--      DEFAULT 1 is safe and correct).
--   3. Add unique constraint on (game_id, turn_number, move_number).

-- Step 1: drop the old per-turn unique constraint (now turns can have many moves)
ALTER TABLE game_moves DROP CONSTRAINT IF EXISTS game_moves_game_id_turn_number_key;

-- Step 2: shift existing turn_numbers from post-action to pre-action
UPDATE game_moves SET turn_number = turn_number - 1;

-- Step 3: add the move_number column
ALTER TABLE game_moves ADD COLUMN move_number integer NOT NULL DEFAULT 1;

-- Step 4: enforce uniqueness on the composite key
ALTER TABLE game_moves
    ADD CONSTRAINT game_moves_unique_move UNIQUE (game_id, turn_number, move_number);

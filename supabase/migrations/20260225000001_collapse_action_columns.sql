-- Add unified action column
ALTER TABLE game_moves ADD COLUMN action JSONB;

-- Backfill: merge action_type into action_payload as "type" key
UPDATE game_moves
SET action = jsonb_build_object('type', action_type) || action_payload;

-- Enforce NOT NULL
ALTER TABLE game_moves ALTER COLUMN action SET NOT NULL;

-- Drop old columns
ALTER TABLE game_moves DROP COLUMN action_type;
ALTER TABLE game_moves DROP COLUMN action_payload;

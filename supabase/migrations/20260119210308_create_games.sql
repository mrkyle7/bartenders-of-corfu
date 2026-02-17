CREATE TYPE game_status AS ENUM ('NEW', 'STARTED', 'ENDED');

CREATE TABLE games (
  id uuid PRIMARY KEY,
  host uuid REFERENCES users(id),
  players uuid[] NOT NULL DEFAULT '{}',
  status game_status NOT NULL DEFAULT 'NEW',
  latest_state jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz DEFAULT now(),
  CONSTRAINT max_players_limit CHECK (cardinality(players) <= 4)
);

CREATE OR REPLACE FUNCTION add_player_to_game(
  game_id uuid,
  player_id uuid
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
DECLARE
  current_players uuid[];
  current_status game_status;
BEGIN
  -- Lock the game row
  SELECT players, status
  INTO current_players, current_status
  FROM games
  WHERE id = game_id
  FOR UPDATE;

  -- Game not found
  IF NOT FOUND THEN
    RETURN false;
  END IF;

  -- Game not joinable
  IF current_status <> 'NEW' THEN
    RETURN false;
  END IF;

  -- Idempotent: already in the game
  IF current_players @> ARRAY[player_id] THEN
    RETURN true;
  END IF;

  -- Game full
  IF cardinality(current_players) >= 4 THEN
    RETURN false;
  END IF;

  -- Safe to add
  UPDATE games
  SET players = array_append(current_players, player_id)
  WHERE id = game_id;

  RETURN true;
END;
$$;

ALTER TABLE games ENABLE ROW LEVEL SECURITY;
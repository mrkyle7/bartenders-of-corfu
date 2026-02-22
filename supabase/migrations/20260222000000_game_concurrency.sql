-- Can't CREATE OR REPLACE a function with a different return type; must drop first.
DROP FUNCTION IF EXISTS add_player_to_game(uuid, uuid);

CREATE FUNCTION add_player_to_game(game_id uuid, player_id uuid)
RETURNS text LANGUAGE plpgsql SECURITY INVOKER AS $$
DECLARE
  current_players uuid[];
  current_status  game_status;
BEGIN
  SELECT players, status INTO current_players, current_status
  FROM games WHERE id = game_id FOR UPDATE;

  IF NOT FOUND                              THEN RETURN 'not_found'; END IF;
  IF current_status <> 'NEW'               THEN RETURN 'not_new';   END IF;
  IF current_players @> ARRAY[player_id]   THEN RETURN 'duplicate'; END IF;
  IF cardinality(current_players) >= 4     THEN RETURN 'full';      END IF;

  UPDATE games SET players = array_append(current_players, player_id) WHERE id = game_id;
  RETURN 'ok';
END;
$$;

CREATE OR REPLACE FUNCTION remove_player_from_game(
  game_id uuid, requester_id uuid, player_id uuid
) RETURNS text LANGUAGE plpgsql SECURITY INVOKER AS $$
DECLARE
  current_players uuid[];
  current_host    uuid;
BEGIN
  SELECT players, host INTO current_players, current_host
  FROM games WHERE id = game_id FOR UPDATE;

  IF NOT FOUND                                        THEN RETURN 'not_found';   END IF;
  IF requester_id <> current_host                     THEN RETURN 'not_host';    END IF;
  IF NOT (current_players @> ARRAY[player_id])        THEN RETURN 'not_in_game'; END IF;
  IF player_id = current_host                         THEN RETURN 'is_host';     END IF;

  UPDATE games SET
    players      = array_remove(current_players, player_id),
    latest_state = jsonb_set(
      latest_state,
      '{player_states}',
      COALESCE(latest_state->'player_states', '{}') - player_id::text
    )
  WHERE id = game_id;
  RETURN 'ok';
END;
$$;

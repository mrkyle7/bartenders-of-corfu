"""Regression tests: a player eliminated mid-turn must not stall the game.

When a player is hospitalised (drunk_level over MAX_DRUNK_LEVEL) by their own
main action, the turn must advance to the next active player. Otherwise the
game gets stuck — particularly bad for bots, where ``process_bot_turns`` would
see the hospitalised player as the active turn and bail out.
"""

from uuid import uuid4

from app import actions
from app.GameState import GameState
from app.Ingredient import Ingredient
from app.PlayerState import PlayerState
from app.card import Card


def _make_game(num_players=2):
    pids = [uuid4() for _ in range(num_players)]
    player_states = {pid: PlayerState.new_player(pid) for pid in pids}
    gs = GameState(
        winner=None,
        bag_contents=[Ingredient.COLA] * 20,
        player_states=player_states,
        player_turn=pids[0],
        open_display=[Ingredient.COLA] * 5,
        turn_order=list(pids),
        turn_number=0,
    )
    return gs, pids


def _whiskey_free_action_card() -> dict:
    """Free action card that grants reroll_specials — leaves a free slot unused."""
    return Card(
        id=str(uuid4()),
        card_type="free_action",
        name="WHISKEY Free Action",
        spirit_type="WHISKEY",
    ).to_dict()


class TestDrinkCupHospitalisedAdvances:
    def test_drinking_cup_into_hospital_advances_turn(self):
        """Drinking a cup that pushes the player past MAX_DRUNK advances turn."""
        gs, pids = _make_game(2)
        p1, p2 = pids

        # P1 holds a free-action card so the turn would normally wait for it.
        gs.player_states[p1].cards.append(_whiskey_free_action_card())
        # Pre-load drunk level just below max so a single cup pushes them over.
        gs.player_states[p1].drunk_level = 5
        gs.player_states[p1].cups[0].ingredients = [
            Ingredient.VODKA,
            Ingredient.RUM,
        ]

        gs, _ = actions.drink_cup(gs, p1, 0)

        assert gs.player_states[p1].status == "hospitalised"
        assert gs.player_turn == p2, (
            "Turn must advance away from hospitalised player even though a "
            "free action card remains unused"
        )

    def test_drinking_cup_without_elimination_keeps_free_slot_open(self):
        """Sanity check: without elimination, the free-action slot still holds the turn."""
        gs, pids = _make_game(2)
        p1, p2 = pids

        gs.player_states[p1].cards.append(_whiskey_free_action_card())
        gs.player_states[p1].cups[0].ingredients = [Ingredient.COLA]

        gs, _ = actions.drink_cup(gs, p1, 0)

        assert gs.player_states[p1].status == "active"
        assert gs.player_turn == p1  # waiting on the WHISKEY free action


class TestDrinkStoredSpiritHospitalisedAdvances:
    def test_drinking_from_store_into_hospital_advances_turn(self):
        """drink_stored_spirit is a free action; if it eliminates the player,
        the turn must still advance so the game doesn't stall."""
        gs, pids = _make_game(2)
        p1, p2 = pids

        store_card = Card(
            id=str(uuid4()),
            card_type="store",
            name="RUM Store",
            spirit_type="RUM",
        ).to_dict()
        store_card["stored_spirits"] = ["RUM", "RUM"]
        gs.player_states[p1].cards.append(store_card)
        gs.player_states[p1].drunk_level = 4

        store_index = len(gs.player_states[p1].cards) - 1
        gs, _ = actions.drink_stored_spirit(gs, p1, store_index, 2)

        assert gs.player_states[p1].status == "hospitalised"
        assert gs.player_turn == p2


class TestProcessBotTurnsForceAdvancesEliminated:
    """If the active turn somehow lands on an eliminated bot, process_bot_turns
    must force-advance the turn rather than returning silently."""

    def test_eliminated_bot_turn_is_skipped(self):
        from unittest.mock import MagicMock, patch

        from app.bot_player import process_bot_turns
        from app.game import Game, Status

        gs, pids = _make_game(2)
        p1, p2 = pids
        # The active player is eliminated.
        gs.player_states[p1].status = "hospitalised"
        # Don't pre-advance the turn — that's the broken state we're testing.

        game_id = uuid4()
        fake_game = MagicMock(spec=Game)
        fake_game.id = game_id
        fake_game.status = Status.STARTED
        fake_game.game_state = gs
        fake_game.players = {p1, p2}

        bot_user = MagicMock()
        bot_user.id = p1
        bot_user.bot_strategy = "random"

        captured = {}

        def fake_apply_action(_game, _player_id, action_type, new_state, payload):
            captured["action_type"] = action_type
            captured["new_state"] = new_state
            # Mutate the game so the second loop iteration sees the advance.
            fake_game.game_state = new_state

        manager = MagicMock()
        manager._apply_action.side_effect = fake_apply_action

        with patch("app.bot_player.db") as mock_db:
            mock_db.get_game.return_value = fake_game
            mock_db.get_bot_users_by_ids.return_value = [bot_user]
            process_bot_turns(manager, game_id)

        assert captured.get("action_type") == "skip_turn"
        assert captured["new_state"].player_turn == p2

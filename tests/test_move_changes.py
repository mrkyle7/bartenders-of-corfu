"""The history records what each move changed (app/move_changes.py)."""

from uuid import uuid4

from app.actions import _deep_copy_state
from app.card import Card, CardRow
from app.GameState import GameState
from app.Ingredient import Ingredient
from app.move_changes import move_changes
from app.PlayerState import PlayerState


def _game():
    pids = [uuid4(), uuid4()]
    gs = GameState(
        winner=None,
        bag_contents=[Ingredient.COLA] * 10,
        player_states={pid: PlayerState.new_player(pid) for pid in pids},
        player_turn=pids[0],
        card_rows=[
            CardRow(
                position=3,
                cards=[Card(id="a", card_type="store", name="Rum Store")],
            )
        ],
        turn_order=list(pids),
    )
    return gs, pids


def test_nothing_changed_records_nothing():
    gs, _ = _game()
    assert move_changes(gs, _deep_copy_state(gs)) == {}


def test_cards_off_and_onto_the_table():
    gs, _ = _game()
    after = _deep_copy_state(gs)
    after.card_rows[0].cards = [
        Card(id="b", card_type="specialist", name="Gin Specialist")
    ]
    changes = move_changes(gs, after)
    assert changes["cards_out"] == [
        {"name": "Rum Store", "card_type": "store", "row": 3}
    ]
    assert changes["cards_in"] == [
        {"name": "Gin Specialist", "card_type": "specialist", "row": 3}
    ]


def test_only_players_whose_drunk_level_or_points_changed():
    gs, (me, other) = _game()
    after = _deep_copy_state(gs)
    after.player_states[me].points = 5
    after.player_states[me].drunk_level = 2
    changes = move_changes(gs, after)
    assert changes["players"] == {str(me): {"drunk": [0, 2], "points": [0, 5]}}
    assert "cards_out" not in changes

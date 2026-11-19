"""Undo takes back moves one at a time (app/undo.py), and blind bag draws a
taken-back move made come out again if the move is made again that turn
(GameState.bag_redraws)."""

from uuid import uuid4

from app import actions, undo
from app.GameState import GameState
from app.Ingredient import Ingredient
from app.PlayerState import PlayerState

P1, P2, BOT = "p1", "p2", "bot"


def _move(turn, move, player, kind, **payload):
    return {
        "turn_number": turn,
        "move_number": move,
        "player_id": player,
        "action": {"type": kind, **payload},
    }


def _keys(moves):
    return [(m["turn_number"], m["move_number"]) for m in moves]


# ─── Which moves still stand ─────────────────────────────────────────────────


def test_an_undo_takes_back_the_last_move_only():
    moves = [
        _move(0, 1, P1, "draw_from_bag", drawn=["GIN"]),
        _move(0, 2, P1, "take_ingredients"),
        _move(1, 1, P2, "sell_cup"),
        _move(2, 1, P2, "undo", target_turn_number=1, target_move_number=1),
    ]
    assert _keys(undo.live_moves(moves)) == [(0, 1), (0, 2)]


def test_undos_one_after_another_walk_back_a_move_at_a_time():
    moves = [
        _move(0, 1, P1, "draw_from_bag", drawn=["GIN"]),
        _move(0, 2, P1, "take_ingredients"),
        _move(1, 1, P1, "undo", target_turn_number=0, target_move_number=2),
    ]
    target, taken_back = undo.plan_undo(moves, set())
    assert (target["turn_number"], target["move_number"]) == (0, 1)
    assert _keys(taken_back) == [(0, 1)]


def test_moves_made_after_an_undo_can_be_taken_back():
    moves = [
        _move(0, 1, P1, "draw_from_bag", drawn=["GIN"]),
        _move(1, 1, P1, "undo", target_turn_number=0, target_move_number=1),
        _move(2, 1, P1, "draw_from_bag", drawn=["GIN"]),
    ]
    target, _ = undo.plan_undo(moves, set())
    assert (target["turn_number"], target["move_number"]) == (2, 1)


def test_old_whole_turn_undos_take_back_every_move_of_the_turn():
    moves = [
        _move(0, 1, P1, "take_ingredients"),
        _move(1, 1, P2, "draw_from_bag", drawn=["GIN"]),
        _move(1, 2, P2, "take_ingredients"),
        _move(2, 1, P1, "undo", target_turn_number=1),
    ]
    assert _keys(undo.live_moves(moves)) == [(0, 1)]


def test_nothing_to_take_back_once_every_move_is_undone():
    moves = [
        _move(0, 1, P1, "take_ingredients"),
        _move(1, 1, P1, "undo", target_turn_number=0, target_move_number=1),
    ]
    assert undo.plan_undo(moves, set()) is None
    assert undo.plan_undo([], set()) is None


def test_bot_moves_are_taken_back_with_the_last_move_a_person_made():
    moves = [
        _move(0, 1, P1, "draw_from_bag", drawn=["GIN"]),
        _move(0, 2, P1, "take_ingredients"),
        _move(1, 1, BOT, "draw_from_bag", drawn=["RUM"]),
        _move(1, 2, BOT, "take_ingredients"),
    ]
    target, taken_back = undo.plan_undo(moves, {BOT})
    assert (target["turn_number"], target["move_number"]) == (0, 2)
    assert _keys(taken_back) == [(0, 2), (1, 1), (1, 2)]


def test_only_bot_moves_means_nothing_to_take_back():
    moves = [_move(0, 1, BOT, "take_ingredients")]
    assert undo.plan_undo(moves, {BOT}) is None


# ─── What the bag hands out again ────────────────────────────────────────────


def test_blind_draws_of_a_move():
    assert undo.blind_draws({"type": "draw_from_bag", "drawn": ["GIN", "COLA"]}) == [
        "GIN",
        "COLA",
    ]
    taken = [
        {"ingredient": "RUM", "source": "bag"},
        {"ingredient": "SODA", "source": "display"},
    ]
    assert undo.blind_draws({"type": "take_ingredients", "taken": taken}) == ["RUM"]
    assert undo.blind_draws({"type": "sell_cup"}) == []


def test_redraws_inside_the_turn_are_the_draws_taken_back_then_what_was_to_come():
    taken_back = [
        _move(0, 1, P1, "draw_from_bag", drawn=["GIN"]),
        _move(
            0, 2, P1, "take_ingredients", taken=[{"ingredient": "RUM", "source": "bag"}]
        ),
    ]
    current = {"player_turn": P1, "bag_redraws": ["VODKA"]}
    assert undo.redraws(taken_back, current, {"bag_redraws": []}) == [
        "GIN",
        "RUM",
        "VODKA",
    ]


def test_redraws_leave_out_a_later_turn():
    taken_back = [
        _move(
            0, 2, P1, "take_ingredients", taken=[{"ingredient": "RUM", "source": "bag"}]
        ),
        _move(1, 1, BOT, "draw_from_bag", drawn=["GIN"]),
    ]
    current = {"player_turn": P1, "bag_redraws": ["VODKA"]}
    assert undo.redraws(taken_back, current, {"bag_redraws": []}) == ["RUM"]


def test_redraws_back_past_the_end_of_a_turn_keep_what_was_still_to_come():
    # P1 drew GIN of the remembered GIN, RUM, then ended their turn (P2 is up)
    taken_back = [_move(0, 3, P1, "draw_from_bag", drawn=["GIN"])]
    current = {"player_turn": P2, "bag_redraws": []}
    restored = {"bag_redraws": ["GIN", "RUM"]}
    assert undo.redraws(taken_back, current, restored) == ["GIN", "RUM"]


# ─── The bag ─────────────────────────────────────────────────────────────────


def _game():
    pids = [uuid4(), uuid4()]
    gs = GameState(
        winner=None,
        bag_contents=[Ingredient.COLA] * 10 + [Ingredient.GIN, Ingredient.RUM],
        player_states={pid: PlayerState.new_player(pid) for pid in pids},
        player_turn=pids[0],
        open_display=[Ingredient.SODA] * 5,
        turn_order=list(pids),
    )
    return gs, pids


def test_a_blind_draw_hands_out_the_remembered_draws_first():
    gs, pids = _game()
    gs.bag_redraws = [Ingredient.RUM, Ingredient.GIN]
    gs, payload = actions.draw_from_bag(gs, pids[0], 2)
    assert payload["drawn"] == ["RUM", "GIN"]
    assert gs.bag_redraws == []
    assert Ingredient.RUM not in gs.bag_contents
    assert Ingredient.GIN not in gs.bag_contents


def test_a_remembered_draw_no_longer_in_the_bag_is_skipped():
    gs, pids = _game()
    gs.bag_contents = [Ingredient.COLA] * 3
    gs.bag_redraws = [Ingredient.RUM]
    gs, payload = actions.draw_from_bag(gs, pids[0], 1)
    assert payload["drawn"] == ["COLA"]


def test_remembered_draws_survive_a_save_and_end_with_the_turn():
    gs, pids = _game()
    gs.bag_redraws = [Ingredient.RUM]
    gs = GameState.from_dict(gs.to_dict())
    assert gs.bag_redraws == [Ingredient.RUM]
    actions._advance_turn(gs)
    assert gs.bag_redraws == []

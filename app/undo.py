"""Undo: taking back moves, one at a time.

An undo takes back the latest move nobody has taken back yet, so undoing
again and again walks back through the game a move at a time. Bots don't
ask for their moves back: an undo takes back the latest move a person made,
with any bot moves made since.

The move history keeps every move, taken back or not, with an ``undo`` move
for each undo. ``live_moves`` works out which moves still stand.

Blind bag draws are random, so an undo remembers what the taken-back moves
drew (``redraws``, kept in ``GameState.bag_redraws``): a player who makes
the move again gets what they got. That lasts until the turn ends.
"""

from collections.abc import Collection


def _key(move: dict) -> tuple[int, int]:
    return (move["turn_number"], move.get("move_number") or 1)


def undo_target_key(action: dict) -> tuple[int, int]:
    """The (turn_number, move_number) an undo move took the game back to.

    Undos from before moves could be taken back one at a time took back a
    whole turn: back to its first move."""
    return (action["target_turn_number"], action.get("target_move_number") or 1)


def live_moves(moves: list[dict]) -> list[dict]:
    """The moves still standing, oldest first: every move but undos and the
    moves they took back. ``moves`` is the history in order."""
    stack: list[dict] = []
    for move in moves:
        action = move.get("action") or {}
        if action.get("type") == "undo":
            target = undo_target_key(action)
            while stack and _key(stack[-1]) >= target:
                stack.pop()
        else:
            stack.append(move)
    return stack


def plan_undo(
    moves: list[dict], bot_ids: Collection[str]
) -> tuple[dict, list[dict]] | None:
    """What an undo now would take back: ``(target, taken_back)``.

    ``target`` is the latest standing move made by a person (not a bot);
    the game goes back to just before it. ``taken_back`` is it and every
    standing move since (bot moves), oldest first. None if there's nothing
    to take back.
    """
    stack = live_moves(moves)
    taken_back: list[dict] = []
    while stack and str(stack[-1]["player_id"]) in bot_ids:
        taken_back.insert(0, stack.pop())
    if not stack:
        return None
    target = stack.pop()
    return target, [target, *taken_back]


def blind_draws(action: dict) -> list[str]:
    """The tokens a move drew blind from the bag, in order."""
    kind = action.get("type")
    if kind == "draw_from_bag":
        return list(action.get("drawn") or [])
    if kind == "take_ingredients":
        return [
            t["ingredient"]
            for t in action.get("taken") or []
            if t.get("source") == "bag" and t.get("ingredient")
        ]
    return []


def redraws(
    taken_back: list[dict],
    current_state: dict,
    restored_state: dict,
) -> list[str]:
    """What the bag hands out next once the undo has put the game back.

    The blind draws the target's player made in the moves taken back, then,
    if the undo stays inside their turn, what the bag was going to hand out
    next anyway (a previous undo's redraws not yet drawn again). Draws in a
    later turn are left out: that turn hasn't started in the restored game,
    and its draws will be random when it does.
    """
    player = str(taken_back[0]["player_id"])
    drawn: list[str] = []
    same_turn = True
    for move in taken_back:
        if str(move["player_id"]) != player:
            same_turn = False
            break
        drawn.extend(blind_draws(move.get("action") or {}))
    if same_turn and str(current_state.get("player_turn")) == player:
        return drawn + list(current_state.get("bag_redraws") or [])
    # The undo goes back past the end of the player's turn: what they drew
    # comes out again, then what was still to come out from an earlier undo.
    stored = list(restored_state.get("bag_redraws") or [])
    if stored[: len(drawn)] == drawn:
        return drawn + stored[len(drawn) :]
    return drawn

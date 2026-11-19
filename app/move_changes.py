"""What a move changed on the table, kept with the move for the history.

Each move's record gets a ``changes`` entry (only when something changed):

    {
        "cards_out": [{"name": ..., "card_type": ..., "row": 3}, ...],
        "cards_in":  [{"name": ..., "card_type": ..., "row": 3}, ...],
        "players": {"<player_id>": {"drunk": [before, after],
                                     "points": [before, after]}, ...},
    }

``cards_out`` are cards that left the rows on the table (claimed, served,
cleared or swiped); ``cards_in`` the cards dealt in to replace them.
``players`` lists only players whose drunk level or points changed, and
only the values that did.
"""

from app.GameState import GameState


def _row_cards(gs: GameState) -> dict[str, tuple[int, dict]]:
    return {
        card.id: (row.position, card.to_dict())
        for row in gs.card_rows
        for card in row.cards
    }


def _brief(card: dict, row: int) -> dict:
    return {
        "name": card.get("name", ""),
        "card_type": card.get("card_type"),
        "row": row,
    }


def move_changes(before: GameState, after: GameState) -> dict:
    """The cards, drunk levels and points a move changed (empty if none)."""
    was, now = _row_cards(before), _row_cards(after)
    changes: dict = {}
    out = [_brief(c, row) for cid, (row, c) in was.items() if cid not in now]
    dealt = [_brief(c, row) for cid, (row, c) in now.items() if cid not in was]
    if out:
        changes["cards_out"] = out
    if dealt:
        changes["cards_in"] = dealt

    players: dict = {}
    for pid, ps in after.player_states.items():
        old = before.player_states.get(pid)
        if old is None:
            continue
        diff = {}
        if old.drunk_level != ps.drunk_level:
            diff["drunk"] = [old.drunk_level, ps.drunk_level]
        if old.points != ps.points:
            diff["points"] = [old.points, ps.points]
        if diff:
            players[str(pid)] = diff
    if players:
        changes["players"] = players
    return changes

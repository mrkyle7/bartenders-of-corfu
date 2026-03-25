"""Concise game state display for debugging play-test runs."""

from uuid import UUID

from app.GameState import GameState
from app.actions import _MIXERS, _SPIRITS

from playtesting.valid_actions import Action


def format_game_state(
    gs: GameState, strategy_names: dict[UUID, str] | None = None
) -> str:
    """Return a concise multi-line summary of the game state."""
    lines: list[str] = []
    sn = strategy_names or {}

    current_name = (
        sn.get(gs.player_turn, str(gs.player_turn)[:8]) if gs.player_turn else "?"
    )
    lines.append(f"--- Turn {gs.turn_number} | Current: {current_name} ---")

    # Bag and display
    bag_spirits = sum(1 for i in gs.bag_contents if i in _SPIRITS)
    bag_mixers = sum(1 for i in gs.bag_contents if i in _MIXERS)
    bag_specials = sum(1 for i in gs.bag_contents if i.name == "SPECIAL")
    lines.append(
        f"  Bag: {len(gs.bag_contents)} ({bag_spirits}S {bag_mixers}M {bag_specials}X) | "
        f"Display: {', '.join(i.name for i in gs.open_display)}"
    )

    # Card rows
    for row in gs.card_rows:
        cards_str = ", ".join(
            f"{c.name}({c.card_type[0].upper()}/{c.spirit_type or c.mixer_type or '?'})"
            for c in row.cards
        )
        lines.append(f"  Row{row.position}: [{cards_str}]")

    deck_size = len(gs._deck_dicts) if gs._deck_dicts else 0
    discard_size = len(gs.discard) if gs.discard else 0
    lines.append(f"  Deck: {deck_size} | Discard: {discard_size}")

    # Winner
    if gs.winner:
        winner_name = sn.get(gs.winner, str(gs.winner)[:8])
        lines.append(f"  ** WINNER: {winner_name} **")

    # Players
    for pid in gs.turn_order:
        ps = gs.player_states[pid]
        name = sn.get(pid, str(pid)[:8])
        status = ps.status.upper()
        marker = " <<" if pid == gs.player_turn else ""

        bladder_str = f"{len(ps.bladder)}/{ps.bladder_capacity}"
        lines.append(
            f"  {name} [{status}] {ps.points}pts "
            f"drunk:{ps.drunk_level} bladder:{bladder_str} "
            f"wc:{ps.toilet_tokens} karaoke:{ps.karaoke_cards_claimed}{marker}"
        )

        # Cups
        for ci in (0, 1):
            cup = ps.cups[ci]
            ing_str = (
                ", ".join(i.name for i in cup.ingredients)
                if cup.ingredients
                else "empty"
            )
            doubler = " [DOUBLER]" if cup.has_cup_doubler else ""
            lines.append(f"    Cup{ci}: [{ing_str}]{doubler}")

        # Bladder contents (compact)
        if ps.bladder:
            from collections import Counter

            bc = Counter(i.name for i in ps.bladder)
            bladder_detail = " ".join(f"{n}x{c}" for n, c in bc.items())
            lines.append(f"    Bladder: {bladder_detail}")

        # Cards
        if ps.cards:
            card_strs = []
            for cd in ps.cards:
                ct = cd.get("card_type", "?")
                name_str = cd.get("name", "?")
                stored = cd.get("stored_spirits", [])
                if stored:
                    card_strs.append(f"{name_str}({ct}, {len(stored)} stored)")
                else:
                    card_strs.append(f"{name_str}({ct})")
            lines.append(f"    Cards: {', '.join(card_strs)}")

        # Specials
        if ps.special_ingredients:
            lines.append(f"    Specials: {', '.join(ps.special_ingredients)}")

    return "\n".join(lines)


def format_action(action: Action) -> str:
    """Return a one-line description of an action."""
    if action.description:
        return action.description
    return f"{action.action_type}({action.params})"


def format_result(result) -> str:
    """Format a GameResult for display."""
    lines: list[str] = []
    lines.append(f"=== Game Over (turn {result.turn_count}) ===")
    lines.append(f"  Winner: {result.winner_strategy} ({result.reason})")

    for pid, pr in result.player_results.items():
        status = pr.status.upper()
        lines.append(
            f"  {pr.strategy_name} [{status}] {pr.points}pts karaoke:{pr.karaoke_cards}"
        )

    return "\n".join(lines)

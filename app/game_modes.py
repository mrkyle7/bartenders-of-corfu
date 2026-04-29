"""Optional rule variations a host can enable in the lobby.

To add a new mode:
  1. Add a new value to ``GameMode``.
  2. Have action / bot / UI code check ``gs.has_mode("...")``.
  3. Surface the toggle in the lobby UI.

Modes are locked once the game starts. The chosen modes travel with the
game state (``GameState.game_modes``) so actions and bots can read them
without an extra DB lookup.
"""

from enum import Enum


class GameMode(str, Enum):
    """Optional rule variations selected in the lobby."""

    SELL_BOTH_CUPS = "sell_both_cups"


VALID_GAME_MODES: frozenset[str] = frozenset(m.value for m in GameMode)


def normalise_modes(modes: list[str] | None) -> list[str]:
    """Validate and de-duplicate mode strings, preserving order.

    Raises ValueError if any value is not a recognised mode.
    """
    if not modes:
        return []
    seen: set[str] = set()
    result: list[str] = []
    for m in modes:
        if not isinstance(m, str):
            raise ValueError(f"Game mode must be a string, got {type(m).__name__}")
        if m not in VALID_GAME_MODES:
            raise ValueError(f"Unknown game mode: {m}")
        if m in seen:
            continue
        seen.add(m)
        result.append(m)
    return result

"""Optional rule variations a host can enable in the lobby.

There are none at the moment. The three there were have been settled:
selling both cups in one action and claiming a card as a free action are
now standard rules, and re-rolling specials is no longer part of the game.
Games saved with those modes still load; the modes are simply ignored.

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


# Former modes, kept so old saved games are recognised.
RETIRED_GAME_MODES: frozenset[str] = frozenset(
    {"sell_both_cups", "claim_card_free_action", "reroll_specials_free_action"}
)

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

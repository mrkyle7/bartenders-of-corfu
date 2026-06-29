"""Guards against the production bug where ml-backed bots silently fell back to
random because ml/ wasn't shipped and the registration error was swallowed.

Invariants:
- importing ml registers the ml-backed strategies and they are instantiable;
- playtesting.strategy must NOT import ml (keeps the dependency one-directional
  and prevents reintroducing the silent circular-import registration hook).

Pure tests — no Supabase required.
"""

import subprocess
import sys


def test_import_ml_registers_ml_bots():
    import ml  # noqa: F401

    from playtesting.strategy import STRATEGY_CLASSES

    assert "mcts" in STRATEGY_CLASSES
    assert "lookahead" in STRATEGY_CLASSES


def test_all_registered_strategies_are_instantiable():
    import ml  # noqa: F401

    from playtesting.strategy import STRATEGY_CLASSES

    for name, cls in STRATEGY_CLASSES.items():
        assert cls() is not None, f"{name} failed to instantiate"


def test_core_production_bots_present_after_ml_import():
    import ml  # noqa: F401

    from playtesting.strategy import STRATEGY_CLASSES

    for required in ("mastermind", "mcts", "lookahead"):
        assert required in STRATEGY_CLASSES


def test_playtesting_strategy_does_not_import_ml():
    """In a fresh interpreter, importing playtesting.strategy must not pull in
    ml — otherwise we'd be back to the circular import that hid load failures."""
    code = (
        "import sys; import playtesting.strategy as s; "
        "assert 'ml' not in sys.modules, 'playtesting.strategy must not import ml'; "
        "assert 'mcts' not in s.STRATEGY_CLASSES, 'ml bots should not register via playtesting'; "
        "print('ok')"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout

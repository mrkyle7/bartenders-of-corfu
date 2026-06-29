"""ML module: Gymnasium environment and the MCTS / lookahead bots.

Importing this package registers the ml-backed bot strategies (``mcts``,
``lookahead``) into ``playtesting.strategy.STRATEGY_CLASSES`` as an import side
effect. This is deliberately NOT wrapped in a try/except: if a packaging or
deployment error drops these modules (as happened when ``ml/`` was missing from
the Docker image), ``import ml`` must fail loudly so the app refuses to start —
rather than silently downgrading every bot to random moves.
"""

# mcts first; lookahead depends on it. Importing each module self-registers it.
from ml import lookahead, mcts  # noqa: F401

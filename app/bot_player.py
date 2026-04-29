"""BotPlayer: executes bot turns using playtesting strategies through the GameManager.

When a game action results in the turn advancing to a bot player, this module
picks a strategy, computes valid actions, and executes them via GameManager
(which handles persistence and move recording).
"""

import logging
from uuid import UUID

from app.db import db
from app.game import Game, GameException

from playtesting.strategy import STRATEGY_CLASSES, Strategy
from playtesting.valid_actions import Action, get_valid_actions

logger = logging.getLogger(__name__)

MAX_BOT_TURNS = 20  # safety limit per call to prevent infinite bot loops
MAX_FREE_ACTIONS_PER_TURN = 20
MAX_RETRIES = 3


def _get_strategy(strategy_name: str) -> Strategy:
    cls = STRATEGY_CLASSES.get(strategy_name)
    if cls is None:
        cls = STRATEGY_CLASSES["random"]
    return cls()


def get_bot_ids_for_game(player_ids: set[UUID]) -> dict[UUID, str]:
    """Return {bot_id: strategy_name} for all bot players in the game."""
    bots = db.get_bot_users_by_ids(player_ids)
    return {bot.id: (bot.bot_strategy or "random") for bot in bots}


def process_bot_turns(game_manager, game_id: UUID) -> None:
    """Check if the current player is a bot and execute their turns.

    Loops to handle consecutive bot players. Stops when a human player's
    turn arrives, the game ends, or a safety limit is hit.
    """
    for _ in range(MAX_BOT_TURNS):
        game = db.get_game(game_id)
        if game is None or game.status.name != "STARTED":
            return

        gs = game.game_state
        if gs is None or gs.winner is not None:
            return

        current_player = gs.player_turn
        if current_player is None:
            return

        ps = gs.player_states.get(current_player)
        if ps is None or ps.is_eliminated:
            return

        # Check if current player is a bot
        bot_map = get_bot_ids_for_game(game.players)
        if current_player not in bot_map:
            return  # human player's turn

        strategy_name = bot_map[current_player]
        strategy = _get_strategy(strategy_name)

        logger.info(
            "Bot %s (%s) taking turn in game %s",
            current_player,
            strategy_name,
            game_id,
        )

        try:
            _execute_bot_turn(game_manager, game, current_player, strategy)
        except Exception:
            logger.exception(
                "Bot %s failed to take turn in game %s, skipping",
                current_player,
                game_id,
            )
            # Force-advance the turn to prevent the game from getting stuck
            _force_advance_turn(game_manager, game, current_player)


def _execute_bot_turn(
    game_manager, game: Game, player_id: UUID, strategy: Strategy
) -> None:
    """Execute a single complete bot turn (free actions + main action)."""
    gs = game.game_state

    # Free actions phase
    for _ in range(MAX_FREE_ACTIONS_PER_TURN):
        # Re-fetch game state since actions modify it
        game = db.get_game(game.id)
        gs = game.game_state
        if gs.winner is not None:
            return

        all_actions = get_valid_actions(gs, player_id)
        free_actions = [a for a in all_actions if a.is_free]
        if not free_actions:
            break

        chosen = strategy.choose_free_action(gs, player_id, free_actions)
        if chosen is None:
            break

        logger.debug("Bot %s free action: %s", player_id, chosen.action_type)
        try:
            _execute_action(game_manager, game, player_id, chosen, strategy)
        except GameException as e:
            logger.debug("Bot free action failed: %s", e)
            break

    # Main action phase
    for attempt in range(MAX_RETRIES):
        game = db.get_game(game.id)
        gs = game.game_state
        if gs.winner is not None:
            return

        all_actions = get_valid_actions(gs, player_id)
        turn_actions = [a for a in all_actions if not a.is_free]

        if not turn_actions:
            logger.debug("Bot %s has no valid actions, skipping turn", player_id)
            _force_advance_turn(game_manager, game, player_id)
            return

        chosen = strategy.choose_action(gs, player_id, turn_actions)
        logger.debug("Bot %s main action: %s", player_id, chosen.action_type)

        try:
            _execute_action(game_manager, game, player_id, chosen, strategy)
            return
        except GameException as e:
            logger.debug("Bot main action retry %d: %s", attempt + 1, e)
            continue

    # All retries exhausted
    logger.warning("Bot %s exhausted retries, skipping turn", player_id)
    game = db.get_game(game.id)
    _force_advance_turn(game_manager, game, player_id)


def _execute_action(
    game_manager, game: Game, player_id: UUID, action: Action, strategy: Strategy
) -> None:
    """Execute a single action through the GameManager."""
    t = action.action_type
    p = action.params

    if t == "take_ingredients":
        _execute_take(game_manager, game, player_id, strategy)
    elif t == "sell_cup":
        game_manager.sell_cup(
            game,
            player_id,
            p["cup_index"],
            p.get("declared_specials", []),
            additional_cups=p.get("additional_cups"),
        )
    elif t == "drink_cup":
        game_manager.drink_cup(game, player_id, p["cup_index"])
    elif t == "go_for_a_wee":
        game_manager.go_for_a_wee(game, player_id)
    elif t == "claim_card":
        game_manager.claim_card(
            game,
            player_id,
            p["card_id"],
            cup_index=p.get("cup_index"),
            spirit_type=p.get("spirit_type"),
        )
    elif t == "drink_stored_spirit":
        game_manager.drink_stored_spirit(
            game, player_id, p["store_card_index"], p["count"]
        )
    elif t == "use_stored_spirit":
        game_manager.use_stored_spirit(
            game, player_id, p["store_card_index"], p["cup_index"]
        )
    elif t == "refresh_card_row":
        game_manager.refresh_card_row(game, player_id, p["row_position"])
    else:
        raise GameException(f"Unknown action type: {t}", status_code=500)


def _execute_take(
    game_manager, game: Game, player_id: UUID, strategy: Strategy
) -> None:
    """Handle the multi-step take_ingredients flow for a bot."""
    gs = game.game_state
    ps = gs.player_states[player_id]
    take_count = ps.take_count
    remaining = take_count - gs.ingredients_taken_this_turn

    # Phase 1: display picks
    display_assignments = strategy.choose_take_assignments(gs, player_id, remaining)

    if display_assignments:
        new_state, payload = game_manager.take_ingredients(
            game, player_id, display_assignments
        )
        if payload.get("turn_complete", False):
            return
        # Re-fetch game after state change
        game = db.get_game(game.id)

    # Phase 2: draw from bag in batches
    batch_limit = 10
    while batch_limit > 0:
        batch_limit -= 1
        game = db.get_game(game.id)
        gs = game.game_state
        ps = gs.player_states[player_id]
        remaining = ps.take_count - gs.ingredients_taken_this_turn
        if remaining <= 0:
            break

        bag_count = min(remaining, len(gs.bag_contents))
        if bag_count <= 0:
            break

        new_state, draw_payload = game_manager.draw_from_bag(game, player_id, bag_count)
        # Re-fetch game after draw
        game = db.get_game(game.id)
        gs = game.game_state

        drawn = gs.bag_draw_pending[:]
        pending_assignments = strategy.choose_pending_assignments(gs, player_id, drawn)

        new_state, payload = game_manager.take_ingredients(
            game, player_id, pending_assignments
        )
        if payload.get("turn_complete", False):
            return
        game = db.get_game(game.id)


def _force_advance_turn(game_manager, game: Game, player_id: UUID) -> None:
    """Force-advance the turn when a bot can't act."""
    from app.actions import _advance_turn, _deep_copy_state

    gs = _deep_copy_state(game.game_state)
    gs.turn_number += 1
    _advance_turn(gs)
    game_manager._apply_action(
        game, player_id, "skip_turn", gs, {"reason": "no_valid_actions"}
    )

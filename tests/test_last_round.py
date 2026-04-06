"""Unit tests for the 40-point last-round rule.

These tests exercise the actions module directly without needing Supabase,
by constructing GameState objects in memory.
"""

from uuid import uuid4

from app.GameState import GameState
from app.Ingredient import Ingredient
from app.PlayerState import PlayerState
from app import actions


def _make_game(num_players=2, points=None):
    """Build a minimal started GameState for testing last-round logic.

    Returns (gs, player_ids) where player_ids[0] is the starting player.
    """
    pids = [uuid4() for _ in range(num_players)]
    player_states = {}
    for i, pid in enumerate(pids):
        ps = PlayerState.new_player(pid)
        if points and i < len(points):
            ps.points = points[i]
        player_states[pid] = ps
    gs = GameState(
        winner=None,
        bag_contents=[Ingredient.COLA] * 20,
        player_states=player_states,
        player_turn=pids[0],
        open_display=[Ingredient.COLA] * 5,
        turn_order=list(pids),
        turn_number=0,
    )
    return gs, pids


def _setup_cup_for_liet(ps):
    """Set up cup 0 with Long Island Iced Tea ingredients and specials."""
    ps.cups[0].ingredients = [
        Ingredient.GIN,
        Ingredient.VODKA,
        Ingredient.TEQUILA,
        Ingredient.RUM,
        Ingredient.COLA,
    ]
    ps.special_ingredients = ["sugar", "lemon"]


def _setup_cup_single_spirit(ps):
    """Set up cup 0 with a simple 1-point drink."""
    ps.cups[0].ingredients = [Ingredient.VODKA, Ingredient.COLA]
    ps.special_ingredients = []


class TestLastRoundTriggered:
    """Reaching 40 points should trigger last_round, not end the game."""

    def test_sell_cup_triggers_last_round(self):
        gs, pids = _make_game(2, points=[37, 0])
        _setup_cup_for_liet(gs.player_states[pids[0]])
        gs, _ = actions.sell_cup(gs, pids[0], 0, ["sugar", "lemon"])
        assert gs.last_round is True
        assert gs.winner is None  # Not instant win
        assert gs.player_turn == pids[1]  # Next player's turn

    def test_sell_cup_below_40_no_last_round(self):
        gs, pids = _make_game(2, points=[0, 0])
        _setup_cup_single_spirit(gs.player_states[pids[0]])
        gs, _ = actions.sell_cup(gs, pids[0], 0, [])
        assert gs.last_round is False
        assert gs.winner is None


class TestLastRoundCompletion:
    """Game ends when the round completes (turn cycles back to starting player)."""

    def test_starting_player_triggers_others_get_turns(self):
        """P1 (starting) hits 40 → P2 still gets a turn → then game ends."""
        gs, pids = _make_game(2, points=[37, 0])
        p1, p2 = pids

        # P1 sells LIET (15 pts) → 52 pts → last round triggered
        _setup_cup_for_liet(gs.player_states[p1])
        gs, _ = actions.sell_cup(gs, p1, 0, ["sugar", "lemon"])
        assert gs.last_round is True
        assert gs.winner is None
        assert gs.player_turn == p2

        # P2 takes a non-scoring action (wee) — bladder must have something
        gs.player_states[p2].bladder = [Ingredient.COLA]
        gs, _ = actions.go_for_a_wee(gs, p2)

        # Now turn wraps back to P1 → round complete → game ends
        assert gs.winner == p1  # P1 has 52, P2 has 0

    def test_last_player_triggers_game_ends_immediately(self):
        """P2 (last in order) hits 40 → next is P1 (round start) → game ends."""
        gs, pids = _make_game(2, points=[0, 37])
        p1, p2 = pids

        # P1 does a non-scoring action first
        gs.player_states[p1].bladder = [Ingredient.COLA]
        gs, _ = actions.go_for_a_wee(gs, p1)
        assert gs.player_turn == p2

        # P2 sells LIET → 52 pts → last round + immediately complete
        _setup_cup_for_liet(gs.player_states[p2])
        gs, _ = actions.sell_cup(gs, p2, 0, ["sugar", "lemon"])
        assert gs.last_round is True
        assert gs.winner == p2  # Game ends immediately

    def test_three_players_middle_triggers(self):
        """3 players [A,B,C]. B hits 40 → C gets a turn → game ends."""
        gs, pids = _make_game(3, points=[0, 37, 0])
        a, b, c = pids

        # A takes non-scoring action
        gs.player_states[a].bladder = [Ingredient.COLA]
        gs, _ = actions.go_for_a_wee(gs, a)
        assert gs.player_turn == b

        # B sells LIET → 52 pts → last round triggered
        _setup_cup_for_liet(gs.player_states[b])
        gs, _ = actions.sell_cup(gs, b, 0, ["sugar", "lemon"])
        assert gs.last_round is True
        assert gs.winner is None
        assert gs.player_turn == c

        # C takes non-scoring action → turn wraps to A → round complete
        gs.player_states[c].bladder = [Ingredient.COLA]
        gs, _ = actions.go_for_a_wee(gs, c)
        assert gs.winner == b  # B has 52, highest


class TestLastRoundHighestPointsWins:
    """During the last round, other players can overtake the trigger player."""

    def test_another_player_scores_higher(self):
        gs, pids = _make_game(2, points=[37, 38])
        p1, p2 = pids

        # P1 sells LIET (15pts) → 52 pts → last round triggered
        _setup_cup_for_liet(gs.player_states[p1])
        gs, _ = actions.sell_cup(gs, p1, 0, ["sugar", "lemon"])
        assert gs.last_round is True
        assert gs.player_turn == p2

        # P2 also sells LIET (15pts) → 53 pts → round complete, P2 wins
        _setup_cup_for_liet(gs.player_states[p2])
        gs, _ = actions.sell_cup(gs, p2, 0, ["sugar", "lemon"])
        assert gs.winner == p2  # P2 has 53, P1 has 52


class TestKaraokeOverridesLastRound:
    """Karaoke wins are instant and override the last-round system."""

    def test_karaoke_still_instant_win(self):
        gs, pids = _make_game(2, points=[0, 0])
        p1 = pids[0]
        ps1 = gs.player_states[p1]
        ps1.karaoke_cards_claimed = 2

        # Set up a claimable karaoke card
        from app.card import Card, CardRow

        karaoke_card = Card(
            id=str(uuid4()),
            card_type="karaoke",
            name="Test Karaoke",
            spirit_type="RUM",
        )
        gs.card_rows = [
            CardRow(position=1, cards=[karaoke_card]),
            CardRow(position=2, cards=[]),
            CardRow(position=3, cards=[]),
        ]
        # Give player 3 RUM in bladder
        ps1.bladder = [Ingredient.RUM, Ingredient.RUM, Ingredient.RUM]

        gs, _ = actions.claim_card(gs, p1, karaoke_card.id)
        assert gs.winner == p1  # Instant win
        assert gs.last_round is False  # Never triggered

    def test_karaoke_during_last_round_overrides(self):
        gs, pids = _make_game(2, points=[37, 5])
        p1, p2 = pids

        # P1 sells LIET → triggers last round
        _setup_cup_for_liet(gs.player_states[p1])
        gs, _ = actions.sell_cup(gs, p1, 0, ["sugar", "lemon"])
        assert gs.last_round is True
        assert gs.player_turn == p2

        # P2 claims 3rd karaoke card → instant win even though P1 has more points
        ps2 = gs.player_states[p2]
        ps2.karaoke_cards_claimed = 2
        from app.card import Card, CardRow

        karaoke_card = Card(
            id=str(uuid4()),
            card_type="karaoke",
            name="Test Karaoke",
            spirit_type="RUM",
        )
        gs.card_rows = [
            CardRow(position=1, cards=[karaoke_card]),
            CardRow(position=2, cards=[]),
            CardRow(position=3, cards=[]),
        ]
        ps2.bladder = [Ingredient.RUM, Ingredient.RUM, Ingredient.RUM]
        gs, _ = actions.claim_card(gs, p2, karaoke_card.id)
        assert gs.winner == p2  # P2 wins with karaoke despite P1 having 52 pts


class TestLastRoundWithElimination:
    """Eliminated players are skipped during the last round."""

    def test_eliminated_starting_player(self):
        """If starting player is eliminated, round end is when turn reaches
        the first active player in turn order."""
        gs, pids = _make_game(3, points=[0, 37, 0])
        a, b, c = pids

        # Eliminate player A
        gs.player_states[a].status = "hospitalised"
        gs.player_turn = b  # Skip A

        # B sells LIET → triggers last round
        _setup_cup_for_liet(gs.player_states[b])
        gs, _ = actions.sell_cup(gs, b, 0, ["sugar", "lemon"])
        assert gs.last_round is True
        assert gs.player_turn == c

        # C takes action → next active player is B (A eliminated)
        # B is the effective round start → round complete
        gs.player_states[c].bladder = [Ingredient.COLA]
        gs, _ = actions.go_for_a_wee(gs, c)
        assert gs.winner == b  # B has 52 pts


class TestGameStateSerialization:
    """last_round persists through serialization."""

    def test_last_round_serialization(self):
        gs, _ = _make_game(2)
        gs.last_round = True
        d = gs.to_dict()
        assert d["last_round"] is True
        restored = GameState.from_dict(d)
        assert restored.last_round is True

    def test_last_round_defaults_false(self):
        gs, _ = _make_game(2)
        d = gs.to_dict()
        del d["last_round"]
        restored = GameState.from_dict(d)
        assert restored.last_round is False

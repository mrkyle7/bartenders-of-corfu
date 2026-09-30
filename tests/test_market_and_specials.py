"""The card market, orders, free actions, specials and target score.

Pure engine tests (no Supabase): they drive app.actions directly.
"""

import uuid

import pytest

from app import actions
from app.actions import (
    claim_card,
    end_turn,
    go_for_a_wee,
    refresh_card_row,
    reroll_specials,
    sell_cup,
    take_ingredients,
)
from app.card import Card, CardRow
from app.game import GameException
from app.GameState import GameState, score_to_win
from app.Ingredient import Ingredient, SpecialType
from app.PlayerState import Cup


def _game(players: int = 2) -> GameState:
    return GameState.start_game([uuid.uuid4() for _ in range(players)])


def _me(gs: GameState):
    pid = gs.player_turn
    return pid, gs.player_states[pid]


def _row(gs: GameState, position: int) -> CardRow:
    return next(r for r in gs.card_rows if r.position == position)


def _order(name: str, drink: str, bonus: int, **kw) -> Card:
    return Card(
        id=f"o-{name}", card_type="order", name=name, drink=drink, bonus=bonus, **kw
    )


# ─── Setting up ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("players,tokens,target", [(2, 4, 40), (3, 5, 35), (4, 6, 30)])
def test_setup_scales_with_players(players, tokens, target):
    gs = _game(players)
    in_play = gs.bag_contents + gs.open_display
    assert in_play.count(Ingredient.SPECIAL) == tokens
    assert gs.score_to_win == target == score_to_win(players)
    assert gs.to_dict()["score_to_win"] == target


def test_market_has_every_karaoke_card_then_orders_then_abilities():
    gs = _game()
    karaoke, orders, abilities = (_row(gs, p).cards for p in (1, 2, 3))
    assert len(karaoke) == 5 and all(c.card_type == "karaoke" for c in karaoke)
    assert len(orders) == 3 and all(c.card_type == "order" for c in orders)
    assert len(abilities) == 3
    assert all(c.card_type not in ("karaoke", "order") for c in abilities)
    # 19 ability cards (no Cocktail Shaker) and 18 orders in all
    assert len(gs._deck_dicts) + len(abilities) == 19
    assert len(gs.order_deck) + len(orders) == 18
    names = {c["name"] for c in gs._deck_dicts} | {c.name for c in abilities}
    assert "Cocktail Shaker" not in names


def test_display_specials_line_up_with_the_display():
    gs = _game(4)
    assert len(gs.display_specials) == len(gs.open_display)
    for token, face in zip(gs.open_display, gs.display_specials):
        assert (face is not None) == (token == Ingredient.SPECIAL)


# ─── Claiming cards is a free action, once a turn ───────────────────────────


def test_claiming_is_free_and_leaves_the_main_action():
    gs = _game()
    pid, ps = _me(gs)
    ps.bladder = [Ingredient.RUM] * 3
    sea_shanty = next(c for c in _row(gs, 1).cards if c.spirit_type == "RUM")

    new, payload = claim_card(gs, pid, sea_shanty.id)

    assert payload["is_free_action"] is True
    assert new.player_turn == pid
    assert new.main_action_taken_this_turn is False
    # The karaoke row isn't refilled
    assert len(_row(new, 1).cards) == 4


def test_only_one_claim_a_turn():
    gs = _game()
    pid, ps = _me(gs)
    ps.bladder = [Ingredient.RUM] * 3 + [Ingredient.GIN] * 3
    karaoke = _row(gs, 1).cards
    rum = next(c for c in karaoke if c.spirit_type == "RUM")
    gin = next(c for c in karaoke if c.spirit_type == "GIN")
    gs, _ = claim_card(gs, pid, rum.id)
    with pytest.raises(GameException) as exc:
        claim_card(gs, pid, gin.id)
    assert exc.value.status_code == 409


def test_claimed_ability_card_is_replaced_from_the_top_of_the_deck():
    gs = _game()
    pid, ps = _me(gs)
    store = Card(id="s1", card_type="store", name="Rum Store", spirit_type="RUM")
    _row(gs, 3).cards[0] = store
    top = gs._deck_dicts[0]["id"]
    ps.bladder = [Ingredient.RUM]
    new, _ = claim_card(gs, pid, "s1")
    assert top in [c.id for c in _row(new, 3).cards]


def test_orders_cannot_be_claimed():
    gs = _game()
    pid, _ = _me(gs)
    with pytest.raises(GameException):
        claim_card(gs, pid, _row(gs, 2).cards[0].id)


def test_turn_waits_while_a_claim_is_possible_then_ends_after_it():
    gs = _game()
    pid, ps = _me(gs)
    ps.bladder = [Ingredient.RUM] * 3
    ps.cups[0] = Cup(ingredients=[Ingredient.VODKA, Ingredient.COLA])
    gs.card_rows[1].cards = []  # no orders to muddy the sale
    gs, _ = sell_cup(gs, pid, 0, [])
    # Main action done, but Sea Shanty is affordable: the turn stays open
    assert gs.player_turn == pid
    sea_shanty = next(c for c in _row(gs, 1).cards if c.spirit_type == "RUM")
    gs, _ = claim_card(gs, pid, sea_shanty.id)
    assert gs.player_turn != pid


def test_turn_ends_straight_after_the_main_action_when_nothing_free_is_left():
    gs = _game()
    pid, ps = _me(gs)
    ps.bladder = [Ingredient.SODA]
    gs, _ = go_for_a_wee(gs, pid)
    assert gs.player_turn != pid


def test_end_turn_gives_up_a_possible_claim():
    gs = _game()
    pid, ps = _me(gs)
    ps.bladder = [Ingredient.RUM] * 3
    ps.cups[0] = Cup(ingredients=[Ingredient.VODKA, Ingredient.COLA])
    gs.card_rows[1].cards = []
    gs, _ = sell_cup(gs, pid, 0, [])
    gs, payload = end_turn(gs, pid)
    assert gs.player_turn != pid
    assert "claim_card" in payload["forfeited_free_actions"]


# ─── Orders ──────────────────────────────────────────────────────────────────


def test_serving_an_order_pays_its_bonus_and_rotates_it():
    gs = _game()
    pid, ps = _me(gs)
    order = _order("Rum and Cola", "simple", 2, spirit_type="RUM", mixer_type="COLA")
    _row(gs, 2).cards[0] = order
    ps.cups[0] = Cup(ingredients=[Ingredient.RUM, Ingredient.RUM, Ingredient.COLA])
    next_up = gs.order_deck[0]["id"]

    new, payload = sell_cup(gs, pid, 0, [])

    assert payload["points_earned"] == 3 + 2
    assert payload["orders"] == [{"name": "Rum and Cola", "bonus": 2}]
    assert new.order_deck[-1]["id"] == "o-Rum and Cola"
    assert next_up in [c.id for c in _row(new, 2).cards]


def test_order_bonus_is_not_doubled():
    gs = _game()
    pid, ps = _me(gs)
    _row(gs, 2).cards[0] = _order(
        "Vodka Tonic", "simple", 2, spirit_type="VODKA", mixer_type="TONIC"
    )
    ps.cups[0] = Cup(
        ingredients=[Ingredient.VODKA, Ingredient.TONIC], has_cup_doubler=True
    )
    _, payload = sell_cup(gs, pid, 0, [])
    assert payload["points_earned"] == 1 * 2 + 2


def test_cocktail_order_needs_that_cocktail():
    gs = _game()
    pid, ps = _me(gs)
    _row(gs, 2).cards[:] = [_order("Mojito", "cocktail", 4, cocktail="Mojito")]
    ps.special_ingredients = ["sugar"]
    ps.cups[0] = Cup(ingredients=[Ingredient.RUM, Ingredient.RUM, Ingredient.SODA])
    _, payload = sell_cup(gs, pid, 0, ["sugar"])
    assert payload["points_earned"] == 10 + 4


def test_selling_both_glasses_can_serve_two_orders():
    gs = _game()
    pid, ps = _me(gs)
    _row(gs, 2).cards[:] = [
        _order("Rum and Cola", "simple", 2, spirit_type="RUM", mixer_type="COLA"),
        _order("Tequila Slammer", "slammer", 3, spirit_type="TEQUILA"),
    ]
    ps.cups[0] = Cup(ingredients=[Ingredient.RUM, Ingredient.COLA])
    ps.cups[1] = Cup(ingredients=[Ingredient.TEQUILA, Ingredient.TEQUILA])
    _, payload = sell_cup(
        gs, pid, 0, [], additional_cups=[{"cup_index": 1, "declared_specials": []}]
    )
    assert payload["points_earned"] == (1 + 2) + (3 + 3)
    assert len(payload["orders"]) == 2


def test_a_drink_nobody_ordered_scores_as_usual():
    gs = _game()
    pid, ps = _me(gs)
    _row(gs, 2).cards[:] = [
        _order("Gin and Tonic", "simple", 2, spirit_type="GIN", mixer_type="TONIC")
    ]
    ps.cups[0] = Cup(ingredients=[Ingredient.RUM, Ingredient.COLA])
    _, payload = sell_cup(gs, pid, 0, [])
    assert payload["points_earned"] == 1
    assert "orders" not in payload


# ─── Clearing rows ───────────────────────────────────────────────────────────


def test_clearing_orders_needs_drunk_three_and_is_the_main_action():
    gs = _game()
    pid, ps = _me(gs)
    ps.drunk_level = 2
    with pytest.raises(GameException):
        refresh_card_row(gs, pid, 2)
    ps.drunk_level = 3
    before = [c.id for c in _row(gs, 2).cards]
    new, payload = refresh_card_row(gs, pid, 2)
    assert payload["is_free_action"] is False
    assert [d["id"] for d in new.order_deck[-3:]] == before
    assert len(_row(new, 2).cards) == 3


def test_swiping_abilities_needs_drunk_two_and_is_free_once_a_turn():
    gs = _game()
    pid, ps = _me(gs)
    ps.drunk_level = 1
    with pytest.raises(GameException):
        refresh_card_row(gs, pid, 3)
    ps.drunk_level = 2
    before = [c.id for c in _row(gs, 3).cards]
    new, payload = refresh_card_row(gs, pid, 3)
    assert payload["is_free_action"] is True
    assert new.player_turn == pid and not new.main_action_taken_this_turn
    assert [d["id"] for d in new._deck_dicts[-3:]] == before
    with pytest.raises(GameException) as exc:
        refresh_card_row(new, pid, 3)
    assert exc.value.status_code == 409


def test_karaoke_row_is_never_cleared():
    gs = _game()
    pid, ps = _me(gs)
    ps.drunk_level = 5
    with pytest.raises(GameException):
        refresh_card_row(gs, pid, 1)


# ─── Specials ────────────────────────────────────────────────────────────────


def _display_special(gs: GameState, face: str) -> int:
    gs.open_display[0] = Ingredient.SPECIAL
    gs.display_specials[0] = face
    return 0


def test_taking_a_special_puts_it_on_the_mat_and_the_token_back_in_the_bag():
    gs = _game()
    pid, ps = _me(gs)
    _display_special(gs, "lemon")
    tokens_before = gs.bag_contents.count(Ingredient.SPECIAL)

    new, payload = take_ingredients(
        gs, pid, [{"ingredient": "SPECIAL", "source": "display", "display_index": 0}]
    )

    assert new.player_states[pid].special_ingredients == ["lemon"]
    assert new.bag_contents.count(Ingredient.SPECIAL) == tokens_before + 1
    assert payload["taken"][0]["special_type"] == "lemon"


def test_choose_any_takes_the_special_you_ask_for():
    gs = _game()
    pid, _ = _me(gs)
    _display_special(gs, "any")
    new, payload = take_ingredients(
        gs,
        pid,
        [
            {
                "ingredient": "SPECIAL",
                "source": "display",
                "display_index": 0,
                "special_type": "vermouth",
            }
        ],
    )
    assert new.player_states[pid].special_ingredients == ["vermouth"]


def test_choose_any_cannot_take_a_special_someone_holds():
    gs = _game()
    pid, _ = _me(gs)
    other = next(p for p in gs.player_states if p != pid)
    gs.player_states[other].special_ingredients = ["vermouth"]
    _display_special(gs, "any")
    new, _ = take_ingredients(
        gs,
        pid,
        [
            {
                "ingredient": "SPECIAL",
                "source": "display",
                "display_index": 0,
                "special_type": "vermouth",
            }
        ],
    )
    got = new.player_states[pid].special_ingredients
    assert len(got) == 1 and got[0] != "vermouth"


def test_holding_two_you_swap_or_leave_the_third():
    gs = _game()
    pid, ps = _me(gs)
    ps.special_ingredients = ["sugar", "bitters"]
    _display_special(gs, "lemon")
    left, payload = take_ingredients(
        gs, pid, [{"ingredient": "SPECIAL", "source": "display", "display_index": 0}]
    )
    assert left.player_states[pid].special_ingredients == ["sugar", "bitters"]
    assert payload["taken"][0]["special_type"] == "nothing"

    swapped, payload = take_ingredients(
        gs,
        pid,
        [
            {
                "ingredient": "SPECIAL",
                "source": "display",
                "display_index": 0,
                "swap_special": "bitters",
            }
        ],
    )
    assert sorted(swapped.player_states[pid].special_ingredients) == ["lemon", "sugar"]
    assert payload["taken"][0]["swapped"] == "bitters"


def test_rolls_never_show_a_special_that_is_held_or_showing(monkeypatch):
    gs = _game()
    pid, _ = _me(gs)
    for i, other in enumerate(gs.player_states.values()):
        other.special_ingredients = [["lemon", "sugar"], ["bitters", "vermouth"]][i]
    gs.open_display = [Ingredient.GIN] * 4
    gs.display_specials = [None] * 4
    gs.bag_contents = [Ingredient.SPECIAL] * 3
    rolls = iter([SpecialType.LEMON, SpecialType.COINTREAU, SpecialType.COINTREAU])
    monkeypatch.setattr(
        "app.specials.SpecialType.roll", classmethod(lambda cls: next(rolls))
    )
    actions._replenish_display(gs)
    assert gs.display_specials[-1] == "cointreau"


def test_selling_a_cocktail_returns_its_specials_to_the_supply():
    gs = _game()
    pid, ps = _me(gs)
    gs.card_rows[1].cards = []
    ps.special_ingredients = ["sugar"]
    tokens = gs.bag_contents.count(Ingredient.SPECIAL)
    ps.cups[0] = Cup(ingredients=[Ingredient.RUM, Ingredient.RUM, Ingredient.SODA])
    new, _ = sell_cup(gs, pid, 0, ["sugar"])
    assert new.player_states[pid].special_ingredients == []
    # The token went back when the special was taken, not again on sale
    assert new.bag_contents.count(Ingredient.SPECIAL) == tokens


def test_rerolling_is_gone():
    gs = _game()
    pid, ps = _me(gs)
    ps.special_ingredients = ["sugar"]
    with pytest.raises(GameException) as exc:
        reroll_specials(gs, pid, ["sugar"])
    assert exc.value.status_code == 400


# ─── Target score ────────────────────────────────────────────────────────────


def test_four_players_trigger_the_last_round_at_thirty():
    gs = _game(4)
    pid, ps = _me(gs)
    gs.card_rows[1].cards = []
    ps.points = 29
    ps.cups[0] = Cup(ingredients=[Ingredient.VODKA, Ingredient.COLA])
    new, _ = sell_cup(gs, pid, 0, [])
    assert new.last_round is True

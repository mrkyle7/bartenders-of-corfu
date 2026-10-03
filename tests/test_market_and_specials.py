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
from app.Ingredient import SPECIAL_INGREDIENTS, Ingredient, SpecialType
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


@pytest.mark.parametrize("players,target", [(2, 40), (3, 35), (4, 30)])
def test_setup_scales_with_players(players, target):
    gs = _game(players)
    in_play = gs.bag_contents + gs.open_display + gs.specials_display
    assert in_play.count(Ingredient.GIN) == players + 3
    # Two of each special, whatever the number of players; no die tokens
    for special in SPECIAL_INGREDIENTS:
        assert in_play.count(special) == 2
    assert Ingredient.SPECIAL not in in_play
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


def test_the_display_shows_five_spirits_and_mixers_and_specials_go_aside():
    for _ in range(20):
        gs = _game(4)
        assert len(gs.open_display) == 5
        assert not any(i in SPECIAL_INGREDIENTS for i in gs.open_display)
        assert all(i in SPECIAL_INGREDIENTS for i in gs.specials_display)
        assert gs.to_dict()["specials_display"] == [i.name for i in gs.specials_display]


# ─── Claiming cards is a free action, once a turn ───────────────────────────


def test_claiming_is_free_and_leaves_the_main_action():
    gs = _game()
    pid, ps = _me(gs)
    ps.bladder = [Ingredient.RUM] * 2
    ps.drunk_level = 3
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
    ps.bladder = [Ingredient.RUM] * 2 + [Ingredient.GIN] * 2
    ps.drunk_level = 3
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
    ps.bladder = [Ingredient.RUM] * 2
    ps.drunk_level = 3
    ps.cups[0] = Cup(ingredients=[Ingredient.VODKA, Ingredient.COLA])
    gs.card_rows[1].cards = []  # no orders to muddy the sale
    # nothing to swipe either (drunk 3 could otherwise swipe the abilities)
    _row(gs, 3).cards = []
    gs._deck_dicts = []
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
    # A card the rum can pay for, so a claim is always possible
    _row(gs, 3).cards = [
        Card(id="c-store", card_type="store", name="Rum Store", spirit_type="RUM")
    ]
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


def test_clearing_orders_needs_drunk_two_and_is_free_once_a_turn():
    gs = _game()
    pid, ps = _me(gs)
    ps.drunk_level = 1
    with pytest.raises(GameException):
        refresh_card_row(gs, pid, 2)
    ps.drunk_level = 2
    before = [c.id for c in _row(gs, 2).cards]
    new, payload = refresh_card_row(gs, pid, 2)
    assert payload["is_free_action"] is True
    assert new.player_turn == pid and not new.main_action_taken_this_turn
    assert [d["id"] for d in new.order_deck[-3:]] == before
    assert len(_row(new, 2).cards) == 3
    with pytest.raises(GameException) as exc:
        refresh_card_row(new, pid, 2)
    assert exc.value.status_code == 409


def test_clearing_orders_after_the_main_action_still_works():
    gs = _game()
    pid, ps = _me(gs)
    ps.drunk_level = 4  # a wee sobers you up by one
    ps.bladder = [Ingredient.SODA]
    gs.card_rows[0].cards = []  # nothing to claim
    after_wee, _ = go_for_a_wee(gs, pid)
    # The turn waits: the orders could still be cleared
    assert after_wee.player_turn == pid
    new, payload = refresh_card_row(after_wee, pid, 2)
    assert payload["is_free_action"] is True


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


def _bag_of(gs: GameState, tokens: list[Ingredient]) -> None:
    gs.bag_contents = list(tokens)


def test_specials_drawn_to_fill_the_display_go_to_the_specials_display(monkeypatch):
    monkeypatch.setattr("app.GameState.random.choice", lambda seq: seq[0])
    gs = _game()
    gs.open_display = [Ingredient.GIN] * 3
    gs.display_specials = [None] * 3
    gs.specials_display = []
    _bag_of(gs, [Ingredient.LEMON, Ingredient.SUGAR, Ingredient.RUM, Ingredient.COLA])
    actions._replenish_display(gs)
    assert sorted(gs.open_display, key=lambda i: i.name) == [
        Ingredient.COLA,
        Ingredient.GIN,
        Ingredient.GIN,
        Ingredient.GIN,
        Ingredient.RUM,
    ]
    assert sorted(i.name for i in gs.specials_display) == ["LEMON", "SUGAR"]
    assert gs.bag_contents == []


def test_a_blind_draw_hands_you_specials_to_deal_with(monkeypatch):
    """Specials drawn blind aren't set aside: they're yours to put on a
    glass rim or drink, like any other token."""
    monkeypatch.setattr("app.GameState.random.choice", lambda seq: seq[0])
    gs = _game()
    pid, ps = _me(gs)
    gs.specials_display = []
    _bag_of(gs, [Ingredient.BITTERS, Ingredient.LEMON, Ingredient.VODKA])
    gs, payload = actions.draw_from_bag(gs, pid, 3)
    assert gs.bag_draw_pending == [
        Ingredient.BITTERS,
        Ingredient.LEMON,
        Ingredient.VODKA,
    ]
    assert gs.specials_display == [] and payload["to_specials_display"] == []
    assert gs.player_states[pid].take_count == 3  # sober: take 3
    gs, _ = take_ingredients(
        gs,
        pid,
        [
            {"source": "pending", "disposition": "cup", "cup_index": 0},  # rim
            {"source": "pending", "disposition": "drink"},
            {"source": "pending", "disposition": "cup", "cup_index": 0},
        ],
    )
    me = gs.player_states[pid]
    assert me.cups[0].ingredients == [Ingredient.BITTERS, Ingredient.VODKA]
    assert Ingredient.LEMON in me.bladder


def test_a_blind_draw_can_take_whatever_is_left_in_the_bag():
    gs = _game()
    pid, _ = _me(gs)
    _bag_of(gs, [Ingredient.BITTERS, Ingredient.VODKA])
    new, _ = actions.draw_from_bag(gs, pid, 2)
    assert sorted(i.name for i in new.bag_draw_pending) == ["BITTERS", "VODKA"]
    with pytest.raises(GameException) as exc:
        actions.draw_from_bag(gs, pid, 3)
    assert exc.value.status_code in (400, 409)


def test_a_special_goes_in_a_glass_on_top_of_five():
    gs = _game()
    pid, ps = _me(gs)
    gs.specials_display = [Ingredient.SUGAR, Ingredient.LEMON]
    ps.cups[0] = Cup(ingredients=[Ingredient.GIN] * 5)
    new, payload = take_ingredients(
        gs,
        pid,
        [
            {
                "ingredient": "SUGAR",
                "source": "specials",
                "disposition": "cup",
                "cup_index": 0,
            }
        ],
    )
    cup = new.player_states[pid].cups[0]
    assert cup.ingredients[-1] == Ingredient.SUGAR
    assert cup.specials == ["sugar"] and cup.is_full
    assert new.specials_display == [Ingredient.LEMON]
    assert payload["taken"][0] == {
        "ingredient": "SUGAR",
        "source": "specials",
        "disposition": "cup",
        "cup_index": 0,
    }
    # It counts as one of the ingredients you take this turn
    assert new.ingredients_taken_this_turn == 1


def test_a_glass_holds_at_most_two_specials():
    gs = _game()
    pid, ps = _me(gs)
    gs.specials_display = [Ingredient.BITTERS]
    ps.cups[1] = Cup(
        ingredients=[Ingredient.WHISKEY, Ingredient.VERMOUTH, Ingredient.LEMON]
    )
    with pytest.raises(GameException):
        take_ingredients(
            gs,
            pid,
            [
                {
                    "ingredient": "BITTERS",
                    "source": "specials",
                    "disposition": "cup",
                    "cup_index": 1,
                }
            ],
        )


def test_you_can_only_take_a_special_that_is_showing():
    gs = _game()
    pid, _ = _me(gs)
    gs.specials_display = [Ingredient.LEMON]
    with pytest.raises(GameException):
        take_ingredients(
            gs,
            pid,
            [{"ingredient": "SUGAR", "source": "specials", "disposition": "drink"}],
        )


def test_drinking_specials_sobers_you_like_a_mixer():
    gs = _game()
    pid, ps = _me(gs)
    ps.drunk_level = 2  # takes five: two specials, three mixers
    gs.specials_display = [Ingredient.LEMON, Ingredient.SUGAR]
    gs.open_display = [Ingredient.SODA] * 3 + [Ingredient.GIN] * 2
    gs.display_specials = [None] * 5
    _bag_of(gs, [Ingredient.GIN] * 10)  # the refill draws no new specials
    new, payload = take_ingredients(
        gs,
        pid,
        [
            {"ingredient": name, "source": "specials", "disposition": "drink"}
            for name in ("LEMON", "SUGAR")
        ]
        + [{"ingredient": "SODA", "source": "display", "disposition": "drink"}] * 3,
    )
    assert payload["turn_complete"]
    me = new.player_states[pid]
    assert me.drunk_level == 0
    assert sorted(i.name for i in me.bladder) == [
        "LEMON",
        "SODA",
        "SODA",
        "SODA",
        "SUGAR",
    ]
    assert new.specials_display == []


def test_specials_never_pay_for_cards():
    gs = _game()
    pid, ps = _me(gs)
    ps.bladder = [Ingredient.LEMON, Ingredient.SUGAR, Ingredient.BITTERS]
    for row in gs.card_rows:
        for card in row.cards:
            # A specialist takes one of its own special (sugar pays for the
            # Rum Specialist); that's tested on its own. Nothing else does.
            if card.card_type == "specialist":
                continue
            assert not actions._can_afford(ps, card)


def test_a_cocktail_made_with_specials_in_the_glass():
    gs = _game()
    pid, ps = _me(gs)
    gs.card_rows[1].cards = []
    ps.cups[0] = Cup(
        ingredients=[Ingredient.RUM, Ingredient.SUGAR, Ingredient.RUM, Ingredient.SODA]
    )
    bag = len(gs.bag_contents)
    new, payload = sell_cup(gs, pid, 0, [])
    assert payload["points_earned"] == 10
    # Everything in the glass, the sugar included, goes back in the bag
    assert len(new.bag_contents) == bag + 4
    assert Ingredient.SUGAR in new.bag_contents


def test_a_special_spoils_a_simple_drink():
    gs = _game()
    pid, ps = _me(gs)
    ps.cups[0] = Cup(ingredients=[Ingredient.RUM, Ingredient.COLA, Ingredient.LEMON])
    with pytest.raises(GameException):
        sell_cup(gs, pid, 0, [])


def test_a_cocktail_order_is_served_by_specials_in_the_glass():
    gs = _game()
    pid, ps = _me(gs)
    _row(gs, 2).cards = [_order("Mojito please", "cocktail", 4, cocktail="Mojito")]
    gs.order_deck = []
    ps.cups[0] = Cup(
        ingredients=[Ingredient.RUM, Ingredient.RUM, Ingredient.SODA, Ingredient.SUGAR]
    )
    new, payload = sell_cup(gs, pid, 0, [])
    assert payload["points_earned"] == 14
    assert payload["orders"] == [{"name": "Mojito please", "bonus": 4}]


def test_an_old_game_with_die_tokens_still_loads_and_plays():
    """Games started before specials were ingredients keep their die tokens."""
    gs = _game()
    data = gs.to_dict()
    data.pop("specials_display")
    data["open_display"][0] = "SPECIAL"
    data["display_specials"] = ["lemon", None, None, None, None]
    old = GameState.from_dict(data)
    assert old.specials_display == []
    pid, _ = _me(old)
    new, payload = take_ingredients(
        old, pid, [{"ingredient": "SPECIAL", "source": "display", "display_index": 0}]
    )
    assert new.player_states[pid].special_ingredients == ["lemon"]


# ─── Specials in games started before they were ingredients ─────────────────
# Those games keep the special die tokens; a special goes on the player's mat.


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


# ─── Boozy specials, paying for cards, specialists paid with a special ──────


def test_bitters_vermouth_and_cointreau_get_you_drunk():
    gs = _game()
    pid, ps = _me(gs)
    gs.specials_display = [Ingredient.BITTERS, Ingredient.VERMOUTH, Ingredient.LEMON]
    _bag_of(gs, [Ingredient.GIN] * 10)
    new, payload = take_ingredients(
        gs,
        pid,
        [
            {"ingredient": name, "source": "specials", "disposition": "drink"}
            for name in ("BITTERS", "VERMOUTH", "LEMON")
        ],
    )
    assert payload["turn_complete"]
    # Two boozy specials: +2, and the lemon can't sober you after them
    assert new.player_states[pid].drunk_level == 2


def test_cointreau_cancels_a_mixers_sobering():
    gs = _game()
    pid, ps = _me(gs)
    ps.drunk_level = 1  # takes four
    gs.specials_display = [Ingredient.COINTREAU]
    gs.open_display = [Ingredient.SODA] * 5
    gs.display_specials = [None] * 5
    _bag_of(gs, [Ingredient.GIN] * 10)
    new, _ = take_ingredients(
        gs,
        pid,
        [{"ingredient": "COINTREAU", "source": "specials", "disposition": "drink"}]
        + [{"ingredient": "SODA", "source": "display", "disposition": "drink"}] * 3,
    )
    assert new.player_states[pid].drunk_level == 2


def _ability(gs: GameState, card: Card) -> None:
    _row(gs, 3).cards = [card]


def test_claiming_leaves_the_cost_in_your_bladder():
    gs = _game()
    pid, ps = _me(gs)
    _row(gs, 1).cards = []
    _ability(
        gs,
        Card(
            id="sp-vodka",
            card_type="specialist",
            name="Vodka Specialist",
            spirit_type="VODKA",
        ),
    )
    ps.bladder = [Ingredient.VODKA, Ingredient.VODKA, Ingredient.SODA]
    bag = len(gs.bag_contents)
    new, payload = claim_card(gs, pid, "sp-vodka")
    assert new.player_states[pid].bladder == ps.bladder  # checked, not spent
    assert len(new.bag_contents) == bag
    assert payload["cost"] == ["VODKA", "VODKA"]


@pytest.mark.parametrize(
    "spirit,special",
    [
        ("WHISKEY", "BITTERS"),
        ("TEQUILA", "COINTREAU"),
        ("VODKA", "VERMOUTH"),
        ("RUM", "SUGAR"),
        ("GIN", "LEMON"),
    ],
)
def test_a_specialist_can_be_paid_with_its_special(spirit, special):
    gs = _game()
    pid, ps = _me(gs)
    _row(gs, 1).cards = []
    _ability(
        gs,
        Card(id="sp", card_type="specialist", name="Specialist", spirit_type=spirit),
    )
    ps.bladder = [Ingredient[special]]
    new, payload = claim_card(gs, pid, "sp")
    assert new.player_states[pid].points == 2
    assert new.player_states[pid].bladder == [Ingredient[special]]
    assert payload["cost"] == [special]


def test_a_specialist_paid_with_spirits_when_you_say_so():
    gs = _game()
    pid, ps = _me(gs)
    _row(gs, 1).cards = []
    _ability(
        gs,
        Card(id="sp", card_type="specialist", name="Rum Specialist", spirit_type="RUM"),
    )
    ps.bladder = [Ingredient.SUGAR, Ingredient.RUM, Ingredient.RUM]
    new, payload = claim_card(gs, pid, "sp", spirit_type="RUM")
    assert payload["cost"] == ["RUM", "RUM"]
    assert len(new.player_states[pid].bladder) == 3


def test_the_wrong_special_does_not_pay_for_a_specialist():
    gs = _game()
    pid, ps = _me(gs)
    _ability(
        gs,
        Card(id="sp", card_type="specialist", name="Rum Specialist", spirit_type="RUM"),
    )
    ps.bladder = [Ingredient.LEMON]
    with pytest.raises(GameException):
        claim_card(gs, pid, "sp")


def test_karaoke_needs_drunk_three_and_two_spirits():
    gs = _game()
    pid, ps = _me(gs)
    card = next(c for c in _row(gs, 1).cards if c.spirit_type == "GIN")
    ps.bladder = [Ingredient.GIN] * 3
    ps.drunk_level = 2
    with pytest.raises(GameException):
        claim_card(gs, pid, card.id)
    ps.drunk_level = 3
    new, payload = claim_card(gs, pid, card.id)
    me = new.player_states[pid]
    assert me.bladder == [Ingredient.GIN] * 3  # the cost stays
    assert me.karaoke_cards_claimed == 1
    assert me.drunk_level == 3
    assert payload["cost"] == ["GIN", "GIN"]


def test_one_spirit_does_not_sing_a_song_however_drunk():
    gs = _game()
    pid, ps = _me(gs)
    card = next(c for c in _row(gs, 1).cards if c.spirit_type == "GIN")
    ps.bladder = [Ingredient.GIN]
    ps.drunk_level = 5
    with pytest.raises(GameException):
        claim_card(gs, pid, card.id)


def test_a_store_card_stores_all_of_its_spirit():
    gs = _game()
    pid, ps = _me(gs)
    _row(gs, 1).cards = []
    _ability(
        gs,
        Card(id="st", card_type="store", name="Gin Store", spirit_type="GIN"),
    )
    ps.bladder = [Ingredient.GIN] * 3
    bag = len(gs.bag_contents)
    new, _ = claim_card(gs, pid, "st")
    me = new.player_states[pid]
    assert me.bladder == []
    assert me.cards[-1]["stored_spirits"] == ["GIN", "GIN", "GIN"]
    assert len(new.bag_contents) == bag


def test_sell_actions_name_the_order_and_its_bonus():
    from playtesting.valid_actions import get_valid_actions

    gs = _game()
    pid, ps = _me(gs)
    _row(gs, 2).cards = [
        _order("Vodka Tonic", "simple", 2, spirit_type="VODKA", mixer_type="TONIC")
    ]
    gs.order_deck = []
    ps.cups[0] = Cup(ingredients=[Ingredient.VODKA, Ingredient.TONIC])
    ps.cups[1] = Cup(ingredients=[Ingredient.VODKA, Ingredient.TONIC])
    sells = [
        a.params for a in get_valid_actions(gs, pid) if a.action_type == "sell_cup"
    ]
    single = next(
        p for p in sells if p["cup_index"] == 0 and "additional_cups" not in p
    )
    assert single["points"] == 3
    assert (single["order"], single["order_bonus"]) == ("Vodka Tonic", 2)
    both = next(p for p in sells if "additional_cups" in p)
    # One order: only the first glass serves it
    assert both["points"] == 4
    assert both["orders"] == [{"cup_index": 0, "name": "Vodka Tonic", "bonus": 2}]


# ─── The Entrepreneur ────────────────────────────────────────────────────────


def _entrepreneur(gs: GameState):
    pid, ps = _me(gs)
    ps.cards.append(
        Card(
            id="c-ent",
            card_type="free_action",
            name="Entrepreneur",
            spirit_type="VODKA",
        ).to_dict()
    )
    ps.cups[0] = Cup(ingredients=[Ingredient.VODKA, Ingredient.COLA])
    ps.bladder = [Ingredient.SODA]
    return pid, ps


def _sells(gs: GameState, pid) -> list:
    from playtesting.valid_actions import get_valid_actions

    return [a for a in get_valid_actions(gs, pid) if a.action_type == "sell_cup"]


def test_entrepreneur_sells_for_free_after_another_main_action():
    gs = _game()
    pid, _ = _entrepreneur(gs)
    gs, payload = go_for_a_wee(gs, pid)
    assert payload["is_free_action"] is False
    assert gs.player_turn == pid  # the free sale holds the turn open
    assert _sells(gs, pid) and all(a.is_free for a in _sells(gs, pid))
    gs, payload = sell_cup(gs, pid, 0, [])
    assert payload["is_free_action"] is True
    assert gs.player_turn != pid


def test_entrepreneur_sells_first_then_takes_any_other_main_action():
    gs = _game()
    pid, ps = _entrepreneur(gs)
    ps.cups[1] = Cup(ingredients=[Ingredient.GIN, Ingredient.TONIC])
    assert all(a.is_free for a in _sells(gs, pid))
    gs, payload = sell_cup(gs, pid, 0, [])
    assert payload["is_free_action"] is True
    assert gs.player_turn == pid and not gs.main_action_taken_this_turn
    # Only one sale a turn: the other glass can't be sold as the main action
    assert _sells(gs, pid) == []
    with pytest.raises(GameException) as exc:
        sell_cup(gs, pid, 1, [])
    assert exc.value.status_code == 409
    gs, payload = go_for_a_wee(gs, pid)
    assert payload["is_free_action"] is False
    assert gs.player_turn != pid


def test_entrepreneur_can_end_the_turn_after_selling_instead_of_a_main_action():
    gs = _game()
    pid, ps = _entrepreneur(gs)
    assert not actions.can_end_turn(gs, ps)
    gs, _ = sell_cup(gs, pid, 0, [])
    assert gs.player_turn == pid
    assert actions.can_end_turn(gs, gs.player_states[pid])
    gs, payload = end_turn(gs, pid)
    assert gs.player_turn != pid
    assert payload["skipped_main_action"] is True


def test_without_a_sale_the_turn_cannot_end_before_the_main_action():
    gs = _game()
    pid, ps = _entrepreneur(gs)
    with pytest.raises(GameException) as exc:
        end_turn(gs, pid)
    assert exc.value.status_code == 409


# ─── Every free-action card works the same way ───────────────────────────────


def _with_card(spirit: str):
    gs = _game()
    pid, ps = _me(gs)
    ps.cards.append(
        Card(
            id=f"c-{spirit}", card_type="free_action", name=spirit, spirit_type=spirit
        ).to_dict()
    )
    ps.cups[0] = Cup(ingredients=[Ingredient.VODKA, Ingredient.COLA])
    ps.cups[1] = Cup(ingredients=[Ingredient.GIN, Ingredient.TONIC])
    ps.bladder = [Ingredient.SODA]
    _row(gs, 3).cards = []  # nothing to claim holding the turn open
    return gs, pid


def _full_glass(gs: GameState, pid) -> int:
    return next(i for i, c in enumerate(gs.player_states[pid].cups) if c.ingredients)


def _take_from_display(gs: GameState, pid):
    n = gs.player_states[pid].take_count
    cups = gs.player_states[pid].cups
    emptier = min(range(2), key=lambda i: len(cups[i].ingredients))
    picks = [
        {
            "ingredient": i.name,
            "source": "display",
            "disposition": "cup",
            "cup_index": emptier,
        }
        for i in gs.open_display[:n]
    ]
    return take_ingredients(gs, pid, picks)


_CARD_ACTIONS = {
    "RUM": ("take_ingredients", _take_from_display),
    "VODKA": ("sell_cup", lambda gs, pid: sell_cup(gs, pid, _full_glass(gs, pid), [])),
    "GIN": ("go_for_a_wee", go_for_a_wee),
}


@pytest.mark.parametrize("spirit", ["RUM", "VODKA", "GIN"])
def test_a_free_action_card_action_is_free_once_and_can_end_the_turn(spirit):
    action_type, do = _CARD_ACTIONS[spirit]
    gs, pid = _with_card(spirit)
    gs, payload = do(gs, pid)
    assert payload["is_free_action"] is True
    assert gs.player_turn == pid and not gs.main_action_taken_this_turn
    # Not offered again, not even as the main action, and refused if tried
    assert action_type not in {a.action_type for a in _valid(gs, pid)}
    gs.player_states[pid].bladder = [Ingredient.SODA]  # a wee could happen again
    with pytest.raises(GameException) as exc:
        do(gs, pid)
    assert exc.value.status_code == 409
    # It stands in for the main action: the turn can end here
    assert actions.can_end_turn(gs, gs.player_states[pid])
    ended, payload = end_turn(gs, pid)
    assert ended.player_turn != pid and payload["skipped_main_action"] is True


@pytest.mark.parametrize("spirit", ["RUM", "VODKA", "GIN"])
def test_a_free_action_card_action_after_the_main_action_is_free(spirit):
    action_type, do = _CARD_ACTIONS[spirit]
    gs, pid = _with_card(spirit)
    gs, _ = actions.drink_cup(gs, pid, 0)  # main action
    assert gs.player_turn == pid  # the card's action holds the turn open
    assert any(a.is_free for a in _valid(gs, pid) if a.action_type == action_type)
    gs, payload = do(gs, pid)
    assert payload["is_free_action"] is True
    assert gs.player_turn != pid


def _valid(gs: GameState, pid) -> list:
    from playtesting.valid_actions import get_valid_actions

    return get_valid_actions(gs, pid)

"""Card and CardRow entities plus deck builder.

Card effects are applied per cards.allium spec.
"""

import random
from dataclasses import dataclass, field
from uuid import uuid4


# What each free-action card lets you do once per turn, by its spirit.
# (The whisky one, Cocktail Shaker, re-rolled specials; re-rolls are no longer
# part of the game, so it left the deck.)
FREE_ACTION_TYPES: dict[str, str] = {
    "RUM": "take_ingredients",
    "VODKA": "sell_cup",
    "GIN": "go_for_a_wee",
}

# The market: row 1 holds every karaoke card, row 2 the drink orders, row 3
# the ability cards.
KARAOKE_ROW = 1
ORDERS_ROW = 2
ABILITY_ROW = 3
ROW_SIZE = 3


@dataclass
class IngredientRequirement:
    kind: str  # "spirit" | "mixer" | "special"
    count: int

    def to_dict(self) -> dict:
        return {"kind": self.kind, "count": self.count}

    @classmethod
    def from_dict(cls, d: dict) -> "IngredientRequirement":
        return cls(kind=d["kind"], count=d["count"])


@dataclass
class Card:
    id: str  # UUID as string
    card_type: str  # "karaoke" | "store" | "refresher" | "cup_doubler" | "specialist" | "free_action" | "order"
    name: str = ""
    spirit_type: str | None = None  # "WHISKEY" | "RUM" | "VODKA" | "GIN" | "TEQUILA"
    mixer_type: str | None = None  # "COLA" | "SODA" | "TONIC" | "CRANBERRY"
    stored_spirits: list[str] = field(default_factory=list)
    # Order cards only: what drink is wanted and the bonus for serving it.
    # drink is "simple" (a spirit and mixer, single or double), "slammer" or
    # "cocktail" (named by ``cocktail``).
    drink: str | None = None
    cocktail: str | None = None
    bonus: int = 0

    @property
    def free_action_type(self) -> str | None:
        """For free_action cards, the action type granted as a free action."""
        if self.card_type != "free_action":
            return None
        return FREE_ACTION_TYPES.get(self.spirit_type)

    @property
    def is_karaoke(self) -> bool:
        return self.card_type == "karaoke"

    @property
    def cost(self) -> list[IngredientRequirement]:
        """Derived cost list for display purposes."""
        if self.card_type == "karaoke":
            return [IngredientRequirement(kind="spirit", count=3)]
        elif self.card_type == "store":
            return [IngredientRequirement(kind="spirit", count=1)]
        elif self.card_type == "refresher":
            return [IngredientRequirement(kind="mixer", count=2)]
        elif self.card_type == "cup_doubler":
            return [IngredientRequirement(kind="spirit", count=3)]
        elif self.card_type == "specialist":
            return [IngredientRequirement(kind="spirit", count=2)]
        elif self.card_type == "free_action":
            return [IngredientRequirement(kind="spirit", count=3)]
        return []

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "card_type": self.card_type,
            "is_karaoke": self.is_karaoke,
            "name": self.name,
            "spirit_type": self.spirit_type,
            "mixer_type": self.mixer_type,
            "stored_spirits": list(self.stored_spirits),
            "cost": [r.to_dict() for r in self.cost],
        }
        if self.free_action_type:
            d["free_action_type"] = self.free_action_type
        if self.card_type == "order":
            d.update(drink=self.drink, cocktail=self.cocktail, bonus=self.bonus)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Card":
        # Backward compatibility: infer card_type from is_karaoke if card_type missing
        if "card_type" in d:
            card_type = d["card_type"]
        else:
            card_type = "karaoke" if d.get("is_karaoke", False) else "store"
        return cls(
            id=d["id"],
            card_type=card_type,
            name=d.get("name", ""),
            spirit_type=d.get("spirit_type"),
            mixer_type=d.get("mixer_type"),
            stored_spirits=list(d.get("stored_spirits", [])),
            drink=d.get("drink"),
            cocktail=d.get("cocktail"),
            bonus=d.get("bonus", 0),
        )


@dataclass
class CardRow:
    position: int  # 1, 2, or 3
    cards: list[Card] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"position": self.position, "cards": [c.to_dict() for c in self.cards]}

    @classmethod
    def from_dict(cls, d: dict) -> "CardRow":
        return cls(
            position=d["position"],
            cards=[Card.from_dict(c) for c in d.get("cards", [])],
        )


def build_deck(game_modes: list[str] | None = None) -> list[Card]:
    """Build the karaoke and ability cards (unshuffled), 24 in all.

    5 KaraokeCards (one per spirit), 5 StoreCards (one per spirit),
    4 RefresherCards (one per mixer), 2 CupDoublerCards,
    5 SpecialistCards (one per spirit), 3 FreeActionCards (RUM, VODKA, GIN).

    ``game_modes`` is accepted for older callers and ignored: there are no
    optional modes that change the deck any more.
    """
    cards: list[Card] = []

    # 5 KaraokeCards — one per spirit type
    for name, spirit in [
        ("Sea Shanty", "RUM"),
        ("Cringey Crooner", "GIN"),
        ("Dazzling Duet", "TEQUILA"),
        ("Party Tune", "VODKA"),
        ("Ballad Master", "WHISKEY"),
    ]:
        cards.append(
            Card(id=str(uuid4()), card_type="karaoke", name=name, spirit_type=spirit)
        )

    # 5 StoreCards — one per spirit type
    for name, spirit in [
        ("Rum Store", "RUM"),
        ("Gin Store", "GIN"),
        ("Tequila Store", "TEQUILA"),
        ("Vodka Store", "VODKA"),
        ("Whisky Store", "WHISKEY"),
    ]:
        cards.append(
            Card(id=str(uuid4()), card_type="store", name=name, spirit_type=spirit)
        )

    # 4 RefresherCards — one per mixer type
    for name, mixer in [
        ("Cola Refresher", "COLA"),
        ("Soda Refresher", "SODA"),
        ("Tonic Refresher", "TONIC"),
        ("Cranberry Refresher", "CRANBERRY"),
    ]:
        cards.append(
            Card(id=str(uuid4()), card_type="refresher", name=name, mixer_type=mixer)
        )

    # 2 CupDoublerCards
    cards.append(Card(id=str(uuid4()), card_type="cup_doubler", name="Bendy Straw"))
    cards.append(
        Card(id=str(uuid4()), card_type="cup_doubler", name="Cocktail Umbrella")
    )

    # 5 SpecialistCards — one per spirit type
    for name, spirit in [
        ("Rum Specialist", "RUM"),
        ("Gin Specialist", "GIN"),
        ("Tequila Specialist", "TEQUILA"),
        ("Vodka Specialist", "VODKA"),
        ("Whisky Specialist", "WHISKEY"),
    ]:
        cards.append(
            Card(id=str(uuid4()), card_type="specialist", name=name, spirit_type=spirit)
        )

    # 3 FreeActionCards — rum, vodka and gin
    for name, spirit in [
        ("Greedy Bartender", "RUM"),
        ("Entrepreneur", "VODKA"),
        ("Weak Bladder", "GIN"),
    ]:
        cards.append(
            Card(
                id=str(uuid4()), card_type="free_action", name=name, spirit_type=spirit
            )
        )

    return cards


# Simple orders: any drink of this spirit and mixer, single or double.
_SIMPLE_ORDERS = [
    ("Vodka and Cola", "VODKA", "COLA"),
    ("Vodka Soda", "VODKA", "SODA"),
    ("Vodka Tonic", "VODKA", "TONIC"),
    ("Vodka Cranberry", "VODKA", "CRANBERRY"),
    ("Rum and Cola", "RUM", "COLA"),
    ("Whisky and Cola", "WHISKEY", "COLA"),
    ("Whisky Soda", "WHISKEY", "SODA"),
    ("Gin and Tonic", "GIN", "TONIC"),
]
SIMPLE_ORDER_BONUS = 2
SLAMMER_ORDER_BONUS = 3
COCKTAIL_ORDER_BONUS = 4
LONG_ISLAND_ORDER_BONUS = 5


def build_order_deck() -> list[Card]:
    """Build the 18 drink orders (unshuffled).

    8 simple drinks (+2), the Tequila Slammer (+3) and one order per
    cocktail (+4; the Long Island Iced Tea +5).
    """
    from app.cocktails import COCKTAIL_NAMES

    orders = [
        Card(
            id=str(uuid4()),
            card_type="order",
            name=name,
            spirit_type=spirit,
            mixer_type=mixer,
            drink="simple",
            bonus=SIMPLE_ORDER_BONUS,
        )
        for name, spirit, mixer in _SIMPLE_ORDERS
    ]
    orders.append(
        Card(
            id=str(uuid4()),
            card_type="order",
            name="Tequila Slammer",
            spirit_type="TEQUILA",
            drink="slammer",
            bonus=SLAMMER_ORDER_BONUS,
        )
    )
    for cocktail in COCKTAIL_NAMES:
        bonus = (
            LONG_ISLAND_ORDER_BONUS
            if cocktail == "Long Island Iced Tea"
            else COCKTAIL_ORDER_BONUS
        )
        orders.append(
            Card(
                id=str(uuid4()),
                card_type="order",
                name=cocktail,
                drink="cocktail",
                cocktail=cocktail,
                bonus=bonus,
            )
        )
    return orders


def deal_market(
    deck: list[Card], orders: list[Card]
) -> tuple[list[CardRow], list[Card], list[Card]]:
    """Lay out the three rows of the market.

    Row 1: every karaoke card, face up (never cleared or replaced).
    Row 2: three orders off the top of the shuffled order deck.
    Row 3: three ability cards off the top of the shuffled ability deck.

    Returns (rows, ability_deck, order_deck); both decks are drawn from the
    front and cleared cards go to the back.
    """
    karaoke = [c for c in deck if c.card_type == "karaoke"]
    abilities = [c for c in deck if c.card_type != "karaoke"]
    random.shuffle(abilities)
    orders = list(orders)
    random.shuffle(orders)
    rows = [
        CardRow(position=KARAOKE_ROW, cards=karaoke),
        CardRow(position=ORDERS_ROW, cards=orders[:ROW_SIZE]),
        CardRow(position=ABILITY_ROW, cards=abilities[:ROW_SIZE]),
    ]
    return rows, abilities[ROW_SIZE:], orders[ROW_SIZE:]

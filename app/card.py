"""Card and CardRow entities plus deck builder.

Card effects are applied per cards.allium spec.
"""

import random
from dataclasses import dataclass, field
from uuid import uuid4


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
    card_type: str  # "karaoke" | "store" | "refresher" | "cup_doubler" | "specialist" | "free_action"
    name: str = ""
    spirit_type: str | None = None  # "WHISKEY" | "RUM" | "VODKA" | "GIN" | "TEQUILA"
    mixer_type: str | None = None  # "COLA" | "SODA" | "TONIC" | "CRANBERRY"
    stored_spirits: list[str] = field(default_factory=list)

    @property
    def free_action_type(self) -> str | None:
        """For free_action cards, the action type granted as a free action."""
        if self.card_type != "free_action":
            return None
        mapping = {
            "RUM": "take_ingredients",
            "WHISKEY": "reroll_specials",
            "VODKA": "sell_cup",
            "GIN": "go_for_a_wee",
        }
        return mapping.get(self.spirit_type)

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
    """Build the 25-card deck per cards.allium spec (unshuffled).

    5 KaraokeCards (one per spirit), 5 StoreCards (one per spirit),
    4 RefresherCards (one per mixer), 2 CupDoublerCards,
    5 SpecialistCards (one per spirit), 4 FreeActionCards (RUM, WHISKEY, VODKA, GIN).

    When the ``reroll_specials_free_action`` game mode is enabled, the
    Cocktail Shaker (WHISKEY → reroll_specials) free-action card is excluded;
    the deck shrinks to 24 cards.
    """
    modes = set(game_modes or [])
    skip_reroll_card = "reroll_specials_free_action" in modes
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

    # 4 FreeActionCards — one each for RUM, WHISKEY, VODKA, GIN
    for name, spirit in [
        ("Greedy Bartender", "RUM"),
        ("Cocktail Shaker", "WHISKEY"),
        ("Entrepreneur", "VODKA"),
        ("Weak Bladder", "GIN"),
    ]:
        if skip_reroll_card and name == "Cocktail Shaker":
            continue
        cards.append(
            Card(
                id=str(uuid4()), card_type="free_action", name=name, spirit_type=spirit
            )
        )

    return cards


def deal_initial_rows(deck: list[Card]) -> tuple[list[CardRow], list[Card]]:
    """Deal cards into 3 rows per cards.allium spec.

    Row 1: 3 random karaoke cards (never refreshable).
    Remaining 18 shuffled: 3 → row 2, 3 → row 3, 12 remain as deck.
    """
    karaoke_cards = [c for c in deck if c.card_type == "karaoke"]
    non_karaoke = [c for c in deck if c.card_type != "karaoke"]

    # Pick 3 random karaoke cards for row 1
    row1_cards = random.sample(karaoke_cards, 3)
    remaining_karaoke = [c for c in karaoke_cards if c not in row1_cards]

    # Shuffle remaining (2 karaoke + non-karaoke others)
    remaining_all = remaining_karaoke + non_karaoke
    random.shuffle(remaining_all)

    row2_cards = remaining_all[:3]
    row3_cards = remaining_all[3:6]
    remaining_deck = remaining_all[6:]

    rows = [
        CardRow(position=1, cards=row1_cards),
        CardRow(position=2, cards=row2_cards),
        CardRow(position=3, cards=row3_cards),
    ]
    return rows, remaining_deck

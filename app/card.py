"""Card and CardRow entities plus deck builder.

Card effects are deferred per spec (see: cards.allium).
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
    is_karaoke: bool
    cost: list[IngredientRequirement]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "is_karaoke": self.is_karaoke,
            "cost": [r.to_dict() for r in self.cost],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Card":
        return cls(
            id=d["id"],
            is_karaoke=d["is_karaoke"],
            cost=[IngredientRequirement.from_dict(r) for r in d.get("cost", [])],
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


def build_deck() -> list[Card]:
    """Build a shuffled deck of cards. Effects are deferred per spec."""
    cards: list[Card] = []

    # 5 karaoke cards — cost: 2 spirits in bladder
    for _ in range(5):
        cards.append(
            Card(
                id=str(uuid4()),
                is_karaoke=True,
                cost=[IngredientRequirement(kind="spirit", count=2)],
            )
        )

    # 15 standard ability cards with varying bladder costs
    standard_costs = [
        [IngredientRequirement(kind="mixer", count=1)],
        [IngredientRequirement(kind="mixer", count=2)],
        [IngredientRequirement(kind="spirit", count=1)],
        [IngredientRequirement(kind="spirit", count=1), IngredientRequirement(kind="mixer", count=1)],
        [IngredientRequirement(kind="mixer", count=1)],
        [IngredientRequirement(kind="spirit", count=2)],
        [IngredientRequirement(kind="mixer", count=2)],
        [IngredientRequirement(kind="spirit", count=1)],
        [IngredientRequirement(kind="mixer", count=1)],
        [IngredientRequirement(kind="spirit", count=1), IngredientRequirement(kind="mixer", count=1)],
        [IngredientRequirement(kind="mixer", count=3)],
        [IngredientRequirement(kind="spirit", count=1)],
        [IngredientRequirement(kind="mixer", count=1)],
        [IngredientRequirement(kind="spirit", count=2)],
        [IngredientRequirement(kind="mixer", count=2)],
    ]
    for cost in standard_costs:
        cards.append(Card(id=str(uuid4()), is_karaoke=False, cost=cost))

    random.shuffle(cards)
    return cards


def deal_initial_rows(deck: list[Card]) -> tuple[list[CardRow], list[Card]]:
    """Deal cards into 3 rows of 3 from the deck. Returns (rows, remaining_deck)."""
    remaining = list(deck)
    rows = []
    for pos in range(1, 4):
        row_cards = []
        for _ in range(3):
            if remaining:
                row_cards.append(remaining.pop(0))
        rows.append(CardRow(position=pos, cards=row_cards))
    return rows, remaining

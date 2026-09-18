"""Parser for the MPC-Autofill order.xml format.

Schema (see https://github.com/chilli-axe/mpc-autofill/wiki/XML-Schema-Specification):

<order>
    <details>
        <quantity>7</quantity>
        <stock>(S30) Standard Smooth</stock>
        <foil>false</foil>
    </details>
    <fronts>
        <card>
            <id>...google drive id or path...</id>
            <sourceType>Google Drive</sourceType>
            <slots>0,1,2,3</slots>
            <name>Rite of Flame.png</name>
            <query>rite of flame</query>
        </card>
    </fronts>
    <backs>...same structure, for individual card backs...</backs>
    <cardback>...Google Drive ID or path of the default back image...</cardback>
</order>

Each <card> element is already its own card design; the number of entries in
<slots> is the quantity of it needed in the deck.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CardEntry:
    id: str
    name: str
    query: str
    source_type: str
    slots: list[int]
    side: str  # "front" or "back"

    @property
    def quantity(self) -> int:
        return len(self.slots) or 1

    @property
    def display_name(self) -> str:
        name = (self.name or self.id).strip()
        for suffix in (".png", ".jpg", ".jpeg", ".webp"):
            if name.lower().endswith(suffix):
                return name[: -len(suffix)]
        return name


@dataclass
class Order:
    quantity: int
    stock: str
    foil: bool
    fronts: list[CardEntry]
    backs: list[CardEntry]
    cardback: str | None


def _text(el: ET.Element | None, tag: str, default: str = "") -> str:
    if el is None:
        return default
    child = el.find(tag)
    if child is None or child.text is None:
        return default
    return child.text.strip()


def _parse_cards(section: ET.Element | None, side: str) -> list[CardEntry]:
    if section is None:
        return []
    cards = []
    for card_el in section.findall("card"):
        slots_raw = _text(card_el, "slots")
        slots = [int(s) for s in slots_raw.split(",") if s.strip() != ""]
        cards.append(
            CardEntry(
                id=_text(card_el, "id"),
                name=_text(card_el, "name") or _text(card_el, "id"),
                query=_text(card_el, "query"),
                source_type=_text(card_el, "sourceType", "Google Drive"),
                slots=slots,
                side=side,
            )
        )
    return cards


def parse_order(path: str | Path) -> Order:
    tree = ET.parse(path)
    root = tree.getroot()
    if root.tag != "order":
        raise ValueError(f"Expected <order> as the root element, found: <{root.tag}>")

    details = root.find("details")
    quantity = int(_text(details, "quantity", "0") or "0")
    stock = _text(details, "stock")
    foil = _text(details, "foil", "false").lower() == "true"

    fronts = _parse_cards(root.find("fronts"), "front")
    backs = _parse_cards(root.find("backs"), "back")

    cardback_el = root.find("cardback")
    cardback = cardback_el.text.strip() if cardback_el is not None and cardback_el.text else None

    return Order(quantity=quantity, stock=stock, foil=foil, fronts=fronts, backs=backs, cardback=cardback)

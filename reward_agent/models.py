from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class CreditCard:
    card_id: str
    bank: str
    network: str
    reward_rate: float
    monthly_reward_cap: float


@dataclass(slots=True)
class Offer:
    offer_id: str
    card_id: str
    merchant: str
    channel: str
    discount_type: str
    discount_value: float
    min_spend: float
    max_discount: float
    source: str
    active: int


@dataclass(slots=True)
class Recommendation:
    card_id: str
    amount: float
    savings: float
    reason: str

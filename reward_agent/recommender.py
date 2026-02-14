from __future__ import annotations

from dataclasses import asdict
from typing import Iterable, Protocol

from reward_agent.models import Recommendation


class DiscountEvaluator(Protocol):
    def compute(self, amount: float, offer: dict) -> float:
        """Return discount amount for a given offer payload."""


class PercentDiscountEvaluator:
    def compute(self, amount: float, offer: dict) -> float:
        return min(amount * offer["discount_value"], offer["max_discount"])


class FlatDiscountEvaluator:
    def compute(self, amount: float, offer: dict) -> float:
        return min(offer["discount_value"], offer["max_discount"])


class Recommender:
    """Card recommendation engine with pluggable discount evaluators."""

    DEFAULT_EVALUATORS: dict[str, DiscountEvaluator] = {
        "percent": PercentDiscountEvaluator(),
        "flat": FlatDiscountEvaluator(),
    }

    def __init__(
        self,
        cards: Iterable[dict],
        offers: Iterable[dict],
        monthly_spend: dict[str, float],
        discount_evaluators: dict[str, DiscountEvaluator] | None = None,
    ):
        self.cards = list(cards)
        self.cards_by_id = {card["card_id"]: card for card in self.cards}
        self.offers = list(offers)
        self.monthly_spend = monthly_spend
        self.discount_evaluators = discount_evaluators or self.DEFAULT_EVALUATORS

    def _calculate_offer_discount(self, amount: float, offer: dict) -> float:
        evaluator = self.discount_evaluators.get(offer["discount_type"])
        if evaluator is None:
            return 0.0
        return evaluator.compute(amount, offer)

    def _effective_savings(self, card: dict, amount: float, merchant: str, channel: str | None) -> tuple[float, str]:
        reward_cap_left = max(card["monthly_reward_cap"] - self.monthly_spend.get(card["card_id"], 0.0), 0.0)
        base_reward = min(amount * card["reward_rate"], reward_cap_left)
        best_offer = 0.0
        best_reason = "base rewards"

        merchant_normalized = merchant.lower()
        channel_normalized = channel.lower() if channel else None

        for offer in self.offers:
            if offer["card_id"] != card["card_id"]:
                continue
            if offer["merchant"].lower() != merchant_normalized:
                continue
            if channel_normalized and offer["channel"].lower() not in {"all", channel_normalized}:
                continue
            if amount < offer["min_spend"]:
                continue

            discount = self._calculate_offer_discount(amount, offer)
            if discount > best_offer:
                best_offer = discount
                best_reason = f"{offer['source']}:{offer['channel']}"

        return base_reward + best_offer, best_reason

    def recommend(self, amount: float, merchant: str, channel: str | None = None) -> list[Recommendation]:
        ranked: list[Recommendation] = []
        for card in self.cards:
            savings, reason = self._effective_savings(card, amount, merchant, channel)
            ranked.append(Recommendation(card_id=card["card_id"], amount=amount, savings=savings, reason=reason))

        ranked.sort(key=lambda item: item.savings, reverse=True)
        return ranked

    def suggest_split(self, amount: float, merchant: str, channel: str | None = None) -> list[Recommendation]:
        if amount <= 0:
            return []

        allocations: list[Recommendation] = []
        remaining = amount

        for ranked_item in self.recommend(amount=amount, merchant=merchant, channel=channel):
            if remaining <= 0:
                break
            allocation_amount = round(min(remaining, amount * 0.5), 2)
            card = self.cards_by_id[ranked_item.card_id]
            split_savings = self._effective_savings(card, allocation_amount, merchant, channel)[0]
            allocations.append(
                Recommendation(
                    card_id=ranked_item.card_id,
                    amount=allocation_amount,
                    savings=split_savings,
                    reason=f"split strategy via {ranked_item.reason}",
                )
            )
            remaining = round(remaining - allocation_amount, 2)

        if remaining > 0 and allocations:
            allocations[-1].amount += remaining

        return allocations


def rec_to_dict(rows: Iterable[Recommendation]) -> list[dict]:
    return [asdict(r) for r in rows]

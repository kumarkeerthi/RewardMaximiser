from __future__ import annotations

from dataclasses import asdict
from typing import Iterable

from reward_agent.models import Recommendation


class Recommender:
    def __init__(self, cards: Iterable[dict], offers: Iterable[dict], monthly_spend: dict[str, float]):
        self.cards = list(cards)
        self.offers = list(offers)
        self.monthly_spend = monthly_spend

    def _effective_savings(self, card: dict, amount: float, merchant: str, channel: str | None) -> tuple[float, str]:
        reward_cap_left = max(card["monthly_reward_cap"] - self.monthly_spend.get(card["card_id"], 0.0), 0.0)
        base_reward = min(amount * card["reward_rate"], reward_cap_left)
        best_offer = 0.0
        best_reason = "base rewards"

        for offer in self.offers:
            if offer["card_id"] != card["card_id"]:
                continue
            if offer["merchant"].lower() != merchant.lower():
                continue
            if channel and offer["channel"].lower() not in {"all", channel.lower()}:
                continue
            if amount < offer["min_spend"]:
                continue

            if offer["discount_type"] == "percent":
                discount = min(amount * offer["discount_value"], offer["max_discount"])
            else:
                discount = min(offer["discount_value"], offer["max_discount"])

            if discount > best_offer:
                best_offer = discount
                best_reason = f"{offer['source']}:{offer['channel']}"

        return base_reward + best_offer, best_reason

    def recommend(self, amount: float, merchant: str, channel: str | None = None) -> list[Recommendation]:
        best: list[Recommendation] = []
        for card in self.cards:
            savings, reason = self._effective_savings(card, amount, merchant, channel)
            best.append(
                Recommendation(card_id=card["card_id"], amount=amount, savings=savings, reason=reason)
            )

        best.sort(key=lambda item: item.savings, reverse=True)
        return best

    def suggest_split(self, amount: float, merchant: str, channel: str | None = None) -> list[Recommendation]:
        if amount <= 0:
            return []
        allocations: list[Recommendation] = []
        remaining = amount
        sorted_cards = self.recommend(amount=amount, merchant=merchant, channel=channel)
        for item in sorted_cards:
            if remaining <= 0:
                break
            allocation_amount = round(min(remaining, amount * 0.5), 2)
            split_savings = self._effective_savings(
                next(c for c in self.cards if c["card_id"] == item.card_id),
                allocation_amount,
                merchant,
                channel,
            )[0]
            allocations.append(
                Recommendation(
                    card_id=item.card_id,
                    amount=allocation_amount,
                    savings=split_savings,
                    reason=f"split strategy via {item.reason}",
                )
            )
            remaining = round(remaining - allocation_amount, 2)
        if remaining > 0 and allocations:
            allocations[-1].amount += remaining
        return allocations


def rec_to_dict(rows: Iterable[Recommendation]) -> list[dict]:
    return [asdict(r) for r in rows]

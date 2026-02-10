from __future__ import annotations

import argparse
import json
from pathlib import Path

from reward_agent.db import Database
from reward_agent.models import CreditCard
from reward_agent.providers import JsonOfferProvider, OpenClawProvider
from reward_agent.recommender import Recommender, rec_to_dict
from reward_agent.refresh import refresh_offers, run_refresh_daemon


def load_cards(cards_path: str) -> list[CreditCard]:
    payload = json.loads(Path(cards_path).read_text())
    return [CreditCard(**item) for item in payload]


def providers_from_args(args: argparse.Namespace):
    providers = []
    if args.bank_offers:
        providers.append(JsonOfferProvider(source="bank", file_path=args.bank_offers))
    if args.social_offers:
        providers.append(JsonOfferProvider(source="social", file_path=args.social_offers))
    if args.use_openclaw:
        providers.append(OpenClawProvider(source="openclaw"))
    return providers


def cmd_refresh(args: argparse.Namespace) -> None:
    db = Database(args.db)
    providers = providers_from_args(args)
    refresh_offers(db, providers)
    print("Offers refreshed")


def cmd_daemon(args: argparse.Namespace) -> None:
    db = Database(args.db)
    providers = providers_from_args(args)
    run_refresh_daemon(db, providers, days=2)


def cmd_recommend(args: argparse.Namespace) -> None:
    db = Database(args.db)
    cards = [dict(row) for row in db.fetch_cards()]
    offers = [dict(row) for row in db.fetch_active_offers(merchant=args.merchant)]
    monthly = db.monthly_spend_by_card()
    rec = Recommender(cards=cards, offers=offers, monthly_spend=monthly)
    if args.split:
        result = rec.suggest_split(amount=args.amount, merchant=args.merchant, channel=args.channel)
    else:
        result = rec.recommend(amount=args.amount, merchant=args.merchant, channel=args.channel)[:3]
    print(json.dumps(rec_to_dict(result), indent=2))


def cmd_record_expense(args: argparse.Namespace) -> None:
    db = Database(args.db)
    db.add_expense(card_id=args.card_id, merchant=args.merchant, amount=args.amount, category=args.category)
    print("Expense recorded")


def cmd_sync_cards(args: argparse.Namespace) -> None:
    db = Database(args.db)
    cards = load_cards(args.cards)
    db.upsert_cards(cards)
    print(f"Synced {len(cards)} cards")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Credit card rewards maximiser agent")
    parser.add_argument("--db", default="rewardmaximiser.db")
    parser.add_argument("--bank-offers")
    parser.add_argument("--social-offers")
    parser.add_argument("--use-openclaw", action="store_true")

    sub = parser.add_subparsers(required=True)

    sync = sub.add_parser("sync-cards")
    sync.add_argument("--cards", required=True)
    sync.set_defaults(func=cmd_sync_cards)

    refresh = sub.add_parser("refresh")
    refresh.set_defaults(func=cmd_refresh)

    daemon = sub.add_parser("daemon")
    daemon.set_defaults(func=cmd_daemon)

    rec = sub.add_parser("recommend")
    rec.add_argument("--merchant", required=True)
    rec.add_argument("--amount", type=float, required=True)
    rec.add_argument("--channel", default="all")
    rec.add_argument("--split", action="store_true")
    rec.set_defaults(func=cmd_recommend)

    expense = sub.add_parser("record-expense")
    expense.add_argument("--card-id", required=True)
    expense.add_argument("--merchant", required=True)
    expense.add_argument("--amount", type=float, required=True)
    expense.add_argument("--category", default="")
    expense.set_defaults(func=cmd_record_expense)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

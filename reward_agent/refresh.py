from __future__ import annotations

import time
from typing import Iterable

from reward_agent.db import Database
from reward_agent.providers import OfferProvider


def refresh_offers(db: Database, providers: Iterable[OfferProvider]) -> None:
    for provider in providers:
        try:
            offers = provider.fetch_offers()
            db.replace_offers(offers, source=provider.source)
            db.log_refresh(provider.source, "ok", f"offers={len(offers)}")
        except Exception as exc:  # noqa: BLE001
            db.log_refresh(provider.source, "failed", str(exc))


def run_refresh_daemon(db: Database, providers: Iterable[OfferProvider], days: int = 2) -> None:
    interval_seconds = days * 24 * 60 * 60
    while True:
        refresh_offers(db, providers)
        time.sleep(interval_seconds)

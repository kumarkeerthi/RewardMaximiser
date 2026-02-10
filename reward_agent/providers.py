from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from reward_agent.models import Offer


class OfferProvider(Protocol):
    source: str

    def fetch_offers(self) -> list[Offer]:
        ...


class JsonOfferProvider:
    def __init__(self, source: str, file_path: str) -> None:
        self.source = source
        self.file_path = Path(file_path)

    def fetch_offers(self) -> list[Offer]:
        payload = json.loads(self.file_path.read_text())
        return [Offer(source=self.source, active=1, **item) for item in payload]


class OpenClawProvider:
    """
    Adapter placeholder for OpenClaw (or a similar autonomous browser framework).
    Replace fetch_offers with framework-specific scraping flows.
    """

    def __init__(self, source: str) -> None:
        self.source = source

    def fetch_offers(self) -> list[Offer]:
        return []

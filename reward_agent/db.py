from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable

from reward_agent.models import CreditCard, Offer


class Database:
    def __init__(self, path: str = "rewardmaximiser.db") -> None:
        self.path = Path(path)
        self._init_schema()

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS cards (
                    card_id TEXT PRIMARY KEY,
                    bank TEXT NOT NULL,
                    network TEXT NOT NULL,
                    reward_rate REAL NOT NULL,
                    monthly_reward_cap REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS offers (
                    offer_id TEXT PRIMARY KEY,
                    card_id TEXT NOT NULL,
                    merchant TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    discount_type TEXT NOT NULL,
                    discount_value REAL NOT NULL,
                    min_spend REAL NOT NULL,
                    max_discount REAL NOT NULL,
                    source TEXT NOT NULL,
                    active INTEGER NOT NULL,
                    last_refreshed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(card_id) REFERENCES cards(card_id)
                );

                CREATE TABLE IF NOT EXISTS expenses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    card_id TEXT NOT NULL,
                    merchant TEXT NOT NULL,
                    amount REAL NOT NULL,
                    category TEXT,
                    spent_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(card_id) REFERENCES cards(card_id)
                );

                CREATE TABLE IF NOT EXISTS refresh_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    refreshed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    status TEXT NOT NULL,
                    detail TEXT
                );
                """
            )

    def upsert_cards(self, cards: Iterable[CreditCard]) -> None:
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO cards(card_id, bank, network, reward_rate, monthly_reward_cap)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(card_id) DO UPDATE SET
                    bank=excluded.bank,
                    network=excluded.network,
                    reward_rate=excluded.reward_rate,
                    monthly_reward_cap=excluded.monthly_reward_cap
                """,
                [(c.card_id, c.bank, c.network, c.reward_rate, c.monthly_reward_cap) for c in cards],
            )

    def replace_offers(self, offers: Iterable[Offer], source: str) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE offers SET active = 0 WHERE source = ?", (source,))
            conn.executemany(
                """
                INSERT INTO offers(
                    offer_id, card_id, merchant, channel, discount_type, discount_value,
                    min_spend, max_discount, source, active, last_refreshed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(offer_id) DO UPDATE SET
                    card_id=excluded.card_id,
                    merchant=excluded.merchant,
                    channel=excluded.channel,
                    discount_type=excluded.discount_type,
                    discount_value=excluded.discount_value,
                    min_spend=excluded.min_spend,
                    max_discount=excluded.max_discount,
                    source=excluded.source,
                    active=excluded.active,
                    last_refreshed_at=CURRENT_TIMESTAMP
                """,
                [
                    (
                        o.offer_id,
                        o.card_id,
                        o.merchant,
                        o.channel,
                        o.discount_type,
                        o.discount_value,
                        o.min_spend,
                        o.max_discount,
                        o.source,
                        o.active,
                    )
                    for o in offers
                ],
            )

    def log_refresh(self, source: str, status: str, detail: str = "") -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO refresh_log(source, status, detail) VALUES (?, ?, ?)",
                (source, status, detail),
            )

    def add_expense(self, card_id: str, merchant: str, amount: float, category: str = "") -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO expenses(card_id, merchant, amount, category) VALUES (?, ?, ?, ?)",
                (card_id, merchant, amount, category),
            )

    def monthly_spend_by_card(self) -> dict[str, float]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT card_id, COALESCE(SUM(amount), 0.0) as total
                FROM expenses
                WHERE strftime('%Y-%m', spent_at) = strftime('%Y-%m', 'now')
                GROUP BY card_id
                """
            ).fetchall()
        return {row["card_id"]: float(row["total"]) for row in rows}

    def fetch_cards(self) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM cards").fetchall()

    def fetch_active_offers(self, merchant: str | None = None) -> list[sqlite3.Row]:
        query = "SELECT * FROM offers WHERE active = 1"
        params: list[str] = []
        if merchant:
            query += " AND lower(merchant) = lower(?)"
            params.append(merchant)
        with self.connect() as conn:
            return conn.execute(query, params).fetchall()

from __future__ import annotations

import json
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
                    monthly_reward_cap REAL NOT NULL,
                    category_multipliers TEXT NOT NULL DEFAULT '{}',
                    channel_multipliers TEXT NOT NULL DEFAULT '{}',
                    merchant_multipliers TEXT NOT NULL DEFAULT '{}',
                    annual_fee REAL NOT NULL DEFAULT 0,
                    milestone_spend REAL NOT NULL DEFAULT 0,
                    milestone_bonus REAL NOT NULL DEFAULT 0
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

                CREATE TABLE IF NOT EXISTS app_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            self._ensure_column(conn, "cards", "category_multipliers", "TEXT NOT NULL DEFAULT '{}' ")
            self._ensure_column(conn, "cards", "channel_multipliers", "TEXT NOT NULL DEFAULT '{}' ")
            self._ensure_column(conn, "cards", "merchant_multipliers", "TEXT NOT NULL DEFAULT '{}' ")
            self._ensure_column(conn, "cards", "annual_fee", "REAL NOT NULL DEFAULT 0")
            self._ensure_column(conn, "cards", "milestone_spend", "REAL NOT NULL DEFAULT 0")
            self._ensure_column(conn, "cards", "milestone_bonus", "REAL NOT NULL DEFAULT 0")

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, col_type_sql: str) -> None:
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type_sql}")

    def upsert_cards(self, cards: Iterable[CreditCard]) -> None:
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO cards(
                    card_id, bank, network, reward_rate, monthly_reward_cap,
                    category_multipliers, channel_multipliers, merchant_multipliers,
                    annual_fee, milestone_spend, milestone_bonus
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(card_id) DO UPDATE SET
                    bank=excluded.bank,
                    network=excluded.network,
                    reward_rate=excluded.reward_rate,
                    monthly_reward_cap=excluded.monthly_reward_cap,
                    category_multipliers=excluded.category_multipliers,
                    channel_multipliers=excluded.channel_multipliers,
                    merchant_multipliers=excluded.merchant_multipliers,
                    annual_fee=excluded.annual_fee,
                    milestone_spend=excluded.milestone_spend,
                    milestone_bonus=excluded.milestone_bonus
                """,
                [
                    (
                        c.card_id,
                        c.bank,
                        c.network,
                        c.reward_rate,
                        c.monthly_reward_cap,
                        json.dumps(c.category_multipliers or {}),
                        json.dumps(c.channel_multipliers or {}),
                        json.dumps(c.merchant_multipliers or {}),
                        c.annual_fee,
                        c.milestone_spend,
                        c.milestone_bonus,
                    )
                    for c in cards
                ],
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

    def fetch_expenses(self, limit: int = 500) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT id, card_id, merchant, amount, category, spent_at
                FROM expenses
                ORDER BY spent_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

    def fetch_cards(self) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM cards").fetchall()

    def delete_card(self, card_id: str) -> bool:
        with self.connect() as conn:
            result = conn.execute("DELETE FROM cards WHERE card_id = ?", (card_id,))
        return result.rowcount > 0

    def has_cards(self) -> bool:
        with self.connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM cards").fetchone()
        return bool(row and row["count"] > 0)

    def set_state(self, key: str, value: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO app_state(key, value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP
                """,
                (key, value),
            )

    def get_state(self, key: str, default: str = "") -> str:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def fetch_active_offers(self, merchant: str | None = None) -> list[sqlite3.Row]:
        query = "SELECT * FROM offers WHERE active = 1"
        params: list[str] = []
        if merchant:
            query += " AND lower(merchant) = lower(?)"
            params.append(merchant)
        with self.connect() as conn:
            return conn.execute(query, params).fetchall()

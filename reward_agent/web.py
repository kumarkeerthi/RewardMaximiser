from __future__ import annotations

import cgi
import json
import threading
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from reward_agent.db import Database
from reward_agent.intelligence import IndianCardLifestyleAgent, LLMRefiner, LocalResearchAgent, SocialScanner
from reward_agent.models import CreditCard
from reward_agent.recommender import Recommender, rec_to_dict

BASE_DIR = Path(__file__).parent


@dataclass(slots=True)
class AppServices:
    db: Database
    scanner: SocialScanner
    local_agent: LocalResearchAgent
    refiner: LLMRefiner
    lifestyle_agent: IndianCardLifestyleAgent


def _load_cards_payload(filename: str, raw: bytes) -> list[CreditCard]:
    def _parse_rate_map(value: str) -> dict[str, float]:
        if not value:
            return {}
        try:
            payload = json.loads(value)
            if isinstance(payload, dict):
                return {str(k).strip().lower(): float(v) for k, v in payload.items()}
        except (ValueError, TypeError):
            pass
        return {}

    name = filename.lower()
    if name.endswith(".csv"):
        rows = raw.decode("utf-8").strip().splitlines()
        headers = [x.strip() for x in rows[0].split(",")]
        cards = []
        for row in rows[1:]:
            values = [x.strip() for x in row.split(",")]
            payload = dict(zip(headers, values))
            cards.append(
                CreditCard(
                    card_id=payload["card_id"],
                    bank=payload["bank"],
                    network=payload["network"],
                    reward_rate=float(payload["reward_rate"]),
                    monthly_reward_cap=float(payload["monthly_reward_cap"]),
                    category_multipliers=_parse_rate_map(payload.get("category_multipliers", "")),
                    channel_multipliers=_parse_rate_map(payload.get("channel_multipliers", "")),
                    merchant_multipliers=_parse_rate_map(payload.get("merchant_multipliers", "")),
                    annual_fee=float(payload.get("annual_fee", 0.0) or 0.0),
                    milestone_spend=float(payload.get("milestone_spend", 0.0) or 0.0),
                    milestone_bonus=float(payload.get("milestone_bonus", 0.0) or 0.0),
                )
            )
        return cards

    payload = json.loads(raw.decode("utf-8"))
    return [CreditCard(**item) for item in payload]


def _serve_file(path: Path) -> tuple[bytes, str]:
    if path.suffix == ".css":
        content_type = "text/css; charset=utf-8"
    elif path.suffix == ".js":
        content_type = "text/javascript; charset=utf-8"
    else:
        content_type = "text/html; charset=utf-8"
    return path.read_bytes(), content_type


def _run_daily_sync(db_path: str, interval_hours: int = 24) -> None:
    db = Database(db_path)
    agent = LocalResearchAgent()
    while True:
        snapshot = agent.run_daily_scan()
        db.set_state("daily_scan_snapshot", json.dumps(snapshot))
        db.log_refresh("local-agent-daily", "ok", f"mentions={len(snapshot.get('bank_and_reward_mentions', []))}")
        threading.Event().wait(interval_hours * 3600)


def _run_weekly_lifestyle_scan(db_path: str, interval_hours: int = 24 * 7) -> None:
    db = Database(db_path)
    scanner = SocialScanner()
    local_agent = LocalResearchAgent(scanner=scanner)
    lifestyle_agent = IndianCardLifestyleAgent(local_agent=local_agent, scanner=scanner)
    while True:
        expenses = [dict(row) for row in db.fetch_expenses(limit=1000)]
        report = lifestyle_agent.build_weekly_report(expenses=expenses)
        db.set_state("weekly_lifestyle_report", json.dumps(report))
        db.log_refresh("indian-card-lifestyle-weekly", "ok", f"candidates={len(report.get('candidates', []))}")
        threading.Event().wait(interval_hours * 3600)


def _build_services(db_path: str) -> AppServices:
    db = Database(db_path)
    scanner = SocialScanner()
    local_agent = LocalResearchAgent(scanner=scanner)
    return AppServices(
        db=db,
        scanner=scanner,
        local_agent=local_agent,
        refiner=LLMRefiner(),
        lifestyle_agent=IndianCardLifestyleAgent(local_agent=local_agent, scanner=scanner),
    )


def create_handler(db_path: str):
    services = _build_services(db_path)

    class Handler(BaseHTTPRequestHandler):
        def _send_json(self, payload: dict, status: int = 200) -> None:
            raw = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _send_text(self, raw: bytes, content_type: str = "text/html; charset=utf-8", status: int = 200) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _read_json_body(self) -> dict:
            size = int(self.headers.get("Content-Length", "0"))
            return json.loads(self.rfile.read(size).decode("utf-8")) if size else {}

        def _handle_get(self, path: str) -> bool:
            db = services.db
            if path == "/":
                raw, ctype = _serve_file(BASE_DIR / "templates" / "index.html")
                self._send_text(raw, ctype)
                return True
            if path == "/expenses":
                raw, ctype = _serve_file(BASE_DIR / "templates" / "expenses.html")
                self._send_text(raw, ctype)
                return True
            if path.startswith("/static/"):
                target = BASE_DIR / path.lstrip("/")
                if target.exists():
                    raw, ctype = _serve_file(target)
                    self._send_text(raw, ctype)
                else:
                    self.send_error(HTTPStatus.NOT_FOUND)
                return True
            if path == "/api/setup-status":
                self._send_json({"needs_setup": not db.has_cards()})
                return True
            if path == "/api/cards":
                cards = [dict(row) for row in db.fetch_cards()]
                self._send_json({"cards": cards})
                return True
            if path == "/api/cards/catalog":
                cards = services.local_agent.discover_cards()
                self._send_json({"cards": cards})
                return True
            if path == "/api/daily-scan":
                payload = db.get_state("daily_scan_snapshot", default="{}")
                self._send_json({"snapshot": json.loads(payload)})
                return True
            if path == "/api/lifestyle-report":
                payload = db.get_state("weekly_lifestyle_report", default="{}")
                self._send_json({"report": json.loads(payload)})
                return True
            return False

        def _handle_delete(self, path: str) -> bool:
            if not path.startswith("/api/cards/"):
                return False
            card_id = path.replace("/api/cards/", "", 1).strip()
            if not card_id:
                self._send_json({"error": "card_id missing"}, status=400)
                return True
            deleted = services.db.delete_card(card_id)
            if not deleted:
                self._send_json({"error": "card not found"}, status=404)
                return True
            self._send_json({"ok": True})
            return True

        def _create_card(self, payload: dict) -> CreditCard:
            def _coerce_map(value: object) -> dict[str, float]:
                if not isinstance(value, dict):
                    return {}
                return {str(k).strip().lower(): float(v) for k, v in value.items()}

            required = ["card_id", "bank", "network", "reward_rate", "monthly_reward_cap"]
            if not all(key in payload for key in required):
                raise ValueError("Missing required card fields")
            return CreditCard(
                card_id=str(payload["card_id"]).strip(),
                bank=str(payload["bank"]).strip(),
                network=str(payload["network"]).strip(),
                reward_rate=float(payload["reward_rate"]),
                monthly_reward_cap=float(payload["monthly_reward_cap"]),
                category_multipliers=_coerce_map(payload.get("category_multipliers", {})),
                channel_multipliers=_coerce_map(payload.get("channel_multipliers", {})),
                merchant_multipliers=_coerce_map(payload.get("merchant_multipliers", {})),
                annual_fee=float(payload.get("annual_fee", 0.0) or 0.0),
                milestone_spend=float(payload.get("milestone_spend", 0.0) or 0.0),
                milestone_bonus=float(payload.get("milestone_bonus", 0.0) or 0.0),
            )

        def _build_recommendation_response(self, payload: dict) -> dict:
            merchant = payload.get("merchant", "")
            amount = float(payload.get("amount", 0))
            channel = payload.get("channel", "all")
            category = payload.get("category", "other")
            split = bool(payload.get("split", False))
            merchant_url = payload.get("merchant_url", "")

            cards = [dict(row) for row in services.db.fetch_cards()]
            offers = [dict(row) for row in services.db.fetch_active_offers(merchant=merchant)]
            monthly = services.db.monthly_spend_by_card()
            rec = Recommender(cards=cards, offers=offers, monthly_spend=monthly)
            ranked = (
                rec.suggest_split(amount=amount, merchant=merchant, channel=channel, category=category)
                if split
                else rec.recommend(amount=amount, merchant=merchant, channel=channel, category=category)
            )
            ranked_dict = rec_to_dict(ranked)

            social = services.scanner.scan(merchant=merchant)
            merchant_insights = services.local_agent.scan_merchant(merchant_url)
            refined_text = services.refiner.refine(
                {
                    "merchant": merchant,
                    "amount": amount,
                    "channel": channel,
                    "category": category,
                    "split": split,
                    "recommendations": ranked_dict,
                    "community_insights": social.raw_items,
                    "merchant_insights": merchant_insights,
                }
            )
            return {
                "recommendations": ranked_dict,
                "insights": {
                    "summary": social.summary,
                    "sources": social.sources,
                    "items": social.raw_items,
                },
                "merchant_insights": merchant_insights,
                "refined_response": refined_text,
            }

        def _handle_post(self, path: str) -> bool:
            if path == "/api/cards/upload":
                form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={"REQUEST_METHOD": "POST"})
                upload = form["cards_file"] if "cards_file" in form else None
                if upload is None or upload.file is None:
                    self._send_json({"error": "cards_file is required"}, status=400)
                    return True
                cards = _load_cards_payload(upload.filename or "cards.json", upload.file.read())
                services.db.upsert_cards(cards)
                self._send_json({"ok": True, "count": len(cards)})
                return True

            if path == "/api/cards":
                try:
                    card = self._create_card(self._read_json_body())
                except ValueError as exc:
                    self._send_json({"error": str(exc)}, status=400)
                    return True
                services.db.upsert_cards([card])
                self._send_json({"ok": True, "card_id": card.card_id})
                return True

            if path == "/api/expenses":
                size = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(size).decode("utf-8")
                payload = parse_qs(body)
                card_id = payload.get("card_id", [""])[0].strip()
                merchant = payload.get("merchant", [""])[0].strip()
                category = payload.get("category", ["other"])[0]
                amount = float(payload.get("amount", ["0"])[0])
                if not card_id or not merchant or amount <= 0:
                    self._send_json({"error": "card_id, merchant, and positive amount are required"}, status=400)
                    return True
                services.db.add_expense(card_id=card_id, merchant=merchant, amount=amount, category=category)
                self.send_response(302)
                self.send_header("Location", "/expenses")
                self.end_headers()
                return True

            if path == "/api/lifestyle-report/run":
                payload = self._read_json_body()
                selected_card = str(payload.get("selected_card", "")).strip()
                expenses = [dict(row) for row in services.db.fetch_expenses(limit=1000)]
                report = services.lifestyle_agent.build_weekly_report(expenses=expenses, selected_card=selected_card)
                services.db.set_state("weekly_lifestyle_report", json.dumps(report))
                self._send_json({"report": report})
                return True

            if path == "/api/recommend":
                self._send_json(self._build_recommendation_response(self._read_json_body()))
                return True
            return False

        def do_GET(self):
            parsed = urlparse(self.path)
            if self._handle_get(parsed.path):
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def do_DELETE(self):
            parsed = urlparse(self.path)
            if self._handle_delete(parsed.path):
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self):
            parsed = urlparse(self.path)
            if self._handle_post(parsed.path):
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def log_message(self, format, *args):
            return

    return Handler


def run_web_server(db_path: str = "rewardmaximiser.db", host: str = "0.0.0.0", port: int = 8000) -> None:
    thread = threading.Thread(target=_run_daily_sync, args=(db_path,), daemon=True)
    thread.start()
    weekly_thread = threading.Thread(target=_run_weekly_lifestyle_scan, args=(db_path,), daemon=True)
    weekly_thread.start()
    server = ThreadingHTTPServer((host, port), create_handler(db_path))
    print(f"Web UI running on http://{host}:{port}")
    server.serve_forever()

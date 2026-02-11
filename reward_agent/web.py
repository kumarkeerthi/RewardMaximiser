from __future__ import annotations

import cgi
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from reward_agent.db import Database
from reward_agent.intelligence import LLMRefiner, SocialScanner
from reward_agent.models import CreditCard
from reward_agent.recommender import Recommender, rec_to_dict

BASE_DIR = Path(__file__).parent


def _load_cards_payload(filename: str, raw: bytes) -> list[CreditCard]:
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


def create_handler(db_path: str):
    db = Database(db_path)
    scanner = SocialScanner()
    refiner = LLMRefiner()

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

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/":
                raw, ctype = _serve_file(BASE_DIR / "templates" / "index.html")
                self._send_text(raw, ctype)
                return
            if parsed.path == "/expenses":
                raw, ctype = _serve_file(BASE_DIR / "templates" / "expenses.html")
                self._send_text(raw, ctype)
                return
            if parsed.path.startswith("/static/"):
                target = BASE_DIR / parsed.path.lstrip("/")
                if target.exists():
                    raw, ctype = _serve_file(target)
                    self._send_text(raw, ctype)
                else:
                    self.send_error(HTTPStatus.NOT_FOUND)
                return
            if parsed.path == "/api/cards":
                cards = [dict(row) for row in db.fetch_cards()]
                self._send_json({"cards": cards})
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self):
            parsed = urlparse(self.path)
            if parsed.path == "/api/cards/upload":
                form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={"REQUEST_METHOD": "POST"})
                upload = form["cards_file"] if "cards_file" in form else None
                if upload is None or upload.file is None:
                    self._send_json({"error": "cards_file is required"}, status=400)
                    return
                cards = _load_cards_payload(upload.filename or "cards.json", upload.file.read())
                db.upsert_cards(cards)
                self._send_json({"ok": True, "count": len(cards)})
                return

            if parsed.path == "/api/expenses":
                size = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(size).decode("utf-8")
                payload = parse_qs(body)
                card_id = payload.get("card_id", [""])[0].strip()
                merchant = payload.get("merchant", [""])[0].strip()
                category = payload.get("category", ["other"])[0]
                amount = float(payload.get("amount", ["0"])[0])
                if not card_id or not merchant or amount <= 0:
                    self._send_json({"error": "card_id, merchant, and positive amount are required"}, status=400)
                    return
                db.add_expense(card_id=card_id, merchant=merchant, amount=amount, category=category)
                self.send_response(302)
                self.send_header("Location", "/expenses")
                self.end_headers()
                return

            if parsed.path == "/api/recommend":
                size = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(size).decode("utf-8"))
                merchant = payload.get("merchant", "")
                amount = float(payload.get("amount", 0))
                channel = payload.get("channel", "all")
                split = bool(payload.get("split", False))

                cards = [dict(row) for row in db.fetch_cards()]
                offers = [dict(row) for row in db.fetch_active_offers(merchant=merchant)]
                monthly = db.monthly_spend_by_card()
                rec = Recommender(cards=cards, offers=offers, monthly_spend=monthly)
                ranked = rec.suggest_split(amount=amount, merchant=merchant, channel=channel) if split else rec.recommend(amount=amount, merchant=merchant, channel=channel)
                ranked_dict = rec_to_dict(ranked)

                social = scanner.scan(merchant=merchant)
                refined_text = refiner.refine(
                    {
                        "merchant": merchant,
                        "amount": amount,
                        "channel": channel,
                        "split": split,
                        "recommendations": ranked_dict,
                        "community_insights": social.raw_items,
                    }
                )
                self._send_json(
                    {
                        "recommendations": ranked_dict,
                        "insights": {
                            "summary": social.summary,
                            "sources": social.sources,
                            "items": social.raw_items,
                        },
                        "refined_response": refined_text,
                    }
                )
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def log_message(self, format, *args):
            return

    return Handler


def run_web_server(db_path: str = "rewardmaximiser.db", host: str = "0.0.0.0", port: int = 8000) -> None:
    server = ThreadingHTTPServer((host, port), create_handler(db_path))
    print(f"Web UI running on http://{host}:{port}")
    server.serve_forever()

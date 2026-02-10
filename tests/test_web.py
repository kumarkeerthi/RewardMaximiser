from __future__ import annotations

import json
import threading
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from reward_agent.db import Database
from reward_agent.models import CreditCard, Offer
from reward_agent.web import create_handler
from http.server import ThreadingHTTPServer


def _start_server(db_path: str):
    server = ThreadingHTTPServer(("127.0.0.1", 0), create_handler(db_path))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.05)
    return server


def test_upload_cards_and_recommend(tmp_path):
    db_path = tmp_path / "test.db"
    server = _start_server(str(db_path))
    base = f"http://127.0.0.1:{server.server_port}"

    boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
    payload = json.dumps(
        [
            {
                "card_id": "hdfc-millennia",
                "bank": "HDFC",
                "network": "Visa",
                "reward_rate": 0.05,
                "monthly_reward_cap": 1200,
            }
        ]
    )
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="cards_file"; filename="cards.json"\r\n'
        "Content-Type: application/json\r\n\r\n"
        f"{payload}\r\n"
        f"--{boundary}--\r\n"
    ).encode("utf-8")
    req = Request(
        f"{base}/api/cards/upload",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    response = json.loads(urlopen(req).read().decode("utf-8"))
    assert response["count"] == 1

    db = Database(str(db_path))
    db.replace_offers(
        [
            Offer(
                offer_id="o1",
                card_id="hdfc-millennia",
                merchant="zomato",
                channel="zomato",
                discount_type="percent",
                discount_value=0.1,
                min_spend=100,
                max_discount=250,
                source="bank",
                active=1,
            )
        ],
        source="bank",
    )

    req = Request(
        f"{base}/api/recommend",
        data=json.dumps({"merchant": "zomato", "amount": 1000, "channel": "zomato", "split": False}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    result = json.loads(urlopen(req).read().decode("utf-8"))
    assert result["recommendations"][0]["card_id"] == "hdfc-millennia"
    assert "refined_response" in result
    server.shutdown()


def test_expense_route_accepts_category(tmp_path):
    db_path = tmp_path / "test-expense.db"
    db = Database(str(db_path))
    db.upsert_cards(
        [
            CreditCard(
                card_id="icici-amazon",
                bank="ICICI",
                network="Visa",
                reward_rate=0.03,
                monthly_reward_cap=1000,
            )
        ]
    )

    server = _start_server(str(db_path))
    base = f"http://127.0.0.1:{server.server_port}"
    form = urlencode({"card_id": "icici-amazon", "merchant": "dmart", "amount": "450", "category": "grocery"}).encode()
    req = Request(f"{base}/api/expenses", data=form, method="POST")
    opener = urlopen(req)
    assert opener.status == 200
    assert db.monthly_spend_by_card()["icici-amazon"] == 450.0
    server.shutdown()

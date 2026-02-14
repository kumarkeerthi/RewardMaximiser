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
    assert "merchant_insights" in result
    setup = json.loads(urlopen(f"{base}/api/setup-status").read().decode("utf-8"))
    assert setup["needs_setup"] is False
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


def test_add_and_remove_card_api(tmp_path):
    db_path = tmp_path / "test-cards.db"
    server = _start_server(str(db_path))
    base = f"http://127.0.0.1:{server.server_port}"

    req = Request(
        f"{base}/api/cards",
        data=json.dumps({
            "card_id": "axis-ace",
            "bank": "Axis",
            "network": "Visa",
            "reward_rate": 0.02,
            "monthly_reward_cap": 500,
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    added = json.loads(urlopen(req).read().decode("utf-8"))
    assert added["ok"] is True

    cards = json.loads(urlopen(f"{base}/api/cards").read().decode("utf-8"))["cards"]
    assert len(cards) == 1

    delete_req = Request(f"{base}/api/cards/axis-ace", method="DELETE")
    removed = json.loads(urlopen(delete_req).read().decode("utf-8"))
    assert removed["ok"] is True

    setup = json.loads(urlopen(f"{base}/api/setup-status").read().decode("utf-8"))
    assert setup["needs_setup"] is True
    server.shutdown()


def test_lifestyle_report_on_demand(tmp_path):
    db_path = tmp_path / "test-lifestyle.db"
    db = Database(str(db_path))
    db.upsert_cards(
        [
            CreditCard(
                card_id="hdfc-millennia",
                bank="HDFC",
                network="Visa",
                reward_rate=0.05,
                monthly_reward_cap=1200,
            )
        ]
    )
    db.add_expense(card_id="hdfc-millennia", merchant="swiggy", amount=900, category="dining")
    db.add_expense(card_id="hdfc-millennia", merchant="amazon", amount=1500, category="shopping")

    server = _start_server(str(db_path))
    base = f"http://127.0.0.1:{server.server_port}"

    req = Request(
        f"{base}/api/lifestyle-report/run",
        data=json.dumps({"selected_card": "hdfc millennia card"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    result = json.loads(urlopen(req).read().decode("utf-8"))["report"]
    assert "expense_pattern" in result
    assert "recommended_card" in result
    assert "selected_card_guide" in result

    snapshot = json.loads(urlopen(f"{base}/api/lifestyle-report").read().decode("utf-8"))["report"]
    assert snapshot.get("expense_pattern", {}).get("total_spend", 0) >= 2400
    server.shutdown()

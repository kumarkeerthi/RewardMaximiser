from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass(slots=True)
class InsightResult:
    summary: str
    sources: list[dict[str, str]]
    raw_items: list[dict[str, str]]


class SocialScanner:
    """Lightweight scanner for public community posts."""

    def __init__(self, timeout_s: float = 10.0) -> None:
        self.timeout_s = timeout_s

    def scan(self, merchant: str) -> InsightResult:
        merchant_query = merchant.strip() or "credit card offers"
        items: list[dict[str, str]] = []
        sources: list[dict[str, str]] = []

        reddit_items = self._scan_reddit(merchant_query)
        if reddit_items:
            items.extend(reddit_items)
            sources.append({"name": "Reddit", "url": f"https://www.reddit.com/search/?q={merchant_query}"})

        technofino_items = self._scan_technofino(merchant_query)
        if technofino_items:
            items.extend(technofino_items)
            sources.append({"name": "TechnoFino", "url": "https://www.technofino.in/community/"})

        summary = (
            f"Collected {len(items)} community mentions for '{merchant_query}' at "
            f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        )
        return InsightResult(summary=summary, sources=sources, raw_items=items)

    def _scan_reddit(self, query: str) -> list[dict[str, str]]:
        params = urlencode({"q": f"{query} credit card offer", "limit": 5, "sort": "new"})
        url = f"https://www.reddit.com/search.json?{params}"
        req = Request(url, headers={"User-Agent": "RewardMaximiser/1.0"})
        try:
            with urlopen(req, timeout=self.timeout_s) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (URLError, ValueError, TimeoutError):
            return []

        posts = payload.get("data", {}).get("children", [])
        results: list[dict[str, str]] = []
        for post in posts:
            data = post.get("data", {})
            permalink = data.get("permalink", "")
            results.append(
                {
                    "source": "reddit",
                    "title": data.get("title", "Untitled Reddit post"),
                    "snippet": data.get("selftext", "")[:220],
                    "url": f"https://www.reddit.com{permalink}" if permalink else "https://www.reddit.com",
                }
            )
        return results

    def _scan_technofino(self, query: str) -> list[dict[str, str]]:
        params = urlencode({"q": query, "o": "date"})
        url = f"https://www.technofino.in/community/search/search?{params}"
        req = Request(url, headers={"User-Agent": "RewardMaximiser/1.0"})
        try:
            with urlopen(req, timeout=self.timeout_s) as response:
                text = response.read().decode("utf-8")
        except (URLError, UnicodeDecodeError, TimeoutError):
            return []

        chunks = text.split('class="contentRow-title"')
        results: list[dict[str, str]] = []
        for chunk in chunks[1:6]:
            href_marker = 'href="'
            href_start = chunk.find(href_marker)
            if href_start == -1:
                continue
            href_start += len(href_marker)
            href_end = chunk.find('"', href_start)
            if href_end == -1:
                continue
            href = chunk[href_start:href_end]
            title_start = chunk.find(">", href_end)
            if title_start == -1:
                continue
            title_start += 1
            title_end = chunk.find("<", title_start)
            if title_end == -1:
                continue
            title = " ".join(chunk[title_start:title_end].split())
            if not title:
                continue
            results.append(
                {
                    "source": "technofino",
                    "title": title,
                    "snippet": "Community discussion thread",
                    "url": href if href.startswith("http") else f"https://www.technofino.in{href}",
                }
            )
        return results


class LLMRefiner:
    """Uses low-cost/free options when configured; otherwise falls back locally."""

    def __init__(self, timeout_s: float = 20.0) -> None:
        self.timeout_s = timeout_s

    def refine(self, context: dict[str, Any]) -> str:
        prompt = self._build_prompt(context)

        ollama_answer = self._ollama(prompt)
        if ollama_answer:
            return ollama_answer

        hf_answer = self._huggingface(prompt)
        if hf_answer:
            return hf_answer

        return self._fallback(context)

    def _build_prompt(self, context: dict[str, Any]) -> str:
        return (
            "You are a rewards optimization assistant. Summarize recommendations in bullet points "
            "with clear ordered card usage, caveats, and action items.\n"
            f"Context: {json.dumps(context, ensure_ascii=False)}"
        )

    def _post_json(self, url: str, payload: dict, headers: dict[str, str] | None = None) -> dict[str, Any] | list[Any] | None:
        req_headers = {"Content-Type": "application/json"}
        if headers:
            req_headers.update(headers)
        req = Request(url, data=json.dumps(payload).encode("utf-8"), headers=req_headers, method="POST")
        try:
            with urlopen(req, timeout=self.timeout_s) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception:
            return None

    def _ollama(self, prompt: str) -> str:
        model = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
        payload = self._post_json(
            "http://127.0.0.1:11434/api/generate",
            {"model": model, "prompt": prompt, "stream": False},
        )
        if isinstance(payload, dict):
            return str(payload.get("response", "")).strip()
        return ""

    def _huggingface(self, prompt: str) -> str:
        api_key = os.getenv("HF_API_KEY")
        model = os.getenv("HF_MODEL", "mistralai/Mistral-7B-Instruct-v0.2")
        if not api_key:
            return ""
        payload = self._post_json(
            f"https://api-inference.huggingface.co/models/{model}",
            {"inputs": prompt, "parameters": {"max_new_tokens": 250}},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        if isinstance(payload, list) and payload:
            return str(payload[0].get("generated_text", "")).strip()
        return ""

    def _fallback(self, context: dict[str, Any]) -> str:
        ranked_cards = context.get("recommendations", [])
        top_lines = []
        for idx, card in enumerate(ranked_cards[:3], start=1):
            top_lines.append(
                f"{idx}. Use {card['card_id']} first (~₹{card['savings']:.2f} savings, reason: {card['reason']})."
            )
        notes = [
            "No external LLM configured/reachable, so this is a local deterministic summary.",
            "Set OLLAMA_MODEL with a running local Ollama server or HF_API_KEY for Hugging Face Inference.",
        ]
        return "\n".join(top_lines + [""] + notes)

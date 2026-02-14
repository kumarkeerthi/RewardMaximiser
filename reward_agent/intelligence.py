from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
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

        x_items = self._scan_x(merchant_query)
        if x_items:
            items.extend(x_items)
            sources.append({"name": "X.com", "url": f"https://x.com/search?q={merchant_query}"})

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

    def _scan_x(self, query: str) -> list[dict[str, str]]:
        # Public search HTML frequently blocks scraping; use Nitter RSS mirror as a best-effort source.
        params = urlencode({"f": "tweets", "q": f"{query} credit card offer"})
        url = f"https://nitter.net/search/rss?{params}"
        req = Request(url, headers={"User-Agent": "RewardMaximiser/1.0"})
        try:
            with urlopen(req, timeout=self.timeout_s) as response:
                text = response.read().decode("utf-8", errors="ignore")
        except (URLError, UnicodeDecodeError, TimeoutError):
            return []

        items = text.split("<item>")
        results: list[dict[str, str]] = []
        for item in items[1:6]:
            title_match = re.search(r"<title>(.*?)</title>", item, flags=re.DOTALL)
            link_match = re.search(r"<link>(.*?)</link>", item, flags=re.DOTALL)
            desc_match = re.search(r"<description>(.*?)</description>", item, flags=re.DOTALL)
            if not title_match or not link_match:
                continue
            results.append(
                {
                    "source": "x",
                    "title": unescape(title_match.group(1).strip()),
                    "snippet": unescape((desc_match.group(1).strip() if desc_match else ""))[:220],
                    "url": link_match.group(1).strip(),
                }
            )
        return results


class LocalResearchAgent:
    """Best-effort local web intelligence layer for cards, offers, and merchant context."""

    CARD_DIRECTORY_SOURCES = [
        "https://www.hdfcbank.com/personal/pay/cards",
        "https://www.sbicard.com/en/personal/credit-cards.page",
        "https://www.icicibank.com/personal-banking/cards/credit-card",
        "https://www.axisbank.com/retail/cards/credit-card",
    ]

    BANK_OFFER_SOURCES = [
        "https://www.hdfcbank.com/personal/pay/cards/credit-cards/offers",
        "https://www.sbicard.com/en/offers.page",
        "https://www.icicibank.com/personal-banking/offers",
        "https://www.axisbank.com/retail/cards/credit-card/offers-and-benefits",
    ]

    def __init__(self, scanner: SocialScanner | None = None, timeout_s: float = 10.0) -> None:
        self.timeout_s = timeout_s
        self.scanner = scanner or SocialScanner(timeout_s=timeout_s)

    def discover_cards(self) -> list[dict[str, str]]:
        discovered: list[dict[str, str]] = []
        seen = set()
        for url in self.CARD_DIRECTORY_SOURCES:
            html = self._fetch_text(url)
            if not html:
                continue
            for name in self._extract_card_names(html):
                key = name.lower()
                if key in seen:
                    continue
                seen.add(key)
                discovered.append({"name": name, "source": url})
            if len(discovered) >= 40:
                break
        return discovered

    def run_daily_scan(self) -> dict[str, Any]:
        community = self.scanner.scan("credit card rewards")
        bank_offers: list[dict[str, str]] = []
        for url in self.BANK_OFFER_SOURCES:
            html = self._fetch_text(url)
            if not html:
                continue
            snippets = self._extract_offer_snippets(html)
            bank_offers.extend({"source": url, "snippet": text} for text in snippets)

        reward_sites = self._scan_reward_sites()
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "community": {
                "summary": community.summary,
                "sources": community.sources,
                "items": community.raw_items,
            },
            "bank_and_reward_mentions": bank_offers + reward_sites,
        }

    def scan_merchant(self, merchant_url: str) -> dict[str, Any]:
        if not merchant_url:
            return {"url": "", "title": "", "hints": []}
        html = self._fetch_text(merchant_url)
        if not html:
            return {"url": merchant_url, "title": "", "hints": []}

        title_match = re.search(r"<title>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
        title = unescape(title_match.group(1)).strip() if title_match else ""
        text = unescape(re.sub(r"<[^>]+>", " ", html.lower()))
        hints = []
        for token in ["visa", "mastercard", "amex", "rupay", "hdfc", "icici", "axis", "sbi"]:
            if token in text:
                hints.append(token)
        return {"url": merchant_url, "title": title, "hints": sorted(set(hints))}

    def _scan_reward_sites(self) -> list[dict[str, str]]:
        reward_sources = [
            "https://www.cardexpert.in/category/credit-cards/",
            "https://offers.smartbuy.hdfcbank.com/",
        ]
        collected: list[dict[str, str]] = []
        for url in reward_sources:
            html = self._fetch_text(url)
            if not html:
                continue
            for snippet in self._extract_offer_snippets(html)[:5]:
                collected.append({"source": url, "snippet": snippet})
        return collected

    def _fetch_text(self, url: str) -> str:
        req = Request(url, headers={"User-Agent": "RewardMaximiser/1.0"})
        try:
            with urlopen(req, timeout=self.timeout_s) as response:
                return response.read().decode("utf-8", errors="ignore")
        except (URLError, TimeoutError, ValueError):
            return ""

    def _extract_card_names(self, html: str) -> list[str]:
        text = unescape(re.sub(r"<[^>]+>", " ", html))
        pattern = re.compile(r"([A-Z][A-Za-z0-9&\-\s]{2,60}(?:Card|CARD))")
        names = []
        seen = set()
        for match in pattern.findall(text):
            normalized = " ".join(match.split())
            if len(normalized) < 6:
                continue
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            names.append(normalized)
            if len(names) >= 25:
                break
        return names

    def _extract_offer_snippets(self, html: str) -> list[str]:
        text = unescape(re.sub(r"<[^>]+>", " ", html))
        text = " ".join(text.split())
        chunks = re.split(r"(?<=[.!?])\s+", text)
        snippets = []
        for chunk in chunks:
            lower = chunk.lower()
            if any(k in lower for k in ["offer", "cashback", "reward", "points", "discount"]):
                snippets.append(chunk[:220])
            if len(snippets) >= 10:
                break
        return snippets


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
            "You are a local-first rewards optimization assistant. Summarize recommendations in bullet points "
            "with ordered card usage, caveats, and action items. Prefer local signals first.\n"
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
        merchant = context.get("merchant_insights", {})
        if merchant.get("hints"):
            top_lines.append(f"Merchant site hints seen: {', '.join(merchant['hints'])}.")
        notes = [
            "No external LLM configured/reachable, so this is a local deterministic summary.",
            "Set OLLAMA_MODEL with a running local Ollama server or HF_API_KEY for Hugging Face Inference.",
        ]
        return "\n".join(top_lines + [""] + notes)


class IndianCardLifestyleAgent:
    """Weekly/on-demand lifestyle analysis for Indian credit card choices."""

    FEATURE_TOKENS = {
        "cashback": ["cashback", "cash back"],
        "travel": ["travel", "air miles", "airmile", "flight"],
        "lounge": ["lounge", "airport"],
        "dining": ["dining", "restaurant", "swiggy", "zomato"],
        "fuel": ["fuel", "petrol", "diesel"],
        "shopping": ["shopping", "ecommerce", "amazon", "flipkart"],
        "lifestyle": ["lifestyle", "movie", "entertainment"],
    }

    POSITIVE_TOKENS = ["good", "great", "best", "worth", "useful", "easy", "love", "benefit"]
    NEGATIVE_TOKENS = ["bad", "poor", "worst", "delay", "issue", "devalue", "hidden", "fee"]

    def __init__(self, local_agent: LocalResearchAgent, scanner: SocialScanner) -> None:
        self.local_agent = local_agent
        self.scanner = scanner

    def build_weekly_report(self, expenses: list[dict[str, Any]], selected_card: str = "") -> dict[str, Any]:
        pattern = self._expense_pattern(expenses)
        discovered = self.local_agent.discover_cards()
        if not discovered:
            return {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "expense_pattern": pattern,
                "candidates": [],
                "recommended_card": {},
                "selected_card_guide": self._usage_guide({}, pattern),
            }

        daily_snapshot = self.local_agent.run_daily_scan()
        candidates: list[dict[str, Any]] = []
        for item in discovered[:20]:
            name = item.get("name", "").strip()
            if not name:
                continue
            features = self._infer_features(name=name, source=item.get("source", ""), daily_snapshot=daily_snapshot)
            reviews = self.scanner.scan(name)
            candidates.append(self._candidate_analysis(name=name, source=item.get("source", ""), features=features, reviews=reviews, pattern=pattern))

        candidates.sort(key=lambda row: row.get("fit_score", 0.0), reverse=True)
        recommendation = candidates[0] if candidates else {}
        selected = self._resolve_selected(selected_card, candidates)
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "expense_pattern": pattern,
            "candidates": candidates[:5],
            "recommended_card": recommendation,
            "selected_card_guide": self._usage_guide(selected, pattern),
        }

    def _expense_pattern(self, expenses: list[dict[str, Any]]) -> dict[str, Any]:
        if not expenses:
            return {"total_spend": 0.0, "avg_ticket": 0.0, "top_categories": [], "top_merchants": []}
        total = sum(float(row.get("amount", 0.0)) for row in expenses)
        avg = total / max(len(expenses), 1)
        by_category: dict[str, float] = {}
        by_merchant: dict[str, float] = {}
        for row in expenses:
            category = (row.get("category") or "other").strip().lower()
            merchant = (row.get("merchant") or "unknown").strip().lower()
            amount = float(row.get("amount", 0.0))
            by_category[category] = by_category.get(category, 0.0) + amount
            by_merchant[merchant] = by_merchant.get(merchant, 0.0) + amount
        top_categories = sorted(by_category.items(), key=lambda x: x[1], reverse=True)[:3]
        top_merchants = sorted(by_merchant.items(), key=lambda x: x[1], reverse=True)[:3]
        return {
            "total_spend": round(total, 2),
            "avg_ticket": round(avg, 2),
            "top_categories": [{"name": key, "amount": round(value, 2)} for key, value in top_categories],
            "top_merchants": [{"name": key, "amount": round(value, 2)} for key, value in top_merchants],
        }

    def _infer_features(self, name: str, source: str, daily_snapshot: dict[str, Any]) -> list[str]:
        text = f"{name} {source}"
        for row in daily_snapshot.get("bank_and_reward_mentions", []):
            snippet = str(row.get("snippet", ""))
            if name.lower().split()[0] in snippet.lower():
                text += f" {snippet}"
        lowered = text.lower()
        features: list[str] = []
        for feature, variants in self.FEATURE_TOKENS.items():
            if any(token in lowered for token in variants):
                features.append(feature)
        return sorted(set(features))

    def _candidate_analysis(self, name: str, source: str, features: list[str], reviews: InsightResult, pattern: dict[str, Any]) -> dict[str, Any]:
        review_text = " ".join(f"{item.get('title', '')} {item.get('snippet', '')}" for item in reviews.raw_items).lower()
        pos = sum(review_text.count(token) for token in self.POSITIVE_TOKENS)
        neg = sum(review_text.count(token) for token in self.NEGATIVE_TOKENS)
        sentiment = pos - neg

        top_categories = [row["name"] for row in pattern.get("top_categories", [])]
        fit_score = float(sentiment)
        if "dining" in features and any(cat in {"dining", "food"} for cat in top_categories):
            fit_score += 3
        if "travel" in features and any(cat in {"travel", "transport"} for cat in top_categories):
            fit_score += 3
        if "shopping" in features and any(cat in {"shopping", "grocery"} for cat in top_categories):
            fit_score += 2
        if "cashback" in features:
            fit_score += 1

        annual_fee = 4999.0 if "travel" in features and "lounge" in features else (999.0 if "lounge" in features else 500.0)
        expected_extra = annual_fee / 12.0

        pros = []
        cons = []
        if "cashback" in features:
            pros.append("Strong cashback-driven value for regular spend")
        if "dining" in features:
            pros.append("Dining/food-order relevance aligns with lifestyle spend")
        if "travel" in features or "lounge" in features:
            pros.append("Travel-related upside through miles/lounge style benefits")
        if not pros:
            pros.append("General-purpose benefits from mainstream issuer category")

        if neg > pos:
            cons.append("Community sentiment shows more complaints than praise")
        cons.append(f"Potential monthly cost impact around ₹{expected_extra:.0f} from annual fee")

        return {
            "card_name": name,
            "source": source,
            "features": features,
            "reviews": {
                "summary": reviews.summary,
                "sources": reviews.sources,
                "sample_size": len(reviews.raw_items),
            },
            "pros": pros,
            "cons": cons,
            "fit_score": round(fit_score, 2),
            "estimated_monthly_extra_expense": round(expected_extra, 2),
            "estimated_annual_fee": annual_fee,
        }

    def _resolve_selected(self, selected_card: str, candidates: list[dict[str, Any]]) -> dict[str, Any]:
        if not selected_card:
            return candidates[0] if candidates else {}
        target = selected_card.strip().lower()
        for row in candidates:
            if row.get("card_name", "").lower() == target:
                return row
        return candidates[0] if candidates else {}

    def _usage_guide(self, selected: dict[str, Any], pattern: dict[str, Any]) -> list[str]:
        if not selected:
            return ["No selected card available yet. Run weekly scan after adding expense entries."]
        tips = [
            f"Use {selected.get('card_name', 'this card')} for categories where it has strong features: {', '.join(selected.get('features', []) or ['general spend'])}.",
            "Autopay total due to avoid finance charges that wipe out reward gains.",
            "Track monthly statement and reward caps; shift overflow spend to your backup card.",
        ]
        top_categories = pattern.get("top_categories", [])
        if top_categories:
            tips.append(f"Prioritize this card for your top category '{top_categories[0]['name']}' first, then use other cards for non-bonus categories.")
        return tips

# RewardMaximiser Agent

A local agent for credit-card offer tracking, expense tracking, social-offer scanning, and payment recommendation with a web UI.

## What it does

- Ingests your wallet (`cards.sample.json` format) and stores it in SQLite.
- Pulls offers from multiple sources (bank websites, social channels, and an OpenClaw adapter).
- Refreshes all offers every 2 days using a daemon mode.
- Recommends the best card for an upcoming purchase.
- Suggests split payment across cards to maximize total benefit.
- Tracks expenses with merchant + category to keep monthly reward caps in check.
- Web UI to upload card lists, record expenses, and process ordered card recommendations.
- Scans community mentions from Reddit and TechnoFino for additional context.
- Refines recommendation text with free-friendly LLM options:
  - Local Ollama (`OLLAMA_MODEL`, default `llama3.1:8b`)
  - Hugging Face Inference (`HF_API_KEY`, `HF_MODEL`)
  - Local deterministic fallback summary (always available)

## Architecture

- `agent.py`: CLI entrypoint.
- `reward_agent/web.py`: stdlib HTTP web app + API endpoints.
- `reward_agent/intelligence.py`: social scan + LLM refinement integration.
- `reward_agent/db.py`: SQLite schema and persistence.
- `reward_agent/providers.py`: pluggable offer-provider interface.
- `reward_agent/recommender.py`: optimization logic for best-card and split suggestions.
- `reward_agent/refresh.py`: refresh orchestration + 2-day scheduler loop.

## Quick start (CLI)

```bash
python agent.py sync-cards --cards data/cards.sample.json
python agent.py --bank-offers data/bank_offers.sample.json --social-offers data/social_offers.sample.json refresh
python agent.py recommend --merchant zomato --amount 1500 --channel zomato
python agent.py recommend --merchant swiggy --amount 1800 --channel swiggy --split
python agent.py record-expense --card-id sbi-cashback --merchant swiggy --amount 700 --category dining
```

## Run the web app (Chrome friendly)

```bash
python -m pip install -e .
python agent.py sync-cards --cards data/cards.sample.json
python agent.py --bank-offers data/bank_offers.sample.json --social-offers data/social_offers.sample.json refresh
python agent.py web --host 0.0.0.0 --port 8000
```

Then open `http://localhost:8000` in Chrome.

### Web features

- **Recommendations page**:
  - Upload card list JSON/CSV.
  - Enter merchant, amount, channel, and split-payment toggle.
  - See ordered card suggestions with savings.
  - Get LLM-refined explanation.
  - View Reddit + TechnoFino community links and mentions.
- **Expenses page**:
  - Record expense by card, merchant, amount, and category dropdown.

## LLM setup

### Option 1: local Ollama (free)

```bash
# run Ollama separately
export OLLAMA_MODEL=llama3.1:8b
```

### Option 2: Hugging Face Inference (free tier limits apply)

```bash
export HF_API_KEY=your_token
export HF_MODEL=mistralai/Mistral-7B-Instruct-v0.2
```

If neither is configured/reachable, the app still returns a deterministic local summary.

## Daemon mode

```bash
python agent.py --bank-offers data/bank_offers.sample.json --social-offers data/social_offers.sample.json daemon
```

## Extending with OpenClaw

Implement `OpenClawProvider.fetch_offers()` in `reward_agent/providers.py` to:

1. Authenticate and crawl bank offer pages.
2. Crawl social media posts for limited-time campaign codes.
3. Normalize each offer into the `Offer` dataclass.
4. Return the normalized list so the refresh pipeline can persist it.

# RewardMaximiser Agent

A local agent for credit-card offer tracking and payment recommendation.

## What it does

- Ingests your wallet (`cards.sample.json` format) and stores it in SQLite.
- Pulls offers from multiple sources (bank websites, social channels, and an OpenClaw adapter).
- Refreshes all offers every 2 days using a daemon mode.
- Recommends the best card for an upcoming purchase.
- Can suggest split payment across cards to maximize total benefit.
- Tracks expenses to keep monthly reward caps in check.
- Supports dining/payment channel decisions across Zomato, Swiggy, EazyDiner, and Magicpin.

## Architecture

- `agent.py`: CLI entrypoint.
- `reward_agent/db.py`: SQLite schema and persistence.
- `reward_agent/providers.py`: pluggable offer-provider interface.
  - `JsonOfferProvider`: current working provider for bank/social dumps.
  - `OpenClawProvider`: adapter stub where OpenClaw (or another framework) scraping workflows can be wired.
- `reward_agent/recommender.py`: optimization logic for best-card and split suggestions.
- `reward_agent/refresh.py`: refresh orchestration + 2-day scheduler loop.

## Quick start

```bash
python agent.py sync-cards --cards data/cards.sample.json
python agent.py --bank-offers data/bank_offers.sample.json --social-offers data/social_offers.sample.json refresh
python agent.py recommend --merchant zomato --amount 1500 --channel zomato
python agent.py recommend --merchant swiggy --amount 1800 --channel swiggy --split
python agent.py record-expense --card-id sbi-cashback --merchant swiggy --amount 700 --category dining
```

Run as daemon (refresh every 2 days):

```bash
python agent.py --bank-offers data/bank_offers.sample.json --social-offers data/social_offers.sample.json daemon
```

## Extending with OpenClaw

Implement `OpenClawProvider.fetch_offers()` in `reward_agent/providers.py` to:

1. Authenticate and crawl bank offer pages.
2. Crawl social media posts for limited-time campaign codes.
3. Normalize each offer into the `Offer` dataclass.
4. Return the normalized list so the refresh pipeline can persist it.


from reward_agent.recommender import Recommender


def test_recommend_prefers_offer():
    cards = [
        {"card_id": "a", "monthly_reward_cap": 1000.0, "reward_rate": 0.02},
        {"card_id": "b", "monthly_reward_cap": 1000.0, "reward_rate": 0.05},
    ]
    offers = [
        {
            "card_id": "a",
            "merchant": "zomato",
            "channel": "zomato",
            "discount_type": "percent",
            "discount_value": 0.2,
            "min_spend": 200,
            "max_discount": 500,
            "source": "bank",
        }
    ]
    rec = Recommender(cards, offers, monthly_spend={})
    result = rec.recommend(amount=1000, merchant="zomato", channel="zomato")
    assert result[0].card_id == "a"


def test_split_allocates_full_amount():
    cards = [
        {"card_id": "a", "monthly_reward_cap": 1000.0, "reward_rate": 0.02},
        {"card_id": "b", "monthly_reward_cap": 1000.0, "reward_rate": 0.01},
    ]
    offers = []
    rec = Recommender(cards, offers, monthly_spend={})
    split = rec.suggest_split(amount=1200, merchant="restaurant", channel="all")
    assert round(sum(x.amount for x in split), 2) == 1200

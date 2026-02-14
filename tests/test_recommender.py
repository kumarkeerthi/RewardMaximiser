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


def test_recommend_uses_dynamic_card_features():
    cards = [
        {
            "card_id": "base",
            "monthly_reward_cap": 1000.0,
            "reward_rate": 0.02,
            "category_multipliers": "{}",
            "channel_multipliers": "{}",
            "merchant_multipliers": "{}",
            "annual_fee": 0,
        },
        {
            "card_id": "dynamic",
            "monthly_reward_cap": 1000.0,
            "reward_rate": 0.01,
            "category_multipliers": '{"dining": 0.06}',
            "channel_multipliers": '{"online": 0.08}',
            "merchant_multipliers": '{"zomato": 0.10}',
            "annual_fee": 0,
            "milestone_spend": 5000,
            "milestone_bonus": 100,
        },
    ]
    rec = Recommender(cards, offers=[], monthly_spend={"dynamic": 4900})
    result = rec.recommend(amount=500, merchant="zomato", channel="online", category="dining")
    assert result[0].card_id == "dynamic"
    assert result[0].savings > result[1].savings

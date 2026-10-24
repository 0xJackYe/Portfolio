"""Reproduce an illustrative margin calculation from a public market snapshot.

No credentials, account access, orders, or dashboard changes.
The 1,000 USDT empty account is an assumption, not a verified account balance.
"""
import json
import math
from pathlib import Path

OBSERVATION = {
    "symbol": "BTC-261127-60000-P",
    "snapshot_time_beijing": "2026-10-23T22:37:50.898+08:00",
    "source": "http://127.0.0.1:8766/api/market (Binance public market feed)",
    "spot": 81697.09934783,
    "strike": 60000.0,
    "bid": 140.0,
    "ask": 145.0,
    "mark": 141.785,
    "iv": 0.546,
    "days": 34.723662,
    "unit": 1,
    "quantity_step": 0.01,
    "bid_quantity": 66.85,
    "expiry_beijing": "2026-11-27T16:00:00+08:00",
}
BALANCE = 1000.0
S, K, BID, MARK = (OBSERVATION[k] for k in ("spot", "strike", "bid", "mark"))
T = OBSERVATION["days"] / 365
ENTRY_FEE = min(0.00024 * S, 0.1 * BID)


def base(spot, initial=False):
    otm = max(spot - K, 0)
    return max((0.10 if initial else 0.05) * spot,
               (0.15 if initial else 0.075) * spot - otm)


def maintenance(spot, mark, quantity):
    # Current Clearing Procedures 28 includes a liquidation-fee reserve.
    return (base(spot) + mark + 0.0019 * spot) * quantity


def adjusted_equity(quantity):
    # Only this short Put, retained premium, no withdrawals or other positions.
    return BALANCE + (BID - ENTRY_FEE) * quantity


def order_margin(quantity):
    return (max(0, base(S, initial=True) + MARK - BID) + ENTRY_FEE) * quantity


def put_price(spot, iv, years):
    # Zero-rate/zero-carry European lognormal illustration; not Binance's model.
    if years <= 0:
        return max(K - spot, 0)
    normal = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))
    width = iv * math.sqrt(years)
    d1 = math.log(spot / K) / width + width / 2
    d2 = d1 - width
    return K * normal(-d2) - spot * normal(-d1)


BASIS = MARK - put_price(S, OBSERVATION["iv"], T)


def estimate_mark(spot, iv):
    return max(max(K - spot, 0), min(K, put_price(spot, iv, T) + BASIS))


def calculate():
    maximum = math.floor(BALANCE / order_margin(1) / 0.01) * 0.01
    while order_margin(maximum) >= BALANCE:
        maximum = round(maximum - 0.01, 2)
    sizes = []
    for quantity in (0.01, 0.02, 0.03, 0.06, maximum):
        sizes.append({
            "quantity": quantity,
            "order_margin": order_margin(quantity),
            "position_initial_margin": (base(S, True) + MARK) * quantity,
            "gross_premium": BID * quantity,
            "entry_fee": ENTRY_FEE * quantity,
            "net_premium": (BID - ENTRY_FEE) * quantity,
            "adjusted_equity": adjusted_equity(quantity),
            "available_after_entry": BALANCE - order_margin(quantity),
            "maintenance_margin": maintenance(S, MARK, quantity),
            "margin_ratio": maintenance(S, MARK, quantity) / adjusted_equity(quantity),
            "maximum_expiry_loss_including_entry_fee": (K - BID + ENTRY_FEE) * quantity,
        })
    scenarios = []
    for spot, iv in ((S, .546), (62000, .546), (62000, .80), (58000, .546), (S, 1.50)):
        mark = estimate_mark(spot, iv)
        scenarios.append({"spot": spot, "iv": iv, "estimated_mark": mark,
                          "margin_ratios": {str(q): maintenance(spot, mark, q) / adjusted_equity(q)
                                            for q in (.01, .03, maximum)}})
    threshold_marks = [{"spot": s, "mark_at_95_percent":
                        .95 * adjusted_equity(maximum) / maximum - base(s) - .0019 * s}
                       for s in (S, 70000, 62000, 60000, 58000)]
    assert order_margin(maximum) < BALANCE < order_margin(round(maximum + .01, 2))
    assert abs(estimate_mark(S, OBSERVATION["iv"]) - MARK) < 1e-9
    for threshold in threshold_marks:
        assert abs(maintenance(threshold["spot"], threshold["mark_at_95_percent"], maximum)
                   / adjusted_equity(maximum) - .95) < 1e-12
    assert scenarios[1]["margin_ratios"][str(maximum)] < .8
    assert scenarios[2]["margin_ratios"][str(maximum)] > .95
    assert scenarios[3]["margin_ratios"]["0.01"] < .1
    return {"observation": OBSERVATION, "assumed_empty_account_usdt": BALANCE,
            "sources": ["https://www.binance.com/en/about-legal/clearing-procedures",
                        "https://www.binance.com/en/support/faq/detail/1ceb77f837344e3085ecf98d9a6a8097",
                        "https://www.binance.com/en/support/faq/detail/5326e5de61c34fed98abe28d2f175a23"],
            "assumptions": ["Ordinary options long/short account; one short Put only; no orders/other holdings",
                            "All premium retained; baseline fee, no discounts; no funding/withdrawals",
                            "Stress holds remaining time fixed at 34.723662 days; hypothetical immediate shocks",
                            "Stress uses zero-rate European lognormal repricing anchored to observed mark",
                            "No actual account validation; stress values are not precise liquidation prices"],
            "maximum_admitted_quantity_estimate": maximum, "sizes": sizes,
            "stress_scenarios": scenarios, "conditional_mark_thresholds": threshold_marks}


if __name__ == "__main__":
    result = calculate()
    Path(__file__).with_name("results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))

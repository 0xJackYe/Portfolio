"""Read-only comparison of one BTC Put expiry; no account or order endpoints."""
import argparse
import csv
import datetime as dt
import json
import math
from pathlib import Path
from statistics import NormalDist
import urllib.request

ROOT = Path(__file__).resolve().parent
N = NormalDist()
QTY = 0.01
ENTRY_RATE = 0.00024
EXERCISE_RATE = 0.00015
EXERCISE_CAP = 0.1


def exercise_fee(s, k):
    return min(EXERCISE_RATE * s, EXERCISE_CAP * max(k-s, 0))


def breakeven(k, net_credit):
    low, high = 0.0, k
    for _ in range(90):
        middle = (low+high)/2
        if net_credit-max(k-middle, 0)-exercise_fee(middle, k) < 0:
            low = middle
        else:
            high = middle
    return (low+high)/2


def distribution(s, k, years, sigma, mu, credit):
    """All monetary results are per 1 BTC. Common physical models use mu=0."""
    m = math.log(s) + (mu-0.5*sigma*sigma)*years
    v = sigma*math.sqrt(years)
    mean_s = math.exp(m+0.5*v*v)

    def probability(x):
        return 0.0 if x <= 0 else N.cdf((math.log(x)-m)/v)

    def truncated_price(x):
        return 0.0 if x <= 0 else mean_s*N.cdf((math.log(x)-m-v*v)/v)

    def expected_payout(cut=math.inf):
        bound = min(k, cut)
        return k*probability(bound)-truncated_price(bound)

    def expected_fee(cut=math.inf):
        crossover = EXERCISE_CAP*k/(EXERCISE_RATE+EXERCISE_CAP)
        first = min(crossover, cut)
        result = EXERCISE_RATE*truncated_price(first)
        upper = min(k, cut)
        if upper > crossover:
            result += EXERCISE_CAP*(k*(probability(upper)-probability(crossover))
                       - (truncated_price(upper)-truncated_price(crossover)))
        return max(result, 0.0)

    be = breakeven(k, credit)
    result = {"expected_payout": expected_payout(), "expected_exercise_fee": expected_fee(),
              "ev": credit-expected_payout()-expected_fee(), "loss_probability": probability(be)}
    for tail, label in ((0.05, "95"), (0.01, "99")):
        quantile = math.exp(m+v*N.inv_cdf(tail))
        result["var"+label] = max(0.0, max(k-quantile, 0)+exercise_fee(quantile, k)-credit)
        # Positive loss only, so a remote put has ES=0 if the modeled tail never loses.
        cap = min(quantile, be)
        tail_loss = expected_payout(cap)+expected_fee(cap)-credit*probability(cap)
        result["es"+label] = max(0.0, tail_loss/tail)
    return result


def historical_scenario(s, k, credit, returns):
    values = [credit-max(k-s*(1+ret), 0)-exercise_fee(s*(1+ret), k) for ret in returns]
    losses = sorted([max(-value, 0) for value in values], reverse=True)
    losses_count = sum(value < 0 for value in values)
    winning = [value for value in values if value > 0]
    losing = [-value for value in values if value < 0]
    return {"ev": sum(values)/len(values), "loss_frequency": losses_count/len(values),
            "es95": sum(losses[:math.ceil(0.05*len(losses))])/math.ceil(0.05*len(losses)),
            "es99": sum(losses[:math.ceil(0.01*len(losses))])/math.ceil(0.01*len(losses)),
            "average_gain": sum(winning)/len(winning) if winning else 0,
            "average_loss": sum(losing)/len(losing) if losing else 0}


def analyze(snapshot, history):
    s = float(snapshot["btc_index_price"])
    now = snapshot["server_now_ms"]
    clock_offset = snapshot["exchange_clock_offset_ms"]
    raw_marks = {row["symbol"]: row for row in snapshot["endpoints"]["mark"].get("data", [])}
    contracts = {row["symbol"]: row for row in snapshot["endpoints"]["exchange_info"].get("data", {}).get("optionSymbols", [])}
    hist_returns = history["sixteen_day_returns_latest_365_windows"]
    if hist_returns and isinstance(hist_returns[0], dict):
        hist_returns = [row["simple_return"] for row in hist_returns]
    rows = []
    for option in snapshot["options"]:
        if not option["symbol"].startswith("BTC-261030-") or option["side"] != "PUT":
            continue
        k, bid, ask = (float(option[key]) for key in ("strike_price", "bid_price", "ask_price"))
        iv, mark = float(option["mark_iv"]), float(option["mark_price"])
        years = (option["expiry_ms"]-now)/(365*86400000)
        bid_age = (now-clock_offset-option["field_updated_at"]["bid_price"])/1000
        mark_age = (now-clock_offset-option["field_updated_at"]["mark_iv"])/1000
        bid_size = float(option.get("bid_quantity") or 0)
        eligible = (option["status"] == "TRADING" and years > 0 and bid > 0 and ask >= bid
                    and bid_size >= QTY and 0 <= bid_age <= 10 and 0 <= mark_age <= 10)
        entry = min(ENTRY_RATE*s, 0.1*bid)
        credit = bid-entry
        rate = float(raw_marks.get(option["symbol"], {}).get("riskFreeInterest", 0))
        be = breakeven(k, credit)
        row = {"symbol": option["symbol"], "strike": k, "bid": bid, "ask": ask, "mark": mark,
               "iv": iv, "delta": float(option["delta"]), "gamma_api": float(option["gamma"]),
               "theta_api": float(option["theta"]), "vega_api": float(option["vega"]),
               "bid_size": bid_size, "volume_24h": float(option["volume_24h_contracts"]),
               "eligible_at_snapshot": eligible, "bid_age_seconds": bid_age, "mark_age_seconds": mark_age,
               "otm_pct": 100*(s-k)/s, "spread_pct_of_bid": 100*(ask-bid)/bid,
               "entry_fee_0_01": entry*QTY, "net_max_profit_0_01": credit*QTY,
               "breakeven_with_fees": be, "max_loss_0_01": (k-credit)*QTY,
               "period_credit_pct_full_cash": 100*credit/k,
               "max_profit_to_max_loss": credit/(k-credit), "risk_free_api": rate,
               "expiry_beijing": option["expiry_beijing"], "days": years*365}
        rn = distribution(s, k, years, iv, rate, credit)
        row["rn_local_iv_loss_probability"] = rn["loss_probability"]
        row["rn_local_iv_payout_present_value"] = math.exp(-rate*years)*rn["expected_payout"]
        row["mark_minus_local_bs"] = mark-row["rn_local_iv_payout_present_value"]
        # The IV-specific probabilities are pricing-model diagnostics, not a common real distribution.
        for sigma in (0.4, 0.6, 0.8):
            modeled = distribution(s, k, years, sigma, 0, credit)
            for key, value in modeled.items():
                row["sigma%d_%s" % (int(sigma*100), key)] = value if key == "loss_probability" else value*QTY
        empirical = historical_scenario(s, k, credit, hist_returns)
        for key, value in empirical.items():
            row["historical16d_recent365_"+key] = value if key == "loss_frequency" else value*QTY
        for pct in (10, 20, 30, 40):
            settlement = s*(1-pct/100)
            row["pnl_minus%d_0_01" % pct] = (credit-max(k-settlement, 0)-exercise_fee(settlement, k))*QTY
        rules = contracts.get(option["symbol"], {})
        initial = max(s*float(rules.get("minInitialMargin", 0.1)),
                      s*float(rules.get("initialMargin", 0.15))-max(s-k, 0))
        maintenance = max(s*float(rules.get("minMaintenanceMargin", 0.05)),
                          s*float(rules.get("maintenanceMargin", 0.075))-max(s-k, 0))
        row["indicative_position_initial_margin_0_01"] = (initial+mark)*QTY
        row["indicative_maintenance_margin_0_01"] = (maintenance+mark)*QTY
        row["quantity_budget_1000_max_terminal_loss"] = math.floor(1000/(k-credit)/0.01)*0.01
        rows.append(row)
    rows.sort(key=lambda row: row["strike"])
    metadata = {"source": "Binance public market data via the existing local read-only cache",
                "snapshot_beijing": dt.datetime.fromtimestamp(now/1000, dt.timezone(dt.timedelta(hours=8))).isoformat(),
                "spot_index": s, "quantity_comparison": QTY, "rows": len(rows),
                "eligible_rows": sum(row["eligible_at_snapshot"] for row in rows),
                "fee_rates": {"entry": ENTRY_RATE, "exercise": EXERCISE_RATE, "premium_or_intrinsic_cap": 0.1},
                "scenarios": "Common GBM mu=0, annualized sigma=40/60/80%; not true probability forecasts.",
                "historical_scenarios": "Most recent 365 overlapping historical 16-day simple returns, about 15.6-day expiry; descriptive, not independently validated forecasts.",
                "es_convention": "Mean positive loss in the worst 5% or 1% terminal scenarios; profits are clipped to zero. Not signed-P&L ES when the tail includes profits.",
                "rv": history["annualized_realized_volatility"],
                "limits": ["No account balance/margin access, liquidation path, funding return, tax or fee discount modeled.",
                           "Terminal spot is used as proxy for the 30-minute averaged settlement index.",
                           "Vega and theta kept as API raw units; no unverified Greek unit conversion.",
                           "IV-specific RN probabilities are not comparable physical forecasts or a complete arbitrage-free smile distribution.",
                           "Price/quantity at the snapshot is not an execution guarantee."]}
    return {"metadata": metadata, "rows": rows}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    if args.refresh:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open("http://127.0.0.1:8766/api/market", timeout=5) as response:
            snapshot = json.load(response)
        (ROOT/"snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
    else:
        snapshot = json.loads((ROOT/"snapshot.json").read_text(encoding="utf-8"))
    result = analyze(snapshot, json.loads((ROOT/"realized_vol.json").read_text(encoding="utf-8")))
    (ROOT/"results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    with (ROOT/"comparison.csv").open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(result["rows"][0]))
        writer.writeheader()
        writer.writerows(result["rows"])
    print(json.dumps(result["metadata"], ensure_ascii=False, indent=2))
    cols = ["strike", "bid", "iv", "delta", "net_max_profit_0_01", "breakeven_with_fees", "rn_local_iv_loss_probability",
            "sigma40_ev", "sigma60_ev", "sigma80_ev", "historical16d_recent365_ev", "sigma60_es99", "pnl_minus20_0_01", "pnl_minus30_0_01"]
    print(",".join(cols))
    for row in result["rows"]:
        if 58000 <= row["strike"] <= 82000:
            print(",".join("%.6g" % row[key] for key in cols))
    eligible = [row for row in result["rows"] if row["eligible_at_snapshot"] and row["otm_pct"] > 0]
    for name in ("sigma40_ev", "sigma60_ev", "sigma80_ev", "historical16d_recent365_ev"):
        print("top", name, [(row["strike"], round(row[name], 5)) for row in sorted(eligible, key=lambda row: row[name], reverse=True)[:5]])


if __name__ == "__main__":
    main()

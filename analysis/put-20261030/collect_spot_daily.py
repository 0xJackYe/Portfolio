"""Collect public Binance BTCUSDT daily candles for the Put comparison.

No account access or API credential is used. Retains the raw exchange payload.
"""
import datetime as dt
import json
import math
import pathlib
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent
BASE = "https://api.binance.com"
DAY_MS = 86_400_000


def utc_text(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).isoformat()


def public_get(path, params=None):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "local-btc-put-analysis/1.0"})
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                payload = json.load(response)
                return payload, {"url": url, "status": response.status, "date_header": response.headers.get("Date")}
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionResetError):
            if attempt:
                raise
            time.sleep(1)


def quantile(values, probability):
    ordered = sorted(values)
    idx = (len(ordered) - 1) * probability
    low = math.floor(idx)
    high = math.ceil(idx)
    return ordered[low] + (ordered[high] - ordered[low]) * (idx - low)


server, time_source = public_get("/api/v3/time")
asof_ms = int(server["serverTime"])
current_utc_day_open_ms = asof_ms // DAY_MS * DAY_MS
candles, candle_source = public_get("/api/v3/klines", {
    "symbol": "BTCUSDT", "interval": "1d", "endTime": current_utc_day_open_ms - 1, "limit": 731,
})
if not isinstance(candles, list) or len(candles) < 366:
    raise ValueError("Insufficient daily candle history from the public exchange endpoint")
if any(int(row[6]) >= current_utc_day_open_ms for row in candles):
    raise ValueError("The response unexpectedly includes an incomplete UTC daily candle")
if any(int(b[0]) - int(a[0]) != DAY_MS for a, b in zip(candles, candles[1:])):
    raise ValueError("Daily candle history has missing or duplicate intervals")
prices = [float(row[4]) for row in candles]
logs = [math.log(b / a) for a, b in zip(prices, prices[1:])]
simple_1d = [b / a - 1 for a, b in zip(prices, prices[1:])]
simple_16d = [prices[i + 16] / prices[i] - 1 for i in range(len(prices) - 16)]
latest_365_16d = [prices[i + 16] / prices[i] - 1 for i in range(max(0, len(prices) - 365 - 16), len(prices) - 16)]
raw = {
    "metadata": {
        "asof_server_time_ms": asof_ms, "asof_utc": utc_text(asof_ms),
        "source_time": time_source, "source_candles": candle_source,
        "symbol": "BTCUSDT", "interval": "1d", "quote_asset": "USDT",
        "excludes_incomplete_day": True, "count": len(candles),
        "first_open_utc": utc_text(int(candles[0][0])),
        "last_close_utc": utc_text(int(candles[-1][6])),
        "last_complete_close": prices[-1],
        "kline_columns": ["open_time_ms", "open", "high", "low", "close", "base_volume", "close_time_ms", "quote_volume", "number_of_trades", "taker_buy_base_volume", "taker_buy_quote_volume", "unused"],
    },
    "time_payload": server, "klines": candles,
}


def distribution(values):
    return {
        "sample_count": len(values), "mean": statistics.mean(values),
        "sample_std": statistics.stdev(values),
        "min": min(values), "max": max(values),
        "quantiles": {str(q): quantile(values, q) for q in [0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.975, 0.99]},
    }


summary = {
    "metadata": raw["metadata"],
    "realized_volatility_method": "sample stdev of UTC daily close-to-close log returns, annualized with sqrt(365); no mean drift adjustment beyond sample stdev", 
    "annualized_realized_volatility": {str(window): statistics.stdev(logs[-window:]) * math.sqrt(365) for window in [30, 60, 90, 180, 365]},
    "log_return_sample_count": len(logs),
    "one_day_simple_return_distribution": distribution(simple_1d),
    "sixteen_day_simple_return_distribution": distribution(simple_16d),
    "sixteen_day_simple_return_distribution_latest_365_windows": distribution(latest_365_16d),
    "sixteen_day_returns": simple_16d,
    "sixteen_day_returns_latest_365_windows": latest_365_16d,
    "one_day_log_returns": logs,
    "caveats": [
        "Rolling 16-day windows overlap; these observations are not independent and sample_count is not an independent observation count.",
        "Historical returns are physical-distribution scenarios, not forecasts or risk-neutral probabilities.",
        "USDT quote prices do not remove stablecoin basis risk versus USD-denominated option indices.",
        "UTC daily candles differ from Beijing calendar days. These complete UTC candles are used consistently for volatility estimation.",
        "The exact option horizon may differ from 16 complete days; scale or model the horizon explicitly when comparing options.",
    ],
}
ROOT.mkdir(parents=True, exist_ok=True)
(ROOT / "spot_daily.json").write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
(ROOT / "realized_vol.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"metadata": summary["metadata"], "annualized_realized_volatility": summary["annualized_realized_volatility"], "worst_one_day": min(simple_1d), "worst_sixteen_day": min(simple_16d), "sixteen_day_distribution": distribution(simple_16d)}, ensure_ascii=False, indent=2))

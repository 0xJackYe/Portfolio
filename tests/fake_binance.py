"""A deterministic stand-in for Binance's public options API and markPrice stream."""

import json
import math
import time

DAY = 86400000


def black_scholes(side, spot, strike, years, vol):
    if years <= 0:
        return max(0.0, spot - strike if side == "CALL" else strike - spot)
    sd = vol * math.sqrt(years)
    d1 = (math.log(spot / strike) + sd * sd / 2) / sd
    cdf = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))  # noqa: E731
    if side == "CALL":
        return spot * cdf(d1) - strike * cdf(d1 - sd)
    return strike * cdf(sd - d1) - spot * cdf(-d1)


class FakeBinance:
    """Answers market.fetch_json-style calls with a small, realistic BTC options board."""

    def __init__(self, index=80000.0, days=(2, 30), strikes=(60000, 70000, 80000, 90000, 100000), now_ms=None):
        self.now_ms = int(time.time() * 1000) if now_ms is None else now_ms
        self.index = index
        self.expiries = [self.now_ms + int(d * DAY) for d in days]
        self.strikes = strikes
        self.calls = []
        self.fail = None          # an exception for fetch to raise
        self.weight = 10          # X-MBX-USED-WEIGHT-1M reported with each response
        self.extra_symbols = []   # additional raw exchangeInfo entries

    @staticmethod
    def symbol(expiry, strike, side):
        return "BTC-%s-%d-%s" % (time.strftime("%y%m%d", time.gmtime(expiry / 1000)), strike, side[0])

    def board(self):
        for expiry in self.expiries:
            for strike in self.strikes:
                for side in ("CALL", "PUT"):
                    yield expiry, strike, side

    def prices(self, expiry, strike, side):
        mark = black_scholes(side, self.index, strike, (expiry - self.now_ms) / DAY / 365, 0.5)
        return mark, math.floor(mark * 0.98 / 5) * 5, math.ceil(mark * 1.02 / 5) * 5

    def exchange_info(self):
        symbols = [{"symbol": self.symbol(e, k, s), "side": s, "strikePrice": "%.3f" % k, "expiryDate": e,
                    "underlying": "BTCUSDT", "unit": 1, "minQty": "0.01", "status": "TRADING",
                    "quoteAsset": "USDT", "priceScale": 3, "quantityScale": 2} for e, k, s in self.board()]
        return {"timezone": "UTC", "serverTime": self.now_ms, "optionSymbols": symbols + self.extra_symbols}

    def mark(self):
        return [{"symbol": self.symbol(e, k, s), "markPrice": "%.3f" % self.prices(e, k, s)[0], "markIV": "0.5",
                 "bidIV": "0.49", "askIV": "0.51", "delta": "0.5" if s == "CALL" else "-0.5", "gamma": "0.00002",
                 "theta": "-10.5", "vega": "50.25"} for e, k, s in self.board()]

    def ticker(self):
        rows = []
        for e, k, s in self.board():
            _, bid, ask = self.prices(e, k, s)
            rows.append({"symbol": self.symbol(e, k, s), "bidPrice": "%.3f" % bid, "askPrice": "%.3f" % ask,
                         "lastPrice": "0", "volume": "1.5", "amount": "1200"})
        return rows

    def fetch(self, path, params=None):
        self.calls.append(path)
        if self.fail is not None:
            raise self.fail
        if path == "/eapi/v1/time":
            return {"serverTime": self.now_ms}, self.weight
        if path == "/eapi/v1/exchangeInfo":
            return self.exchange_info(), self.weight
        if path == "/eapi/v1/index":
            assert params == {"underlying": "BTCUSDT"}
            return {"indexPrice": "%.8f" % self.index, "time": self.now_ms}, self.weight
        if path == "/eapi/v1/mark":
            return self.mark(), self.weight
        if path == "/eapi/v1/ticker":
            return self.ticker(), self.weight
        raise AssertionError("unexpected path " + path)

    def put(self, days_index=1, strike=70000):
        return self.symbol(self.expiries[days_index], strike, "PUT")

    def frame(self, *events):
        """A combined-stream message as Binance sends it."""
        return json.dumps({"stream": "btcusdt@optionMarkPrice", "data": list(events)})

    def event(self, symbol, stamp=None, **fields):
        event = {"e": "markPrice", "E": self.now_ms if stamp is None else stamp, "s": symbol}
        event.update(fields)
        return event

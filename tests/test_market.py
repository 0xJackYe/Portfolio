import gzip
import io
import json
import os
import sys
import time
import unittest
import urllib.error
from email.message import Message
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import market  # noqa: E402
from fake_binance import DAY, FakeBinance  # noqa: E402
from market import Market, MarketError  # noqa: E402


def row(snapshot, symbol):
    return next(c for c in snapshot["contracts"] if c["symbol"] == symbol)


class LoadTest(unittest.TestCase):
    def setUp(self):
        self.binance = FakeBinance()
        self.market = Market(fetch=self.binance.fetch, connect=None)

    def test_loading_until_the_first_refresh(self):
        snapshot = self.market.snapshot()
        self.assertEqual("loading", snapshot["status"])
        self.assertEqual([], snapshot["contracts"])

    def test_catalog_loads_quotes_greeks_and_index(self):
        self.market.refresh_catalog()
        snapshot = self.market.snapshot()
        self.assertEqual("delayed", snapshot["status"])  # REST only: no stream configured
        self.assertEqual(20, len(snapshot["contracts"]))
        self.assertEqual(80000.0, snapshot["index"])
        put = row(snapshot, self.binance.put())
        mark, bid, ask = self.binance.prices(self.binance.expiries[1], 70000, "PUT")
        self.assertEqual({"symbol": self.binance.put(), "side": "PUT", "strike": 70000.0, "expiry": self.binance.expiries[1],
                          "unit": 1.0, "minQty": 0.01, "bid": float(bid), "ask": float(ask), "bidSize": None, "askSize": None,
                          "mark": round(mark, 3), "iv": 0.5, "delta": -0.5, "gamma": 0.00002, "theta": -10.5, "vega": 50.25,
                          "volume": 1.5}, put)
        self.assertIsNone(snapshot["error"])
        self.assertIsInstance(snapshot["updated"], int)

    def test_contracts_are_sorted_by_expiry_strike_and_side(self):
        self.market.refresh_catalog()
        keys = [(c["expiry"], c["strike"], c["side"]) for c in self.market.snapshot()["contracts"]]
        self.assertEqual(sorted(keys), keys)

    def test_empty_book_sides_and_invalid_numbers_become_none(self):
        symbol = self.binance.put()
        ticker = self.binance.ticker
        mark = self.binance.mark

        def patched_ticker():
            rows = ticker()
            for item in rows:
                if item["symbol"] == symbol:
                    item.update(askPrice="0.000", bidPrice="NaN", volume="-1")
            return rows

        def patched_mark():
            rows = mark()
            for item in rows:
                if item["symbol"] == symbol:
                    item.update(markIV="-1.0", gamma="Infinity", delta=True)
            return rows

        self.binance.ticker, self.binance.mark = patched_ticker, patched_mark
        self.market.refresh_catalog()
        put = row(self.market.snapshot(), symbol)
        self.assertEqual((None, None, None, None, None, None), (put["ask"], put["bid"], put["volume"], put["iv"], put["gamma"], put["delta"]))

    def test_only_trading_btc_contracts_that_have_not_expired(self):
        now = self.binance.now_ms
        base = {"side": "CALL", "strikePrice": "80000", "unit": 1, "minQty": "0.01"}
        self.binance.extra_symbols = [
            dict(base, symbol="ETH-261231-4000-C", underlying="ETHUSDT", expiryDate=now + DAY, status="TRADING"),
            dict(base, symbol="BTC-261231-81000-C", underlying="BTCUSDT", expiryDate=now + DAY, status="PENDING"),
            dict(base, symbol="BTC-200101-82000-C", underlying="BTCUSDT", expiryDate=now - DAY, status="TRADING"),
            dict(base, symbol="BTC-261231-83000-X", underlying="BTCUSDT", expiryDate=now + DAY, side="X"),
            dict(base, symbol="BTC-261231-84000-C", underlying="BTCUSDT", expiryDate=now + DAY, strikePrice="0"),
            "not a contract",
        ]
        self.market.refresh_catalog()
        self.assertEqual(20, len(self.market.snapshot()["contracts"]))

    def test_clock_offset_follows_the_exchange(self):
        self.binance.now_ms += 10000  # the exchange clock runs 10 s ahead of this computer
        self.market.refresh_catalog()
        self.assertAlmostEqual(10000, self.market.snapshot()["offset"], delta=1500)

    def test_unexpected_payloads_raise_data_errors(self):
        for path, payload in (("/eapi/v1/exchangeInfo", {"optionSymbols": "x"}), ("/eapi/v1/ticker", {}),
                              ("/eapi/v1/time", []), ("/eapi/v1/index", {"indexPrice": "0"})):
            original = self.binance.fetch

            def fetch(p, params=None, original=original, path=path, payload=payload):
                return (payload, 1) if p == path else original(p, params)

            broken = Market(fetch=fetch, connect=None)
            with self.subTest(path=path), self.assertRaises(MarketError) as raised:
                broken.refresh_catalog()
            self.assertEqual("data", raised.exception.kind)
            self.assertEqual([], broken.snapshot()["contracts"])

    def test_catalog_with_no_btc_contracts_is_an_error(self):
        self.binance.strikes = ()
        with self.assertRaises(MarketError):
            self.market.refresh_catalog()


class StreamTest(unittest.TestCase):
    def setUp(self):
        self.binance = FakeBinance()
        self.market = Market(fetch=self.binance.fetch, connect=lambda *a, **k: None)
        self.market.refresh_catalog()
        self.symbol = self.binance.put()

    def test_stream_updates_quotes_greeks_and_index(self):
        frame = self.binance.frame(self.binance.event(
            self.symbol, mp="1234.5", bo="1200.000", ao="0.000", bq="3.5", aq="0.00",
            vo="0.55", b="0.54", a="-1.0", d="-0.25", g="0.0001", t="-20", v="60", i="81000.5"))
        self.assertTrue(self.market.apply_stream(frame))
        snapshot = self.market.snapshot()
        put = row(snapshot, self.symbol)
        self.assertEqual("live", snapshot["status"])
        self.assertEqual(81000.5, snapshot["index"])
        self.assertEqual((1234.5, 1200.0, None, 3.5, 0.0, 0.55, -0.25, 0.0001, -20.0, 60.0),
                         (put["mark"], put["bid"], put["ask"], put["bidSize"], put["askSize"], put["iv"], put["delta"],
                          put["gamma"], put["theta"], put["vega"]))
        self.assertEqual(1.5, put["volume"])  # untouched by the stream
        self.assertNotIn("bidIv", put)

    def test_partial_events_keep_other_fields(self):
        before = row(self.market.snapshot(), self.symbol)
        self.market.apply_stream(self.binance.frame(self.binance.event(self.symbol, mp="999")))
        after = row(self.market.snapshot(), self.symbol)
        self.assertEqual(999.0, after["mark"])
        self.assertEqual((before["bid"], before["delta"]), (after["bid"], after["delta"]))

    def test_older_events_never_roll_back_newer_ones(self):
        now = self.binance.now_ms
        self.market.apply_stream(self.binance.frame(self.binance.event(self.symbol, now + 2000, bo="300", i="81000")))
        self.market.apply_stream(self.binance.frame(self.binance.event(self.symbol, now + 1000, bo="200", i="79000")))
        snapshot = self.market.snapshot()
        self.assertEqual(300.0, row(snapshot, self.symbol)["bid"])
        self.assertEqual(81000.0, snapshot["index"])

    def test_single_event_payload_and_garbage_are_handled(self):
        self.assertTrue(self.market.apply_stream(json.dumps({"data": self.binance.event(self.symbol, bo="111")})))
        self.assertEqual(111.0, row(self.market.snapshot(), self.symbol)["bid"])
        for message in ("not json", b"\xff", json.dumps({"result": None, "id": 1}), json.dumps({"data": "x"}),
                        self.binance.frame({"e": "trade", "s": self.symbol}), self.binance.frame(self.binance.event(["x"], bo="1")),
                        self.binance.frame(self.binance.event(self.symbol, stamp="soon", bo="1"))):
            with self.subTest(message=message):
                self.assertFalse(self.market.apply_stream(message))

    def test_new_listing_on_the_stream_triggers_a_catalog_reload(self):
        self.market._catalog_at = time.monotonic() - 300
        listed = self.binance.symbol(self.binance.now_ms + 60 * DAY, 120000, "CALL")
        self.market.apply_stream(self.binance.frame(self.binance.event(self.symbol, bo="1"), self.binance.event(listed, bo="1")))
        self.assertLessEqual(self.market._catalog_due, time.monotonic())

    def test_expired_or_recent_listings_do_not_reload_the_catalog(self):
        due = self.market._catalog_due
        expired = self.binance.symbol(self.binance.now_ms - 2 * DAY, 80000, "CALL")
        self.market.apply_stream(self.binance.frame(self.binance.event(self.symbol, bo="1"), self.binance.event(expired, bo="1")))
        self.assertEqual(due, self.market._catalog_due)
        listed = self.binance.symbol(self.binance.now_ms + 60 * DAY, 120000, "CALL")
        self.market.apply_stream(self.binance.frame(self.binance.event(self.symbol, bo="2"), self.binance.event(listed, bo="1")))
        self.assertEqual(due, self.market._catalog_due)  # the catalog was loaded moments ago

    def test_stream_goes_quiet_then_delayed(self):
        self.market.apply_stream(self.binance.frame(self.binance.event(self.symbol, bo="1")))
        self.market._stream_at -= market.LIVE_SECONDS + 1
        revision = self.market.frame()[0]
        self.market.watch()
        self.assertEqual("delayed", self.market.snapshot()["status"])
        self.assertGreater(self.market.frame()[0], revision)

    def test_first_connection_is_reported_as_connecting(self):
        self.assertEqual("connecting", self.market.snapshot()["status"])
        self.market._started -= market.CONNECT_SECONDS + 1
        self.market.watch()
        self.assertEqual("delayed", self.market.snapshot()["status"])

    def test_catalog_refresh_while_live_only_updates_volume(self):
        self.market.apply_stream(self.binance.frame(self.binance.event(self.symbol, bo="777", mp="780")))
        self.binance.index = 50000.0
        calls = len(self.binance.calls)
        self.market.refresh_catalog()
        put = row(self.market.snapshot(), self.symbol)
        self.assertEqual((777.0, 780.0), (put["bid"], put["mark"]))
        self.assertNotIn("/eapi/v1/mark", self.binance.calls[calls:])  # no quote requests while streaming
        self.assertEqual(80000.0, self.market.snapshot()["index"])

    def test_rest_fallback_does_not_overwrite_quotes_streamed_meanwhile(self):
        other = self.binance.put(0, 80000)

        def fetch(path, params=None):
            if path == "/eapi/v1/mark":  # the stream delivers while the REST request is in flight
                self.market.apply_stream(self.binance.frame(self.binance.event(self.symbol, bo="555")))
            return self.binance.fetch(path, params)

        self.market._fetch = fetch
        self.market.refresh_quotes()
        snapshot = self.market.snapshot()
        self.assertEqual(555.0, row(snapshot, self.symbol)["bid"])
        self.assertEqual(float(self.binance.prices(self.binance.expiries[0], 80000, "PUT")[1]), row(snapshot, other)["bid"])

    def test_stream_connection_lifecycle(self):
        frames = [market.TIMEOUTS[0](), self.binance.frame(self.binance.event(self.symbol, bo="4321")), ""]

        class Socket:
            closed = False

            def settimeout(self, value):
                self.timeout = value

            def recv(self):
                item = frames.pop(0)
                if isinstance(item, Exception):
                    raise item
                return item

            def close(self):
                self.closed = True

        sock = Socket()
        opened = {}

        def connect(url, **options):
            opened.update(options, url=url)
            return sock

        self.market._connect = connect
        self.assertTrue(self.market._stream_once())
        self.assertEqual(market.STREAM_URL, opened["url"])
        self.assertTrue(opened["skip_utf8_validation"])
        self.assertTrue(sock.closed)
        self.assertFalse(self.market._stream_up)
        self.assertEqual(4321.0, row(self.market.snapshot(), self.symbol)["bid"])

    def test_failed_connection_reports_no_delivery(self):
        def connect(url, **options):
            raise OSError("refused")

        self.market._connect = connect
        self.assertFalse(self.market._stream_once())


class LifecycleTest(unittest.TestCase):
    def setUp(self):
        self.binance = FakeBinance()
        self.market = Market(fetch=self.binance.fetch, connect=None)
        self.market.refresh_catalog()

    def test_contracts_disappear_at_expiry(self):
        near = self.binance.expiries[0]
        self.market._offset += near - self.market._clock() + 1  # move the exchange clock past the first expiry
        revision = self.market.frame()[0]
        self.market.watch()
        contracts = self.market.snapshot()["contracts"]
        self.assertEqual(10, len(contracts))
        self.assertTrue(all(c["expiry"] > near for c in contracts))
        self.assertGreater(self.market.frame()[0], revision)

    def test_frame_is_encoded_once_per_revision(self):
        first = self.market.frame()
        self.assertIs(first, self.market.frame())
        self.market.apply_stream(self.binance.frame(self.binance.event(self.binance.put(), bo="1")))
        self.assertGreater(self.market.frame()[0], first[0])

    def test_wait_returns_at_once_for_a_stale_revision_and_times_out_otherwise(self):
        revision = self.market.frame()[0]
        started = time.monotonic()
        self.assertEqual(revision, self.market.wait(revision - 1, 5))
        self.assertEqual(revision, self.market.wait(revision, 0.05))
        self.assertLess(time.monotonic() - started, 1)

    def test_rate_limits_pause_rest_and_surface_an_error(self):
        self.market._failed(MarketError("rate_limit", 429, 120))
        self.assertGreaterEqual(self.market._paused_until - time.monotonic(), 119)
        self.assertEqual("rate_limit", self.market.snapshot()["error"])
        self.market._paused_until = 0
        self.market.refresh_quotes()
        self.assertIsNone(self.market.snapshot()["error"])

    def test_failures_back_off_exponentially(self):
        delays = []
        for _ in range(8):
            self.market._paused_until = 0
            self.market._failed(MarketError("network"))
            delays.append(round(self.market._paused_until - time.monotonic()))
        self.assertEqual([2, 4, 8, 16, 32, 60, 60, 60], delays)

    def test_heavy_weight_use_waits_for_the_next_minute(self):
        self.binance.weight = 320
        self.market.refresh_quotes()
        self.assertGreater(self.market._paused_until, time.monotonic())

    def test_rest_loop_survives_unexpected_errors(self):
        def fetch(path, params=None):
            raise TypeError("surprise")

        broken = Market(fetch=fetch, connect=None)
        broken.start()
        try:
            deadline = time.monotonic() + 3
            while broken.snapshot()["error"] is None and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertEqual("data", broken.snapshot()["error"])
            self.assertTrue(all(thread.is_alive() for thread in broken._threads))
        finally:
            broken.stop()

    def test_start_and_stop(self):
        live = Market(fetch=FakeBinance().fetch, connect=None)
        live.start()
        try:
            deadline = time.monotonic() + 3
            while live.snapshot()["status"] == "loading" and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertEqual("delayed", live.snapshot()["status"])
        finally:
            live.stop()
        self.assertTrue(live.stopped)
        self.assertFalse(any(thread.is_alive() for thread in live._threads))


class HelpersTest(unittest.TestCase):
    def test_symbol_expiry(self):
        self.assertEqual(1795766400000, market.symbol_expiry("BTC-261127-64000-P"))  # 2026-11-27 08:00 UTC
        for symbol in ("BTC", "BTC-261399-1-C", None, 7):
            self.assertIsNone(market.symbol_expiry(symbol))

    def test_number_and_field(self):
        self.assertEqual(1.5, market.number("1.5"))
        for bad in (None, True, "x", "nan", "inf", [], {}):
            self.assertIsNone(market.number(bad))
        self.assertIsNone(market.field("ask", "0.000"))
        self.assertIsNone(market.field("iv", "-1.0"))
        self.assertEqual(0.0, market.field("askSize", "0.00"))
        self.assertIsNone(market.field("volume", "-3"))
        self.assertEqual(-0.5, market.field("delta", "-0.5"))

    def test_stream_proxy_follows_https_proxy_settings(self):
        env = {"HTTPS_PROXY": "http://me:p%40ss@127.0.0.1:7890", "NO_PROXY": ""}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual({"http_proxy_host": "127.0.0.1", "http_proxy_port": 7890, "proxy_type": "http",
                              "http_proxy_auth": ("me", "p@ss")}, market.stream_proxy())
        with mock.patch.dict(os.environ, dict(env, NO_PROXY="binance.com"), clear=True):
            self.assertEqual({}, market.stream_proxy())
        with mock.patch.dict(os.environ, {"HTTPS_PROXY": "socks5://127.0.0.1:1080"}, clear=True):
            self.assertEqual({}, market.stream_proxy())
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch("urllib.request.getproxies", return_value={}):
            self.assertEqual({}, market.stream_proxy())


class FakeResponse:
    def __init__(self, body, headers=None):
        self.body = body
        self.headers = Message()
        for key, value in (headers or {}).items():
            self.headers[key] = value

    def read(self, limit=-1):
        return self.body if limit < 0 else self.body[:limit]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FetchTest(unittest.TestCase):
    def fetch(self, response=None, error=None):
        def urlopen(request, timeout):
            self.request = request
            if error:
                raise error
            return response

        with mock.patch("urllib.request.urlopen", urlopen):
            return market.fetch_json("/eapi/v1/index", {"underlying": "BTCUSDT"})

    def test_decodes_gzip_and_reports_weight(self):
        body = gzip.compress(json.dumps({"indexPrice": "1"}).encode())
        data, weight = self.fetch(FakeResponse(body, {"Content-Encoding": "gzip", "X-MBX-USED-WEIGHT-1M": "42"}))
        self.assertEqual(({"indexPrice": "1"}, 42), (data, weight))
        self.assertEqual("https://eapi.binance.com/eapi/v1/index?underlying=BTCUSDT", self.request.full_url)
        self.assertNotIn("X-mbx-apikey", self.request.headers)

    def test_plain_json_without_weight(self):
        self.assertEqual(([1], None), self.fetch(FakeResponse(b"[1]")))

    def test_http_errors(self):
        headers = Message()
        headers["Retry-After"] = "30"
        with self.assertRaises(MarketError) as raised:
            self.fetch(error=urllib.error.HTTPError("u", 429, "Too Many Requests", headers, io.BytesIO()))
        self.assertEqual(("rate_limit", 429, 30.0), (raised.exception.kind, raised.exception.status, raised.exception.retry_after))
        with self.assertRaises(MarketError) as raised:
            self.fetch(error=urllib.error.HTTPError("u", 418, "Banned", Message(), io.BytesIO()))
        self.assertEqual("rate_limit", raised.exception.kind)
        with self.assertRaises(MarketError) as raised:
            self.fetch(error=urllib.error.HTTPError("u", 503, "Unavailable", Message(), io.BytesIO()))
        self.assertEqual(("server", 503), (raised.exception.kind, raised.exception.status))

    def test_network_errors_do_not_leak_details(self):
        for error in (urllib.error.URLError(ConnectionRefusedError("http://user:secret@proxy:8080")), TimeoutError("slow")):
            with self.subTest(error=error), self.assertRaises(MarketError) as raised:
                self.fetch(error=error)
            self.assertEqual("network", raised.exception.kind)
            self.assertNotIn("secret", str(raised.exception))

    def test_invalid_oversized_and_error_bodies(self):
        with self.assertRaises(MarketError) as raised:
            self.fetch(FakeResponse(b"<html>"))
        self.assertEqual("data", raised.exception.kind)
        with mock.patch.object(market, "MAX_BODY", 4), self.assertRaises(MarketError) as raised:
            self.fetch(FakeResponse(b"[1,2,3,4,5]"))
        self.assertEqual("data", raised.exception.kind)
        with self.assertRaises(MarketError) as raised:
            self.fetch(FakeResponse(json.dumps({"code": -1003, "msg": "Too many requests"}).encode()))
        self.assertEqual("rate_limit", raised.exception.kind)
        with self.assertRaises(MarketError) as raised:
            self.fetch(FakeResponse(json.dumps({"code": -1121, "msg": "Invalid symbol"}).encode()))
        self.assertEqual("server", raised.exception.kind)


if __name__ == "__main__":
    unittest.main()

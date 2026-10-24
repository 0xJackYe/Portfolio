"""Local-only browser acceptance fixture for the actual sell-Put dashboard.

Run: python verification/sell_put_fixture_server.py --port 8769
Open http://127.0.0.1:8769/ manually. Ctrl+C stops the fixture. --seconds N is
available for a bounded smoke check. This script never starts a production
MarketCache, reads saved snapshots, opens Binance connections, or reads keys.
It serves the actual dashboard/dist files through DashboardServer/Handler;
HTML labelling is transformed in memory only, with no production file edits.
All prices and timestamps below are synthetic acceptance data, NOT a live feed.
"""

import argparse
import copy
import json
import re
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dashboard_server import DashboardHandler, DashboardServer  # noqa: E402


BEIJING = timezone(timedelta(hours=8))
LABEL = "模拟数据验收"
INSTANCE_ID = "sell-put-local-fixture-only"
MARK_KEYS = ("mark_price", "mark_iv", "bid_iv", "ask_iv", "delta", "gamma", "theta", "vega")
QUOTE_KEYS = ("bid_price", "ask_price", "bid_quantity", "ask_quantity")
TICKER_KEYS = ("last_price", "volume_24h_contracts", "amount_24h_quote", "last_trade_beijing")


def beijing(stamp_ms):
    return datetime.fromtimestamp(stamp_ms / 1000, BEIJING).isoformat(timespec="milliseconds")


def option_row(now_ms, expiry_ms, strike, *, side="PUT", case="normal"):
    date = datetime.fromtimestamp(expiry_ms / 1000, BEIJING).strftime("%y%m%d")
    symbol = "BTC-%s-%s-%s" % (date, strike, "P" if side == "PUT" else "C")
    mark_ms = now_ms - 120000 if case == "stale_mark" else now_ms
    values = {
        "symbol": symbol, "side": side, "status": "TRADING", "fixture_case": case,
        "expiry_ms": expiry_ms, "expiry_beijing": beijing(expiry_ms),
        "days_to_expiry": (expiry_ms - now_ms) / 86400000,
        "strike_price": str(strike), "unit": 1, "quote_asset": "USDT",
        "bid_price": "65", "ask_price": "70", "mark_price": "65", "last_price": "66",
        "bid_quantity": "0.001" if case == "insufficient_bid_depth" else "2.00",
        "ask_quantity": "3.00", "mark_iv": "0.6", "bid_iv": "0.59", "ask_iv": "0.62",
        "delta": "-0.05" if side == "PUT" else "0.95", "gamma": "0.00001",
        "theta": "-2", "vega": "12", "volume_24h_contracts": "1.50",
        "amount_24h_quote": "99", "last_trade_beijing": beijing(now_ms),
        "min_qty": "0.01", "max_qty": "200", "quantity_step": "0.01",
        "price_scale": 3, "quantity_scale": 2,
        "initial_margin_rate": "0.15", "min_initial_margin_rate": "0.10",
        "maintenance_margin_rate": "0.075", "min_maintenance_margin_rate": "0.05",
        "liquidation_fee_rate": "0.0019", "has_mark": True, "has_ticker": True,
        "quote_updated_at": now_ms, "quote_event_ms": None, "quote_source": "fixture",
        "mark_updated_at": mark_ms, "mark_event_ms": None, "mark_source": "fixture",
        "ticker_updated_at": now_ms, "ticker_event_ms": None, "ticker_source": "fixture",
        "field_updated_at": {}, "field_event_ms": {}, "field_source": {},
    }
    for keys, stamp_ms in ((QUOTE_KEYS, now_ms), (MARK_KEYS, mark_ms), (TICKER_KEYS, now_ms)):
        for key in keys:
            values["field_updated_at"][key] = stamp_ms
            values["field_event_ms"][key] = None
            values["field_source"][key] = "fixture"
    return values


class FakeCache:
    """Only generated in-memory data; supports the real Handler's SSE contract."""
    def __init__(self):
        self._stop = threading.Event()
        self._condition = threading.Condition()
        self._revision = 1
        self._expiry_ms = int(time.time() * 1000) + 15 * 86400000
        self._thread = threading.Thread(target=self._tick, name="sell-put-fixture-clock", daemon=True)
        self._thread.start()

    def _tick(self):
        while not self._stop.wait(1):
            with self._condition:
                self._revision += 1
                self._condition.notify_all()

    def _snapshot_locked(self):
        now_ms = int(time.time() * 1000)
        rows = [option_row(now_ms, self._expiry_ms, 65000),
                option_row(now_ms, self._expiry_ms, 64000, case="stale_mark"),
                option_row(now_ms, self._expiry_ms, 63000, case="insufficient_bid_depth"),
                option_row(now_ms, self._expiry_ms, 65000, side="CALL")]
        health = {}
        for name, status, available, fresh in (("quote", "fresh", 16, 16), ("mark", "partial", 24, 18),
                                                ("index", "fresh", 1, 1), ("ticker", "fresh", 12, 12),
                                                ("catalog", "fresh", 4, 4)):
            health[name] = {"status": status, "source": "fixture", "connected": False,
                            "available_fields": available, "total_fields": available,
                            "fresh_fields": fresh, "missing_fields": 0,
                            "last_updated_at": now_ms, "oldest_updated_at": now_ms - 120000 if name == "mark" else now_ms,
                            "age_seconds": 120 if name == "mark" else 0,
                            "rest_refresh_failed": False, "message": LABEL + "，非真实市场数据"}
        return {"fixture": True, "fixture_label": LABEL, "source": "local_acceptance_fixture",
                "status": "PARTIAL", "credentials_used": False, "credential_validity_tested": False,
                "generated_at_beijing": beijing(now_ms), "fetched_at": beijing(now_ms),
                "catalog_updated_at": beijing(now_ms), "index_updated_at": now_ms,
                "index_event_ms": None, "index_source": "fixture", "btc_index_price": "81400",
                "server_now_ms": now_ms, "server_time_ms": now_ms, "exchange_clock_offset_ms": 0,
                "btc_contracts_total": len(rows), "selected_contracts": len(rows), "options": rows,
                "filters": {"side": "ALL", "min_days": 0, "max_days": 10000, "min_otm": None, "max_otm": None},
                "stale": False, "error": None, "refreshing": False, "retry_after_seconds": 0,
                "revision": self._revision, "instance_id": INSTANCE_ID, "data_health": health,
                "rate_limits": [{"rateLimitType": "REQUEST_WEIGHT", "interval": "MINUTE", "intervalNum": 1, "limit": 2400}],
                "realtime": {"connected": False, "mode": "fixture", "last_message_at": now_ms,
                             "last_error": None, "connections": 0, "connected_connections": 0,
                             "connection_details": {}, "channel_updated_at": {}}, "endpoints": {}}

    def read(self):
        with self._condition:
            return copy.deepcopy(self._snapshot_locked())

    def request_refresh(self):
        with self._condition:
            self._revision += 1
            self._condition.notify_all()
        return True

    def wait_revision(self, revision, timeout=15):
        with self._condition:
            self._condition.wait_for(lambda: self._revision != revision or self._stop.is_set(), timeout)
            return self._revision

    def wait_snapshot(self, revision, timeout=15):
        with self._condition:
            self._condition.wait_for(lambda: self._revision != revision or self._stop.is_set(), timeout)
            return self._revision, copy.deepcopy(self._snapshot_locked())

    def stop(self):
        self._stop.set()
        with self._condition:
            self._condition.notify_all()
        if threading.current_thread() is not self._thread:
            self._thread.join(timeout=2)


class FixtureHandler(DashboardHandler):
    def end_headers(self):
        self.send_header("X-Acceptance-Fixture", "synthetic-public-data-only")
        super().end_headers()

    def _respond(self, status, payload, content_type="application/json; charset=utf-8"):
        if status == 200 and content_type.startswith("text/html"):
            text = payload.decode("utf-8")
            text = re.sub(r"<title>.*?</title>", "<title>" + LABEL + " · BTC 卖 Put 工作台</title>", text, count=1)
            text = re.sub(r'(<h2\b[^>]*\bid="sellPutHeading"[^>]*>).*?(</h2>)',
                          lambda match: match[1] + "卖 Put 工作台 · " + LABEL + match[2], text, count=1)
            text = text.replace("<h1>BTCUSDT</h1>", "<h1>BTCUSDT · " + LABEL + "</h1>")
            payload = text.encode("utf-8")
        super()._respond(status, payload, content_type)


def create_server(port=8769):
    cache = FakeCache()
    try:
        server = DashboardServer(("127.0.0.1", port), cache, static_dir=ROOT / "dashboard" / "dist")
        server.RequestHandlerClass = FixtureHandler
        return server
    except Exception:
        cache.stop()
        raise


def main():
    parser = argparse.ArgumentParser(description=LABEL + "：实际前端 + 本地合成数据，不连接外网。")
    parser.add_argument("--port", type=int, default=8769)
    parser.add_argument("--seconds", type=float, default=0, help="可选：若大于零，在指定秒数后停止。")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535 or args.seconds < 0:
        parser.error("端口或运行时长无效。")
    server = create_server(args.port)
    shutdown_timer = None
    if args.seconds > 0:
        shutdown_timer = threading.Timer(args.seconds, server.shutdown)
        shutdown_timer.daemon = True
        shutdown_timer.start()
    print(LABEL + "：http://127.0.0.1:%s/ （仅本地合成数据，Ctrl+C 停止）" % args.port, flush=True)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        if shutdown_timer is not None:
            shutdown_timer.cancel()
        server.cache.stop()
        server.server_close()
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())

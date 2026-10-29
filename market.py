"""Live Binance BTC options market data for the local dashboard.

One public WebSocket stream, btcusdt@optionMarkPrice, carries the best bid and
ask, mark price, IV, Greeks and the BTC index for every BTC option about once
a second. REST loads the contract list at start, refreshes it every few
minutes and keeps quotes moving whenever the stream is down.

Public market data only: no API keys, no account access, no orders.
"""

import gzip
import http.client
import json
import math
import random
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

try:
    import websocket  # websocket-client; without it the dashboard polls REST
except ImportError:
    websocket = None

REST_URL = "https://eapi.binance.com"
STREAM_HOST = "fstream.binance.com"
STREAM_URL = "wss://fstream.binance.com/market/stream?streams=btcusdt@optionMarkPrice"
UNDERLYING = "BTCUSDT"

CATALOG_SECONDS = 300       # contract list, 24h volume and clock sync
FALLBACK_SECONDS = 15       # REST quotes while the stream is down
LIVE_SECONDS = 10           # stream quotes older than this are "delayed"
CONNECT_SECONDS = 15        # grace period for the first stream connection
SILENT_SECONDS = 20         # reconnect a stream that stops talking
ROTATE_SECONDS = 23 * 3600  # Binance drops connections after 24 hours
WEIGHT_BUDGET = 300         # REST weight per minute; Binance allows 400 per IP
MAX_BODY = 16 * 1024 * 1024

# Binance field names -> snapshot keys.
STREAM_FIELDS = {"bo": "bid", "ao": "ask", "bq": "bidSize", "aq": "askSize", "mp": "mark", "vo": "iv",
                 "d": "delta", "g": "gamma", "t": "theta", "v": "vega"}
MARK_FIELDS = {"markPrice": "mark", "markIV": "iv", "delta": "delta", "gamma": "gamma", "theta": "theta", "vega": "vega"}
TICKER_FIELDS = {"bidPrice": "bid", "askPrice": "ask", "volume": "volume"}
VOLUME_FIELDS = {"volume": "volume"}
QUOTE_KEYS = ("bid", "ask", "bidSize", "askSize", "mark", "iv", "delta", "gamma", "theta", "vega", "volume")
STREAM_KEYS = frozenset(STREAM_FIELDS.values())
POSITIVE_KEYS = frozenset(("bid", "ask", "mark", "iv"))  # 0 or -1 means none
SIZE_KEYS = frozenset(("bidSize", "askSize", "volume"))
TIMEOUTS = (socket.timeout, TimeoutError) + ((websocket.WebSocketTimeoutException,) if websocket else ())
CONNECT = websocket.create_connection if websocket else None


def number(value):
    """Exchange decimal string -> float; None when missing or not finite."""
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def positive(value):
    value = number(value)
    return value if value is not None and value > 0 else None


def field(key, value):
    """Normalize one quote field. Binance sends 0 or -1 for an empty book side."""
    if key in POSITIVE_KEYS:
        return positive(value)
    value = number(value)
    return None if value is None or key in SIZE_KEYS and value < 0 else value


def symbol_expiry(symbol):
    """Expiry (ms) implied by a symbol such as BTC-261127-64000-P; Binance expires at 08:00 UTC."""
    try:
        day = datetime.strptime(symbol.split("-")[1], "%y%m%d")
    except (AttributeError, IndexError, ValueError):
        return None
    return day.replace(hour=8, tzinfo=timezone.utc).timestamp() * 1000


def sort_key(row):
    return row["expiry"], row["strike"], row["side"]


class MarketError(Exception):
    """A failed REST call. kind is network, rate_limit, server or data."""

    def __init__(self, kind, status=None, retry_after=None):
        super().__init__(kind if status is None else "%s (HTTP %s)" % (kind, status))
        self.kind = kind
        self.status = status
        self.retry_after = retry_after


def fetch_json(path, params=None, timeout=10):
    """GET a public Binance options endpoint; returns (data, weight used this minute)."""
    url = REST_URL + path + ("?" + urllib.parse.urlencode(params) if params else "")
    request = urllib.request.Request(url, headers={"Accept": "application/json", "Accept-Encoding": "gzip"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(MAX_BODY + 1)
            encoding = response.headers.get("Content-Encoding", "")
            weight = response.headers.get("X-MBX-USED-WEIGHT-1M", "")
    except urllib.error.HTTPError as error:
        retry_after = number(error.headers.get("Retry-After")) if error.headers else None
        error.close()
        raise MarketError("rate_limit" if error.code in (418, 429) else "server", error.code, retry_after) from None
    except (OSError, http.client.HTTPException):
        # Never echo the exception text: proxy settings can carry credentials.
        raise MarketError("network") from None
    if len(body) > MAX_BODY:
        raise MarketError("data")
    try:
        data = json.loads(gzip.decompress(body) if encoding.lower() == "gzip" else body)
    except (OSError, EOFError, ValueError):
        raise MarketError("data") from None
    if isinstance(data, dict) and isinstance(data.get("code"), int) and data["code"] < 0:
        raise MarketError("rate_limit" if data["code"] == -1003 else "server")
    return data, int(weight) if weight.isdigit() else None


def stream_proxy():
    """Route the stream through the same HTTP proxy as REST (environment or Windows settings)."""
    try:
        proxy = urllib.request.getproxies().get("https")
        if not proxy or urllib.request.proxy_bypass(STREAM_HOST):
            return {}
        parts = urllib.parse.urlsplit(proxy if "://" in proxy else "http://" + proxy)
        if parts.scheme != "http" or not parts.hostname:
            return {}
        options = {"http_proxy_host": parts.hostname, "http_proxy_port": parts.port or 80, "proxy_type": "http"}
        if parts.username:
            options["http_proxy_auth"] = (urllib.parse.unquote(parts.username), urllib.parse.unquote(parts.password or ""))
        return options
    except (OSError, ValueError):
        return {}


class Market:
    """Live BTC options quotes, shared by every open browser tab."""

    def __init__(self, fetch=fetch_json, connect=CONNECT):
        """fetch(path, params) -> (data, weight) reads REST; connect(url, **options) opens the
        stream, or None for REST only."""
        self._fetch = fetch
        self._connect = connect
        self._cond = threading.Condition()
        self._stop = threading.Event()
        self._threads = []
        self._started = time.monotonic()
        self._contracts = {}      # symbol -> snapshot row
        self._event_ms = {}       # symbol -> exchange time of its newest stream event
        self._streamed_at = {}    # symbol -> monotonic time of its last stream update
        self._index = None
        self._index_ms = 0
        self._offset = 0          # exchange clock minus local clock, ms
        self._updated = None      # exchange time quotes were last confirmed, ms
        self._error = None
        self._status = "loading"
        self._stream_up = False
        self._stream_at = 0.0
        self._socket = None
        self._catalog_at = None
        self._catalog_due = 0.0
        self._fallback_due = 0.0
        self._paused_until = 0.0
        self._failures = 0
        self._revision = 0
        self._frame = (-1, b"")

    @property
    def streaming(self):
        """False when websocket-client is missing and quotes come from REST only."""
        return self._connect is not None

    @property
    def stopped(self):
        return self._stop.is_set()

    def start(self):
        self._started = time.monotonic()
        loops = [self._rest_loop, self._watch_loop] + ([self._stream_loop] if self.streaming else [])
        for loop in loops:
            thread = threading.Thread(target=loop, name="market" + loop.__name__, daemon=True)
            thread.start()
            self._threads.append(thread)

    def stop(self):
        self._stop.set()
        with self._cond:
            sock = self._socket
            self._cond.notify_all()
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass
        for thread in self._threads:
            thread.join(timeout=2)

    def sleep(self, seconds):
        """Sleep unless the market is stopping; True if it is."""
        return self._stop.wait(seconds)

    # Snapshot ------------------------------------------------------------

    def frame(self):
        """(revision, JSON bytes) of the current snapshot, encoded once per revision."""
        with self._cond:
            if self._frame[0] != self._revision:
                body = json.dumps(self._snapshot_locked(), separators=(",", ":"), allow_nan=False)
                self._frame = (self._revision, body.encode("utf-8"))
            return self._frame

    def snapshot(self):
        return json.loads(self.frame()[1])

    def wait(self, revision, timeout):
        """Block until the snapshot differs from `revision` or timeout; return the current revision."""
        with self._cond:
            if revision == self._revision and not self._stop.is_set():
                self._cond.wait(timeout)
            return self._revision

    def _snapshot_locked(self):
        clock = self._clock()
        status = self._status_locked()
        contracts = sorted((dict(row) for row in self._contracts.values() if row["expiry"] > clock), key=sort_key)
        return {"status": status, "index": self._index, "offset": self._offset, "updated": self._updated,
                "error": None if status == "live" else self._error, "contracts": contracts}

    def _status_locked(self):
        """loading: no data yet; live: streaming; connecting: first connection; delayed: REST only."""
        if not self._contracts or self._index is None:
            return "loading"
        now = time.monotonic()
        if self._stream_up and now - self._stream_at < LIVE_SECONDS:
            return "live"
        if self.streaming and not self._stream_at and now - self._started < CONNECT_SECONDS:
            return "connecting"
        return "delayed"

    def _clock(self):
        return time.time() * 1000 + self._offset

    def _bump(self):
        self._revision += 1
        self._cond.notify_all()

    def _watch_loop(self):
        while not self._stop.wait(1):
            self.watch()

    def watch(self):
        """Publish status changes and drop contracts the moment they expire."""
        with self._cond:
            clock = self._clock()
            expired = [symbol for symbol, row in self._contracts.items() if row["expiry"] <= clock]
            for symbol in expired:
                del self._contracts[symbol]
            status = self._status_locked()
            if status != self._status or expired:
                self._status = status
                self._bump()

    # REST ----------------------------------------------------------------

    def _rest_loop(self):
        while not self._stop.is_set():
            now = time.monotonic()
            if now >= self._paused_until:
                try:
                    if now >= self._catalog_due:
                        self.refresh_catalog()
                    elif now >= self._fallback_due and not self._live():
                        self.refresh_quotes()
                except MarketError as error:
                    self._failed(error)
                except Exception:  # malformed data must never stop the refresh loop
                    self._failed(MarketError("data"))
            self._stop.wait(1)

    def refresh_catalog(self):
        """Reload contracts, the exchange clock and 24h volume; quotes too unless the stream is live."""
        began = time.monotonic()
        sent = time.time()
        server = self._get("/eapi/v1/time")
        received = time.time()
        info = self._get("/eapi/v1/exchangeInfo")
        ticker = self._get("/eapi/v1/ticker")
        quotes = not self._live()
        mark = self._get("/eapi/v1/mark") if quotes else []
        index = self._get("/eapi/v1/index", {"underlying": UNDERLYING}) if quotes else None
        server_ms = number(server.get("serverTime")) if isinstance(server, dict) else None
        if server_ms is None or not isinstance(ticker, list) or not isinstance(mark, list):
            raise MarketError("data")
        with self._cond:
            self._offset = int(round(server_ms - (sent + received) * 500))
            contracts = self._parse_catalog(info)
            index = self._parse_index(index) if quotes else None
            changed = contracts.keys() != self._contracts.keys()
            self._contracts = contracts
            for table in (self._event_ms, self._streamed_at):
                for symbol in set(table) - contracts.keys():
                    del table[symbol]
            # A live stream owns bid/ask; the catalog refresh only adds 24h volume.
            changed = self._merge(ticker, TICKER_FIELDS if quotes else VOLUME_FIELDS, began) or changed
            if quotes:
                changed = self._merge(mark, MARK_FIELDS, began) or changed
                changed = self._set_index(*index) or changed
            self._catalog_at = time.monotonic()
            self._catalog_due = self._catalog_at + CATALOG_SECONDS
            self._fallback_due = self._catalog_at + FALLBACK_SECONDS
            self._succeeded(changed)

    def refresh_quotes(self):
        """REST fallback for bid/ask, mark, Greeks and the index while the stream is down."""
        began = time.monotonic()
        mark = self._get("/eapi/v1/mark")
        ticker = self._get("/eapi/v1/ticker")
        index = self._get("/eapi/v1/index", {"underlying": UNDERLYING})
        if not isinstance(mark, list) or not isinstance(ticker, list):
            raise MarketError("data")
        with self._cond:
            index = self._parse_index(index)
            changed = self._merge(mark, MARK_FIELDS, began)
            changed = self._merge(ticker, TICKER_FIELDS, began) or changed
            changed = self._set_index(*index) or changed
            self._fallback_due = time.monotonic() + FALLBACK_SECONDS
            self._succeeded(changed)

    def _get(self, path, params=None):
        data, weight = self._fetch(path, params)
        if weight is not None and weight >= WEIGHT_BUDGET:
            # Leave the rest of this minute to other users of the same IP.
            self._paused_until = max(self._paused_until, time.monotonic() + 61 - time.time() % 60)
        return data

    def _live(self):
        with self._cond:
            return self._status_locked() == "live"

    def _succeeded(self, changed):
        self._failures = 0
        self._error = None
        self._updated = int(self._clock())
        self._bump()

    def _failed(self, error):
        self._failures = min(self._failures + 1, 6)
        delay = min(60, 2 ** self._failures)
        if error.kind == "rate_limit":
            delay = max(delay, error.retry_after or 60)
        with self._cond:
            self._paused_until = max(self._paused_until, time.monotonic() + delay)
            if self._error != error.kind:
                self._error = error.kind
                self._bump()

    def _parse_catalog(self, info):
        items = info.get("optionSymbols") if isinstance(info, dict) else None
        if not isinstance(items, list):
            raise MarketError("data")
        clock = self._clock()
        contracts = {}
        for item in items:
            if not isinstance(item, dict) or item.get("underlying") != UNDERLYING or item.get("status", "TRADING") != "TRADING":
                continue
            symbol, side = item.get("symbol"), item.get("side")
            strike, expiry = positive(item.get("strikePrice")), positive(item.get("expiryDate"))
            if not isinstance(symbol, str) or side not in ("CALL", "PUT") or not strike or not expiry or expiry <= clock:
                continue
            row = self._contracts.get(symbol)
            if row is None:
                row = {"symbol": symbol}
                row.update(dict.fromkeys(QUOTE_KEYS))
            row.update(side=side, strike=strike, expiry=int(expiry),
                       unit=positive(item.get("unit")) or 1.0, minQty=positive(item.get("minQty")) or 0.01)
            contracts[symbol] = row
        if not contracts:
            raise MarketError("data")
        return contracts

    def _merge(self, items, mapping, began):
        """Merge REST rows into contracts; stream values received after `began` win."""
        changed = False
        for item in items:
            symbol = item.get("symbol") if isinstance(item, dict) else None
            row = self._contracts.get(symbol) if isinstance(symbol, str) else None
            if row is None:
                continue
            streamed = self._streamed_at.get(row["symbol"], -math.inf) >= began
            for wire, key in mapping.items():
                if wire in item and not (streamed and key in STREAM_KEYS):
                    value = field(key, item[wire])
                    if row[key] != value:
                        row[key] = value
                        changed = True
        return changed

    def _parse_index(self, data):
        price = positive(data.get("indexPrice")) if isinstance(data, dict) else None
        if price is None:
            raise MarketError("data")
        return price, positive(data.get("time")) or self._clock()

    def _set_index(self, price, stamp):
        if stamp < self._index_ms:
            return False
        changed = price != self._index
        self._index, self._index_ms = price, stamp
        return changed

    # Stream ----------------------------------------------------------------

    def _stream_loop(self):
        failures = 0
        while not self._stop.is_set():
            opened = time.monotonic()
            delivered = self._stream_once()
            if self._stop.is_set():
                return
            failures = 0 if delivered and time.monotonic() - opened > 60 else min(failures + 1, 5)
            self._stop.wait(min(30, 2 ** failures) * random.uniform(0.8, 1.2))

    def _stream_once(self):
        """Run one WebSocket connection until it drops; True if it delivered quotes."""
        try:
            sock = self._connect(STREAM_URL, timeout=10, enable_multithread=True,
                                 skip_utf8_validation=True, **stream_proxy())
        except Exception:
            return False
        with self._cond:
            self._socket = sock
        delivered = False
        try:
            sock.settimeout(5)
            opened = last = time.monotonic()
            while not self._stop.is_set():
                now = time.monotonic()
                if now - last > SILENT_SECONDS or now - opened > ROTATE_SECONDS:
                    break
                try:
                    message = sock.recv()
                except TIMEOUTS:
                    continue
                if not message:
                    break  # closed by Binance
                last = time.monotonic()
                delivered = self.apply_stream(message) or delivered
        except Exception:
            pass  # dropped connection: reconnect with backoff
        finally:
            with self._cond:
                self._socket = None
                if self._stream_up:
                    self._stream_up = False
                    self._bump()
            try:
                sock.close()
            except Exception:
                pass
        return delivered

    def apply_stream(self, message):
        """Apply one combined-stream frame of markPrice events; True if it carried quotes."""
        try:
            payload = json.loads(message)
        except (TypeError, ValueError):
            return False
        events = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(events, dict):
            events = [events]
        if not isinstance(events, list):
            return False
        now = time.monotonic()
        with self._cond:
            clock = self._clock()
            newest = None
            changed = unlisted = False
            for event in events:
                symbol = event.get("s") if isinstance(event, dict) and event.get("e") == "markPrice" else None
                if not isinstance(symbol, str):
                    continue
                row = self._contracts.get(symbol)
                if row is None:
                    expiry = symbol_expiry(symbol)
                    unlisted = unlisted or expiry is not None and expiry > clock
                    continue
                stamp = number(event.get("E"))
                if stamp is None or stamp < self._event_ms.get(row["symbol"], 0):
                    continue  # stale event
                self._event_ms[row["symbol"]] = stamp
                self._streamed_at[row["symbol"]] = now
                newest = stamp if newest is None else max(newest, stamp)
                for wire, key in STREAM_FIELDS.items():
                    if wire in event:
                        value = field(key, event[wire])
                        if row[key] != value:
                            row[key] = value
                            changed = True
                index = positive(event.get("i"))
                if index is not None:
                    changed = self._set_index(index, stamp) or changed
            if newest is None:
                return False
            went_live = not self._stream_up
            self._stream_up, self._stream_at = True, now
            self._updated = int(newest)
            if unlisted and (self._catalog_at is None or now - self._catalog_at > 120):
                self._catalog_due = min(self._catalog_due, now)  # a new listing: reload contracts
            if changed or went_live:
                self._bump()
            return True

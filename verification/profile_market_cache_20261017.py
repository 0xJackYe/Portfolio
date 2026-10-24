"""Offline cache profile using an existing public snapshot; no upstream network."""
import copy
import cProfile
import io
import json
from pathlib import Path
import pstats
import statistics
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dashboard_server import MarketCache


def percentile(values, fraction):
    return sorted(values)[min(len(values) - 1, int(len(values) * fraction))]


def measure(call, count):
    durations = []
    for _ in range(count):
        began = time.perf_counter()
        call()
        durations.append((time.perf_counter() - began) * 1000)
    return {"count": count, "mean_ms": round(statistics.mean(durations), 3),
            "p50_ms": round(statistics.median(durations), 3),
            "p95_ms": round(percentile(durations, .95), 3), "max_ms": round(max(durations), 3)}


def build_cache(snapshot, directory):
    cache = MarketCache(directory, websocket_factory=None)
    cache._snapshot = copy.deepcopy(snapshot)
    cache._rows_by_symbol = {row["symbol"]: row for row in cache._snapshot["options"]}
    cache._stream_states = copy.deepcopy(snapshot["realtime"]["connection_details"])
    cache._plan = {"connections": len(cache._stream_states), "streams": snapshot["realtime"]["stream_count"]}
    now = int(time.time() * 1000)
    cache._last_message_at = now
    cache._last_messages = dict(mark=now, index=now, book=now, ticker=now)
    quotes = ("bid_price", "ask_price", "bid_quantity", "ask_quantity")
    for name, state in cache._stream_states.items():
        state.update(connected=True, subscription_confirmed=True, heartbeat_at=now, heartbeat_kind="pong")
        if not name.startswith("book-"):
            continue
        for symbol in state.get("symbols", []):
            row = cache._rows_by_symbol[symbol]
            if not all(row.get(field) is not None for field in quotes):
                continue
            cache._book_baselines[symbol] = dict(connection=name, generation=state["generation"],
                values={field: row[field] for field in quotes}, baseline_at=now, event_ms=now,
                baseline_source="bookTicker", **{meta: {field: row[meta].get(field) for field in quotes}
                    for meta in ("field_updated_at", "field_event_ms", "field_source")})
    return cache


def main():
    path = ROOT / "verification/realtime-final-market-snapshot-20261016.json"
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    report = {"source": str(path), "contracts": len(snapshot["options"]), "upstream_connections_opened": 0}
    with tempfile.TemporaryDirectory() as directory:
        cache = build_cache(snapshot, directory)
        report["certified_baselines"] = len(cache._book_baselines)
        now = int(time.time() * 1000)
        def compact_read():
            with cache._lock:
                return cache._read_locked(include_endpoints=False)
        report["read_full"] = measure(cache.read, 8)
        report["read_sse"] = measure(compact_read, 12)
        report["ticker_coverage"] = measure(lambda: cache._ticker_coverage_locked(now), 30)
        report["health"] = measure(lambda: cache._data_health_locked(now), 20)
        report["deepcopy_rows_only"] = measure(lambda: copy.deepcopy(cache._snapshot["options"]), 12)
        report["deepcopy_snapshot_without_endpoints"] = measure(lambda: copy.deepcopy({k: v for k, v in cache._snapshot.items() if k != "endpoints"}), 12)
        report["deepcopy_endpoints_only"] = measure(lambda: copy.deepcopy(cache._snapshot["endpoints"]), 12)
        sample = compact_read()
        report["json_sse"] = measure(lambda: json.dumps(sample, ensure_ascii=False, allow_nan=False, separators=(",", ":")), 12)
        profile = cProfile.Profile()
        profile.enable()
        for _ in range(8):
            compact_read()
        profile.disable()
        output = io.StringIO()
        pstats.Stats(profile, stream=output).strip_dirs().sort_stats("cumulative").print_stats(30)
        report["sse_profile"] = output.getvalue()
        event_counter = 0
        symbol, row = next(iter(cache._rows_by_symbol.items()))
        book_name, book_state = next((name, state) for name, state in cache._stream_states.items()
                                     if name.startswith("book-") and symbol in state.get("symbols", []))
        def book_update():
            nonlocal event_counter
            event_counter += 1
            event = dict(e="bookTicker", s=symbol, E=now + event_counter,
                         u=(row.get("book_update_id") or 0) + event_counter,
                         b=row["bid_price"], a=row["ask_price"], B=row["bid_quantity"], A=row["ask_quantity"])
            cache.apply_stream_message({"data": event, "_transport": {
                "connection": book_name, "generation": book_state["generation"]}})
        report["apply_book_no_readers"] = measure(book_update, 2500)
        mark_fields = {"mp": "mark_price", "vo": "mark_iv", "b": "bid_iv", "a": "ask_iv",
                       "d": "delta", "g": "gamma", "t": "theta", "v": "vega", "bo": "bid_price",
                       "ao": "ask_price", "bq": "bid_quantity", "aq": "ask_quantity"}
        mark_counter = 3000
        def mark_update():
            nonlocal mark_counter
            mark_counter += 1
            events = [dict(e="markPrice", s=item["symbol"], E=now + mark_counter,
                           i=cache._snapshot["btc_index_price"],
                           **{wire: item.get(field) for wire, field in mark_fields.items()})
                      for item in cache._rows_by_symbol.values()]
            cache.apply_stream_message({"data": events, "_transport": {
                "connection": "market", "generation": cache._stream_states["market"]["generation"]}})
        report["apply_692_mark_array_no_readers"] = measure(mark_update, 30)
        mark_profile = cProfile.Profile()
        mark_profile.enable()
        for _ in range(5):
            mark_update()
        mark_profile.disable()
        mark_output = io.StringIO()
        pstats.Stats(mark_profile, stream=mark_output).strip_dirs().sort_stats("cumulative").print_stats(20)
        report["mark_profile"] = mark_output.getvalue()
        # Book-only callback cost and time waiting for SSE-style reader locks.
        for clients in (1, 3):
            stop = threading.Event()
            reader_durations = []
            def reader():
                while not stop.is_set():
                    began = time.perf_counter()
                    value = compact_read()
                    reader_durations.append((time.perf_counter() - began) * 1000)
                    json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
                    stop.wait(.25)
            threads = [threading.Thread(target=reader) for _ in range(clients)]
            for thread in threads:
                thread.start()
            durations = []
            began = time.perf_counter()
            while time.perf_counter() - began < 3:
                start = time.perf_counter()
                book_update()
                durations.append((time.perf_counter() - start) * 1000)
                stop.wait(.003)
            stop.set()
            for thread in threads:
                thread.join(10)
            report["apply_book_with_%s_sse_clients" % clients] = {
                "messages": len(durations), "mean_ms": round(statistics.mean(durations), 3),
                "p95_ms": round(percentile(durations, .95), 3), "max_ms": round(max(durations), 3),
                "read_count": len(reader_durations), "read_mean_ms": round(statistics.mean(reader_durations), 3)}
        cache.stop()
    target = ROOT / "verification/cache-performance-profile-20261017.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in ("sse_profile", "mark_profile")}, ensure_ascii=False, indent=2))
    print(report["sse_profile"])
    print(report["mark_profile"])


if __name__ == "__main__":
    main()

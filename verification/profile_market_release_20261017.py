"""Bounded offline release profile. Does not open any network connection."""
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
from realtime_market import BookTickerMailbox
from profile_market_cache_20261017 import build_cache


def measure(call, count):
    rows = []
    for _ in range(count):
        wall, cpu = time.perf_counter(), time.process_time()
        call()
        rows.append({"wall_ms": (time.perf_counter()-wall)*1000,
                     "cpu_ms": (time.process_time()-cpu)*1000})
    return {"count": count, "wall_mean_ms": round(statistics.mean(x["wall_ms"] for x in rows), 3),
            "wall_max_ms": round(max(x["wall_ms"] for x in rows), 3),
            "cpu_mean_ms": round(statistics.mean(x["cpu_ms"] for x in rows), 3)}


path = ROOT / "verification/realtime-release-market-snapshot-20261017.json"
snapshot = json.loads(path.read_text(encoding="utf-8"))
report = {"source": str(path), "upstream_connections_opened": 0,
          "contracts": len(snapshot["options"]),
          "connection_state_json_bytes": len(json.dumps(snapshot["realtime"]["connection_details"])),
          "snapshot_json_bytes": len(json.dumps(snapshot)),
          "observed_connection_diagnostics": {name: state.get("diagnostics") for name, state in
                                              snapshot["realtime"]["connection_details"].items()}}
with tempfile.TemporaryDirectory() as directory:
    cache = build_cache(snapshot, directory)
    def read_sse():
        with cache._lock:
            return cache._read_locked(False)
    report["read_sse"] = measure(read_sse, 5)
    report["read_full"] = measure(cache.read, 5)
    result = read_sse()
    report["json_sse"] = measure(lambda: json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(",", ":")), 5)
    report["copy_states"] = measure(lambda: copy.deepcopy(cache._stream_states), 10)
    sequence = 0
    name, state = next((name, state) for name, state in cache._stream_states.items() if name.startswith("book-"))
    symbols = state["symbols"]
    mailbox = BookTickerMailbox(symbols, cache.apply_stream_message,
                                {"connection": name, "generation": state["generation"]}, start=False)
    def update_book_batch():
        global sequence
        sequence += 1
        now = int(time.time()*1000)
        events = []
        for symbol in symbols:
            row = cache._rows_by_symbol[symbol]
            events.append(dict(e="bookTicker", s=symbol, E=now + sequence,
                               u=(row.get("book_update_id") or 0)+sequence,
                               b=row["bid_price"], a=row["ask_price"],
                               B=row["bid_quantity"], A=row["ask_quantity"]))
        mailbox.offer(events, now)
        mailbox.dispatch_once()
    report["book_batch_size"] = len(symbols)
    report["book_mailbox_offer_and_apply_batch"] = measure(update_book_batch, 12)
    report["mailbox_diagnostics"] = mailbox.diagnostics()
    profile = cProfile.Profile()
    profile.enable()
    read_sse()
    update_book_batch()
    profile.disable()
    output = io.StringIO()
    pstats.Stats(profile, stream=output).strip_dirs().sort_stats("cumulative").print_stats(25)
    report["profile"] = output.getvalue()
    mailbox.close()
    cache.stop()
target = ROOT / "verification/cache-release-profile-20261017.json"
target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({k:v for k,v in report.items() if k not in ("profile", "observed_connection_diagnostics")}, ensure_ascii=False, indent=2))
print(report["profile"])

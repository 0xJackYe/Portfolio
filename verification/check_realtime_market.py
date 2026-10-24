"""Sample only the existing localhost public cache; never opens exchange sockets."""
import argparse
import datetime as dt
import json
from pathlib import Path
import time
import urllib.request


def millis(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        try:
            return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000
        except ValueError:
            return None
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--interval", type=float, default=6)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--save-snapshot", type=Path)
    args = parser.parse_args()
    if not 1 <= args.samples <= 10 or not 0 <= args.interval <= 15:
        parser.error("Use 1-10 samples, at intervals of 0-15 seconds.")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    records, previous = [], {}
    fields = ("bid_price", "ask_price", "bid_quantity", "ask_quantity")
    snapshot = None
    for index in range(args.samples):
        began = time.monotonic()
        with opener.open("http://127.0.0.1:8766/api/market", timeout=12) as response:
            snapshot = json.load(response)
        now = time.time() * 1000
        rows = snapshot.get("options", [])
        verified = [row for row in rows if (row.get("quote_verification") or {}).get("verified")]
        quiet = [row for row in verified if all(millis(row.get("field_updated_at", {}).get(field)) is not None
                 and now - millis(row["field_updated_at"][field]) > 20000 for field in fields)]
        current = {row["symbol"]: tuple(row.get(field) for field in fields) for row in rows}
        connections = snapshot.get("realtime", {}).get("connection_details", {})
        sample = {"received_at_beijing": dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat(),
                  "latency_seconds": round(time.monotonic() - began, 3),
                  "revision": snapshot.get("revision"), "contracts": len(rows),
                  "book_subscribed": snapshot.get("realtime", {}).get("book_symbol_count"),
                  "verified_quotes": len(verified), "quiet_verified_quotes": len(quiet),
                  "oct30_verified": sum(row["symbol"].startswith("BTC-261030-") for row in verified),
                  "quote_changes_since_previous": sum(symbol in previous and previous[symbol] != value for symbol, value in current.items()),
                  "btc_index": snapshot.get("btc_index_price"),
                  "index_age_seconds": round((now - millis(snapshot["index_updated_at"])) / 1000, 3) if millis(snapshot.get("index_updated_at")) else None,
                  "mark_age_seconds": round((now - millis(snapshot["realtime"]["channel_updated_at"]["mark"])) / 1000, 3) if millis(snapshot.get("realtime", {}).get("channel_updated_at", {}).get("mark")) else None,
                  "connections": {name: {key: state.get(key) for key in ("connected", "subscription_confirmed", "generation", "plan_generation", "opened_at_ms", "verified_at", "heartbeat_at", "heartbeat_kind", "heartbeat_request_id", "error_type", "diagnostics", "last_disconnect")} for name, state in connections.items()},
                  "quiet_example": [{"symbol": row["symbol"], "quote_updated_at": row.get("quote_updated_at"), "verification": row.get("quote_verification")} for row in quiet[:1]]}
        records.append(sample)
        print(json.dumps({key: value for key, value in sample.items() if key not in ("connections", "quiet_example")}, ensure_ascii=False), flush=True)
        previous = current
        if index + 1 < args.samples:
            time.sleep(args.interval)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"source": "Existing local public market cache", "samples": records}, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.save_snapshot:
        args.save_snapshot.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()

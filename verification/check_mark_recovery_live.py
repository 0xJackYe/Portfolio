"""Bounded live QA of public mark recovery through the local service only."""
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path


BASE = "http://127.0.0.1:8766"
SYMBOLS = ["BTC-261030-63000-P", "BTC-261030-62000-P", "BTC-261030-64000-P", "BTC-261030-65000-P"]
ROOT = Path(__file__).resolve().parent
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def read(path):
    with opener.open(BASE + path, timeout=15) as response:
        return json.load(response)


def main():
    started = time.monotonic()
    samples, errors = [], []
    next_watch = 0
    last_snapshot = None
    while time.monotonic() - started < 100:
        elapsed = time.monotonic() - started
        try:
            if elapsed >= next_watch:
                read("/api/mark-watch?" + urllib.parse.urlencode({"symbols": ",".join(SYMBOLS)}))
                next_watch = elapsed + 10
            snap = read("/api/market")
            now = time.time() * 1000
            by_symbol = {row["symbol"]: row for row in snap["options"]}
            marks = {}
            for symbol in SYMBOLS:
                row = by_symbol[symbol]
                stamps = [row.get("field_updated_at", {}).get(field) for field in ("mark_price", "mark_iv")]
                age = max((now - stamp) / 1000 for stamp in stamps) if all(stamps) else None
                source = row.get("field_source", {}).get("mark_price", row.get("mark_source"))
                fresh = age is not None and 0 <= age <= (20 if source == "websocket" else 30)
                marks[symbol] = {"price": row["mark_price"], "iv": row["mark_iv"], "source": source,
                                 "age_seconds": round(age, 3) if age is not None else None, "fresh": fresh}
            sample = {"elapsed": round(elapsed, 2), "marks": marks, "recovery": snap.get("mark_recovery")}
            samples.append(sample)
            last_snapshot = {key: value for key, value in snap.items() if key != "endpoints"}
            if len(samples) % 5 == 1:
                print("elapsed=%.0fs ages=%s" % (elapsed, [value["age_seconds"] for value in marks.values()]), flush=True)
        except Exception as exc:
            errors.append({"elapsed": round(elapsed, 2), "type": type(exc).__name__})
        time.sleep(3)
    checked = [sample for sample in samples if sample["elapsed"] >= 10]
    stale = [sample for sample in checked if not all(mark["fresh"] for mark in sample["marks"].values())]
    report = {"scope": "Bounded public-data live QA; no account or order access", "samples": samples,
              "errors": errors, "evaluated_samples": len(checked), "stale_samples": len(stale),
              "all_fresh_after_warmup": bool(checked) and not stale and not errors}
    (ROOT / "mark-recovery-live-20261018.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if last_snapshot:
        (ROOT / "mark-recovery-live-snapshot-20261018.json").write_text(json.dumps(last_snapshot, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "samples"}), flush=True)
    return 0 if report["all_fresh_after_warmup"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

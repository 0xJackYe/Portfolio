"""Read-only live acceptance; never reads credentials or sends orders."""
import json
import math
from pathlib import Path
import re
import statistics
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from option_ai_engine import screen_snapshot

BASE = "http://127.0.0.1:8766"


def request(path, body=None, port=8766):
    headers = {"X-Terminal-Request": "1", "Content-Type": "application/json"}
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    with urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:%s" % port + path, data=data, headers=headers), timeout=8) as response:
        return json.load(response)


def sse_revision(last=None):
    headers = {} if last is None else {"Last-Event-ID": str(last)}
    with urllib.request.urlopen(urllib.request.Request(BASE + "/api/events", headers=headers), timeout=8) as response:
        raw = b""
        deadline = time.monotonic() + 8
        while len(raw) < 8 * 1024 * 1024 and time.monotonic() < deadline:
            raw += response.read1(65536)
            if b"event: snapshot" in raw and b"\n\n" in raw[raw.find(b"event: snapshot"):]:
                ids = re.findall(rb"(?:^|\n)id: (\d+)\n", raw)
                if ids:
                    return int(ids[-1])
    raise AssertionError("No live market frame")


def main():
    report = {"checks": {}, "read_only": True}
    checks = report["checks"]
    status = request("/api/option-ai/status")
    checks["real_user_key_configured"] = status["configured"]
    checks["official_models_verified"] = status["models_verified"] and all(item.get("available") for item in status["models"])
    report["models"] = status["models"]
    snapshot = request("/api/market")
    checks["market_live"] = not snapshot.get("stale") and bool(snapshot.get("options"))
    first = sse_revision()
    second = sse_revision(first)
    checks["sse_close_and_resume"] = second > first
    report["stream_revisions"] = [first, second]
    # Exactly one real provider call for the complete local relay pipeline.
    question = "筛选 2026年10月30日到期的卖 Put，虚值0%到20%，数量0.03 BTC，按每日权利金从高到低取5个。"
    started = time.perf_counter()
    submitted = request("/api/option-ai/jobs", {"question": question, "model": "deepseek-flash"})
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        job = request("/api/option-ai/jobs/" + submitted["job_id"])
        if job["status"] in ("complete", "failed", "cancelled"):
            break
        time.sleep(.1)
    if job["status"] != "complete":
        raise AssertionError("Live AI job did not complete")
    result = job["result"]
    report["pipeline_latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
    report["result"] = result
    checks["intent_matches_explicit_request"] = all((result["criteria"]["direction"] == "SELL", result["criteria"]["type"] == "PUT",
        result["criteria"]["expiry"] == "2026-10-30", result["criteria"]["quantity"] == .03,
        result["criteria"]["min_otm_pct"] == 0, result["criteria"]["max_otm_pct"] == 20, result["criteria"]["limit"] == 5))
    checks["actual_candidates"] = bool(result["candidates"]) and all(c["symbol"] in {row["symbol"] for row in snapshot["options"]} for c in result["candidates"])
    checks["independent_daily_premium_math"] = all(math.isclose(c["daily_premium"], c["quote_price"] * c["quantity"] * c["unit"] / ((c["expiry_ms"] - result["snapshot"]["exchange_now_ms"]) / 86400000), rel_tol=1e-12) for c in result["candidates"])
    refreshed = request("/api/option-ai/jobs/" + submitted["job_id"] + "/revalidate", {})["result"]
    checks["refresh_retains_criteria_and_usage"] = refreshed["criteria"] == result["criteria"] and refreshed["usage"] == result["usage"] and refreshed["snapshot"]["revision"] >= result["snapshot"]["revision"]
    selected = request("/api/option-ai/selection", {"symbol": refreshed["candidates"][0]["symbol"], "criteria": refreshed["criteria"]})
    checks["selection_uses_exact_current_bid"] = selected["candidate"]["quote_price"] == float(selected["row"]["bid_price"])
    checks["selection_uses_same_snapshot_index"] = math.isclose(selected["candidate"]["otm_pct"], (1 - float(selected["row"]["strike_price"]) / float(selected["snapshot"]["btc_index_price"])) * 100, rel_tol=1e-12)
    report["selected"] = {"symbol": selected["candidate"]["symbol"], "revision": selected["snapshot"]["revision"], "quote": selected["candidate"]["quote_price"]}
    timings = []
    for _ in range(20):
        current = request("/api/market")
        start = time.perf_counter()
        screen_snapshot(current, {"direction": "SELL", "type": "PUT", "min_otm_pct": 0, "limit": 10})
        timings.append((time.perf_counter() - start) * 1000)
    report["local_screening"] = {"contracts": len(current["options"]), "runs": len(timings),
                                 "median_ms": round(statistics.median(timings), 3), "max_ms": round(max(timings), 3)}
    checks["bounded_local_calculation"] = max(timings) < 250
    checks["legacy_port_shares_configuration"] = request("/api/option-ai/status", port=8765)["configured"]
    checks["terminal_still_available"] = isinstance(request("/api/terminal").get("settings"), dict)
    report["passed"] = all(checks.values())
    (Path(__file__).resolve().parent / "live-acceptance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "checks": checks, "pipeline_latency_ms": report["pipeline_latency_ms"], "local_screening": report["local_screening"]}, ensure_ascii=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

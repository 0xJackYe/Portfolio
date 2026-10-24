"""Four explicit live, read-only multi-turn intent checks on both models."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from option_ai_engine import validate_criteria
from live_acceptance import request


def run(model, question, previous, expected):
    start = time.perf_counter()
    job = request("/api/option-ai/jobs", {"model": model, "question": question,
                                        "previous_criteria": previous, "history": []})
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        result = request("/api/option-ai/jobs/" + job["job_id"])
        if result["status"] in ("complete", "failed", "cancelled"):
            break
        time.sleep(.1)
    actual = result.get("result", {})
    return {"model": model, "question": question, "status": result["status"],
            "criteria": actual.get("criteria"), "expected": expected,
            "passed": actual.get("criteria") == expected and not actual.get("needs_clarification"),
            "latency_ms": round((time.perf_counter() - start) * 1000), "usage": actual.get("usage")}


def main():
    previous = validate_criteria({"expiry": "2026-10-30", "quantity": .03, "min_otm_pct": 0, "max_otm_pct": 20, "limit": 5})
    cases = [("再加上绝对 Delta 不超过 0.25，其他条件保持不变。", dict(previous, max_abs_delta=.25)),
             ("重新开始，清除之前全部筛选条件。买入2026年10月30日到期的 Call，数量0.01 BTC，其余全部使用默认条件。", validate_criteria({"direction": "BUY", "type": "CALL", "expiry": "2026-10-30"}))]
    records = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        for question, expected in cases:
            futures = [pool.submit(run, model, question, previous, expected) for model in ("deepseek-flash", "deepseek-v4-pro")]
            records.extend(future.result() for future in futures)
    report = {"records": records, "paid_requests": 4, "passed": all(row["passed"] for row in records)}
    (Path(__file__).resolve().parent / "continuation-acceptance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "checks": [{"model": row["model"], "passed": row["passed"], "latency_ms": row["latency_ms"]} for row in records]}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

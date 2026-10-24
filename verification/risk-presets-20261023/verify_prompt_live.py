"""Bounded live risk commentary acceptance against public market facts only."""
from concurrent.futures import ThreadPoolExecutor
import json
import math
from pathlib import Path
import sys
import time
import urllib.request

DIRECTORY = Path(__file__).resolve().parent
sys.path.insert(0, str(DIRECTORY.parents[1]))
from deepseek_client import DeepSeekClient, DeepSeekError
from option_ai_explainer import RISK_SYSTEM_PROMPT
from option_ai_service import KeyVault
from option_risk_profiles import screen_risk_profile


def read_market():
    with urllib.request.urlopen("http://127.0.0.1:8766/api/market", timeout=8) as response:
        return json.load(response)


def run(profile, model):
    snapshot = read_market()
    result = screen_risk_profile(snapshot, profile, expiry="2026-10-30", quantity=.01)
    record = {"profile": profile, "model": model, "local": result}
    if not result["candidates"]:
        record.update(passed=False, error="no_live_candidates")
        return record
    try:
        client = DeepSeekClient(KeyVault().read)
        explanation = client.explain(result, model)
        symbols = {row["symbol"] for row in result["candidates"]}
        checks = {
            "same_contract_set": {row["symbol"] for row in explanation["candidates"]} == symbols,
            "no_numeric_narrative": not any(char.isdigit() for char in explanation["overview"] + "".join(row["text"] for row in explanation["candidates"])),
            "independent_credit": all(math.isclose(row["premium_total"], row["quote_price"] * row["quantity"] * row["unit"], rel_tol=1e-12) for row in result["candidates"]),
            "independent_cash_max_loss": all(math.isclose(row["max_loss_gross"], row["strike"] * row["quantity"] * row["unit"] - row["premium_total"], rel_tol=1e-12) for row in result["candidates"]),
            "independent_stress": all(math.isclose(point["pnl_gross"], row["premium_total"] - max(row["strike"] - point["settlement"], 0) * row["quantity"] * row["unit"], rel_tol=1e-12, abs_tol=1e-12) for row in result["candidates"] for point in row["stress_scenarios"]),
        }
        record.update(explanation=explanation, checks=checks, passed=explanation["status"] == "complete" and all(checks.values()))
    except DeepSeekError as exc:
        record.update(passed=False, error=exc.code)
    return record


def main():
    records = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        # Both supported models and all three buttons use the same new prompt.
        for profile in ("low", "medium", "high"):
            records.extend(future.result() for future in [pool.submit(run, profile, model)
                           for model in ("deepseek-flash", "deepseek-v4-pro")])
    report = {"passed": all(row["passed"] for row in records), "records": records,
              "maximum_concurrency": 2, "read_only": True, "requested_calls": 6}
    (DIRECTORY / "live-prompt-results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (DIRECTORY / "系统提示词.md").write_text("# 期权风险分档解读系统提示词\n\n" + RISK_SYSTEM_PROMPT + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "records": [{"profile": row["profile"], "model": row["model"], "passed": row["passed"], "error": row.get("error"), "latency_ms": row.get("explanation", {}).get("latency_ms")} for row in records]}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

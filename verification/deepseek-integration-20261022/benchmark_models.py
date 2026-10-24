"""Explicit, bounded live comparison. Running this file makes <= 12 paid calls.

Credentials are read from the current user's DPAPI vault. No keys, HTTP bodies,
Authorization headers or hidden reasoning are logged or persisted. Importing
this module makes no network calls. HTTP retries are disabled for this run.
"""
import concurrent.futures
import datetime as dt
import json
import math
from pathlib import Path
import re
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request


DIRECTORY = Path(__file__).resolve().parent
PROJECT = DIRECTORY.parents[1]
sys.path.insert(0, str(PROJECT))
from deepseek_client import DeepSeekClient, DeepSeekError, _verified_opener
from option_ai_engine import DEFAULTS, validate_criteria
from option_ai_service import KeyVault, OptionAIService


MODELS = ("deepseek-flash", "deepseek-v4-pro")
AUTH_FAILURES = {"authentication", "insufficient_balance", "access_denied", "key_missing", "key_unavailable"}
REPORT_JSON = DIRECTORY / "model-benchmark-results.json"
REPORT_MD = DIRECTORY / "model-benchmark-report.md"


class NoRetryOpener:
    """Translate HTTP errors before the production client's retry boundary."""
    def __init__(self):
        self.opener = _verified_opener()
        self.calls = 0
        self.lock = threading.Lock()

    def open(self, request, timeout):
        with self.lock:
            self.calls += 1
        try:
            return self.opener.open(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            status = exc.code
            exc.close()
            if 300 <= status < 400:
                raise DeepSeekError("redirect_rejected", "模型服务返回了不支持的重定向。") from None
            raise DeepSeekClient._http_error(status) from None


def cases_for(context):
    expiries = context.get("available_expiries", [])
    now_date = context["beijing_now"][:10]
    available = [value for value in expiries if isinstance(value, str) and value >= now_date]
    october = [value for value in available if value.endswith("-10-30")]
    if not available or not october:
        raise ValueError("公开快照没有实际的 10 月 30 日到期日，停止对比而不编造到期日。")
    sell_call_expiry, buy_put_expiry = october[0], available[0]
    return [
        {"id": "sell_put_days_otm", "question": "卖出 Put，剩余7到20天，虚值比例至少15%，模拟0.01 BTC，最多5张，按平均每日权利金从高到低。",
         "expected": dict(DEFAULTS, min_days=7, max_days=20, min_otm_pct=15, limit=5)},
        {"id": "sell_call_expiry_strike_delta", "question": "卖出%s到期的 Call，行权价至少90000 USDT，绝对Delta不超过0.25，模拟0.02 BTC，最多5张，按平均每日权利金从高到低。" % sell_call_expiry,
         "expected": dict(DEFAULTS, type="CALL", expiry=sell_call_expiry, min_strike=90000,
                          max_abs_delta=.25, quantity=.02, limit=5)},
        {"id": "buy_put_expiry", "question": "买入%s到期的 Put，模拟数量0.01 BTC，其余使用默认筛选口径。" % buy_put_expiry,
         "expected": dict(DEFAULTS, direction="BUY", expiry=buy_put_expiry)},
        {"id": "sell_put_iv_days_spread", "question": "卖出 Put，隐含波动率40%%到80%%，剩余30到90天，买卖价差相对中间价不超过15%%，其他使用默认筛选口径。",
         "expected": dict(DEFAULTS, min_iv=.4, max_iv=.8, min_days=30, max_days=90, max_spread_pct=15)},
        {"id": "sell_put_daily_premium", "question": "卖出 Put，模拟0.1 BTC，整笔平均每天权利金至少1 USDT；其他使用默认筛选口径。",
         "expected": dict(DEFAULTS, quantity=.1, min_daily_premium=1)},
        {"id": "qualitative_profit_guarantee", "question": "帮我找安全稳赚、收益最高的期权。",
         "expected": {}, "requires_clarification": True},
    ]


def same(actual, expected):
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        return (not isinstance(actual, bool) and isinstance(actual, (int, float))
                and math.isfinite(actual) and math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-9))
    return actual == expected


def score(case, plan):
    actual = validate_criteria(plan["criteria"])
    clarification = bool(isinstance(plan.get("clarification"), str) and plan["clarification"].strip())
    checks = []
    fields = case["expected"]
    if case.get("requires_clarification"):
        checks.append({"field": "clarification", "expected": True, "actual": clarification, "pass": clarification})
        extras = set(actual) - set(DEFAULTS)
        for field in sorted(extras):
            checks.append({"field": field, "expected": "未要求的数值不得猜测", "actual": actual[field], "pass": False})
        # Defaults may be populated while asking a clarifying question, but no
        # selection should proceed until the clarification is resolved.
    else:
        checks.append({"field": "clarification", "expected": False, "actual": clarification, "pass": not clarification})
        for field, expected in fields.items():
            checks.append({"field": field, "expected": expected, "actual": actual.get(field),
                           "pass": same(actual.get(field), expected)})
        for field in sorted(set(actual) - set(fields)):
            checks.append({"field": field, "expected": "用户未要求，不应附加", "actual": actual[field], "pass": False})
    text = plan.get("answer", "") + (plan.get("clarification") or "")
    unsafe_contract = bool(re.search(r"BTC-\d{6}-\d+(?:\.\d+)?-[CP]", text))
    unsafe_order = "订单已提交" in text or "已替你下单" in text
    checks.append({"field": "no_invented_contract_or_order", "expected": True,
                   "actual": not (unsafe_contract or unsafe_order), "pass": not (unsafe_contract or unsafe_order)})
    return actual, checks


def safe_text(text, secret):
    if not isinstance(text, str):
        return text
    return re.sub(r"sk-[A-Za-z0-9_-]{8,}", "[密钥已隐藏]", text.replace(secret, "[密钥已隐藏]"))


def run_one(client, model, case, context, stop, secret):
    started = time.monotonic()
    try:
        plan = client.parse(case["question"], model, context, cancel_event=stop)
        normalized, checks = score(case, plan)
        return {"model": model, "case_id": case["id"], "status": "complete",
                "returned_model": safe_text(plan.get("model"), secret),
                "criteria": normalized, "answer": safe_text(plan["answer"], secret),
                "clarification": safe_text(plan.get("clarification"), secret),
                "latency_ms": plan["latency_ms"], "usage": plan["usage"], "checks": checks,
                "passed_fields": sum(item["pass"] for item in checks), "total_fields": len(checks),
                "pass": all(item["pass"] for item in checks)}
    except DeepSeekError as exc:
        if exc.code in AUTH_FAILURES:
            stop.set()
        return {"model": model, "case_id": case["id"], "status": "error", "error": {
            "code": exc.code, "message": safe_text(exc.message, secret), "status": exc.status},
            "latency_ms": int((time.monotonic() - started) * 1000), "pass": False}
    except ValueError:
        return {"model": model, "case_id": case["id"], "status": "error", "error": {
            "code": "invalid_criteria", "message": "模型条件未通过本地规范化校验。"},
            "latency_ms": int((time.monotonic() - started) * 1000), "pass": False}
    except Exception:
        return {"model": model, "case_id": case["id"], "status": "error", "error": {
            "code": "benchmark_unavailable", "message": "对比过程失败，未记录未经清理的异常内容。"},
            "latency_ms": int((time.monotonic() - started) * 1000), "pass": False}


def summarize(records):
    result = []
    for model in MODELS:
        rows = [record for record in records if record["model"] == model]
        completed = [row for row in rows if row["status"] == "complete"]
        result.append({"model": model, "attempted_cases": len(rows), "completed_cases": len(completed),
            "passed_cases": sum(row["pass"] for row in rows),
            "passed_fields": sum(row.get("passed_fields", 0) for row in rows),
            "total_fields": sum(row.get("total_fields", 0) for row in rows),
            "median_latency_ms": round(statistics.median([row["latency_ms"] for row in completed])) if completed else None,
            "total_tokens": sum(row.get("usage", {}).get("total_tokens", 0) for row in rows),
            "errors": [{"case_id": row["case_id"], **row["error"]} for row in rows if row["status"] != "complete"]})
    eligible = [row for row in result if row["attempted_cases"] == 6 and row["completed_cases"] == 6]
    if len(eligible) != 2:
        return result, None
    recommended = max(eligible, key=lambda row: (
        row["passed_cases"], row["passed_fields"] / max(1, row["total_fields"]), -row["median_latency_ms"]))["model"]
    return result, recommended


def persist(report, secret):
    report["summary"], report["recommended_default"] = summarize(report["records"])
    clean_json = safe_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), secret)
    REPORT_JSON.write_text(clean_json + "\n", encoding="utf-8")
    lines = ["# DeepSeek 期权筛选实测", "", "测试时间：" + report["started_at_beijing"], "",
        "两个模型使用相同公开行情摘要、六条中文需求、同一提示词和输出上限；并发最多 2，关闭 HTTP 重试。",
        "测试衡量条件提取准确率与响应延迟，不衡量交易策略的预期收益。单次小样本不代表长期服务水平。", "",
        "| 模型 | 完成 | 整题正确 | 字段正确 | 中位延迟 | Token 总量 |", "|---|---:|---:|---:|---:|---:|"]
    for row in report["summary"]:
        latency = "—" if row["median_latency_ms"] is None else "%.2f 秒" % (row["median_latency_ms"] / 1000)
        lines.append("| %s | %s/6 | %s/6 | %s/%s | %s | %s |" % (
            row["model"], row["completed_cases"], row["passed_cases"], row["passed_fields"], row["total_fields"], latency, row["total_tokens"]))
    lines += ["", "推荐默认模型：" + (report["recommended_default"] or "尚无可判定结果。"), ""]
    if report.get("blocker"):
        lines += ["停止原因：" + report["blocker"]["message"], ""]
    for row in report["records"]:
        failed = [item["field"] for item in row.get("checks", []) if not item["pass"]]
        if row.get("error") or failed:
            lines.append("- %s / %s：%s" % (row["model"], row["case_id"],
                row["error"]["message"] if row.get("error") else "字段不符：" + "、".join(failed)))
    lines += ["", "完整规范化条件、简短回复、澄清问题、逐字段评分、实际返回模型和用量保存在同目录 JSON 中。",
        "未保存密钥、Authorization、原始响应体或隐藏推理。",
        "", "[官方模型列表](https://api-docs.deepseek.com/api/list-models/) · [官方接口](https://api-docs.deepseek.com/api/create-chat-completion/)"]
    REPORT_MD.write_text(safe_text("\n".join(lines) + "\n", secret), encoding="utf-8")


def main():
    secret = KeyVault().read()
    started = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat()
    report = {"started_at_beijing": started, "max_concurrency": 2, "http_retries": 0,
              "max_paid_calls": 12, "records": [], "models": [], "cases": []}
    if not secret:
        report["blocker"] = {"code": "key_missing", "message": "本机凭据保护目录没有可读取的 API Key。"}
        persist(report, "unused-placeholder-secret")
        print("STOP key_missing: no paid calls made", flush=True)
        return 2
    adapter = NoRetryOpener()
    client = DeepSeekClient(lambda: secret, opener=adapter)
    try:
        report["models"] = client.list_models()
        actual_ids = {row["id"] for row in report["models"]}
        if not set(MODELS) <= actual_ids:
            raise DeepSeekError("models_unavailable", "实际模型列表没有同时提供两个目标模型，停止付费对比。")
        print("MODELS verified: " + ", ".join(row["id"] for row in report["models"]), flush=True)
        with urllib.request.urlopen("http://127.0.0.1:8766/api/market", timeout=15) as response:
            snapshot = json.load(response)
        context = OptionAIService._context(snapshot)
        cases = cases_for(context)
        report["context"] = context
        report["cases"] = cases
        report["public_contracts"] = len(snapshot.get("options", []))
        persist(report, secret)
        stop = threading.Event()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            for index, case in enumerate(cases, 1):
                if stop.is_set():
                    break
                print("CASE %s/6 %s started" % (index, case["id"]), flush=True)
                futures = [executor.submit(run_one, client, model, case, context, stop, secret) for model in MODELS]
                for future in concurrent.futures.as_completed(futures):
                    row = future.result()
                    report["records"].append(row)
                    report["http_calls"] = adapter.calls
                    if row.get("error", {}).get("code") in AUTH_FAILURES:
                        report["blocker"] = row["error"]
                        stop.set()
                    persist(report, secret)
                    print("RESULT %s %s %s latency_ms=%s fields=%s/%s" % (
                        row["model"], row["case_id"], "pass" if row["pass"] else row.get("error", {}).get("code", "field_mismatch"),
                        row["latency_ms"], row.get("passed_fields", 0), row.get("total_fields", 0)), flush=True)
                if stop.is_set():
                    break
    except DeepSeekError as exc:
        report["blocker"] = {"code": exc.code, "message": safe_text(exc.message, secret), "status": exc.status}
    except Exception:
        report["blocker"] = {"code": "benchmark_setup_failed", "message": "无法读取实时行情或准备基准，未发送额外付费请求。"}
    report["http_calls"] = adapter.calls
    report["finished_at_beijing"] = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat()
    persist(report, secret)
    print("DONE recommended_default=" + str(report["recommended_default"]) + " http_calls=" + str(adapter.calls), flush=True)
    if report.get("blocker"):
        print("STOP " + report["blocker"]["code"], flush=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

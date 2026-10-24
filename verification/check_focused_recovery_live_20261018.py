"""Observe the real local focused market API without contacting Binance directly.

Run after deploying the local service. This is an observer, not a fixture that
claims a pass: transport, freshness, liquidity and actual UI/engine outcomes are
reported separately. Only the local public watch and telemetry routes are used.
"""
import argparse
import collections
import datetime as dt
import json
import math
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SYMBOLS = ("BTC-261030-62000-P", "BTC-261030-63000-P",
                   "BTC-261030-64000-P", "BTC-261030-65000-P")
MAX_RESPONSE_BYTES = 512 * 1024
BEIJING = dt.timezone(dt.timedelta(hours=8))

NODE_HELPER = r"""
const path = require('node:path');
const readline = require('node:readline');
const root = process.argv[1];
const risk = require(path.join(root, 'dashboard', 'dist', 'risk-ui.js'));
const engine = require(path.join(root, 'dashboard', 'dist', 'sell-put-engine.js'));
const settings = engine.normalizeSettings({}).settings;
const numeric = v => typeof v === 'boolean' || v === null || v === '' || v === undefined
  ? null : Number.isFinite(Number(v)) ? Number(v) : null;
const stamp = v => typeof v === 'number' ? numeric(v)
  : typeof v === 'string' && Number.isFinite(Date.parse(v)) ? Date.parse(v) : null;
function observation(value, received, source, now, limit, proof=false) {
  const at=stamp(received), age=at===null ? null : now-at;
  let state='fresh';
  if (numeric(value)===null) state='missing_value';
  else if (at===null || at<=0) state='missing_time';
  else if (age < -2000) state='future_time';
  else if (age>limit) state=proof?'old_change_verified_by_live_book':'stale';
  return {value,updatedAt:received??null,source:source??null,ageMs:age,limitMs:limit,
    state,fresh:state==='fresh'||state==='old_change_verified_by_live_book'};
}
function category(issue, row) {
  if(!issue)return 'calculable';
  if (/陈旧|时间未知|时间异常|更新时间未知|更新时间.*异常|核验过旧/.test(issue))return 'freshness';
  if (/无有效买一报价/.test(issue) || numeric(row.bid_price)===0)return 'zero_bid';
  if (/价差/.test(issue))return 'spread';
  if (/深度不足|最小开仓数量/.test(issue))return 'liquidity_or_size';
  if (/偏离|交叉|等待同步|盘口快照待核验/.test(issue))return 'synchronization_or_integrity';
  if (/缺失|未知|规则|模块不可用/.test(issue))return 'data_or_metadata_missing';
  if (/余额|保证金不足|数量|资金|可交易状态|已到期|只支持|仅支持/.test(issue))return 'risk_or_contract_hard_failure';
  return 'other_hard_failure';
}
function analyze(snapshot, now, symbols) {
  const rows=new Map((snapshot.options??[]).map(row=>[row.symbol,row]));
  const index=observation(snapshot.btc_index_price,snapshot.index_updated_at,
    snapshot.index_source,now,snapshot.index_source==='websocket'?20000:30000);
  if (!(numeric(snapshot.btc_index_price)>0)) {index.state='invalid_value';index.fresh=false;}
  const catalogAt=stamp(snapshot.catalog_updated_at), catalogAge=catalogAt===null?null:now-catalogAt;
  const catalog={updatedAt:snapshot.catalog_updated_at??null,ageMs:catalogAge,limitMs:600000,
    fresh:catalogAt!==null&&catalogAt>0&&catalogAge>=-2000&&catalogAge<=600000};
  const out=[];
  for(const symbol of symbols) {
    const row=rows.get(symbol);
    if(!row){out.push({symbol,missing:true,criticalFresh:false,freshnessFailures:['missing_contract'],category:'missing_contract'});continue;}
    const proofValid=risk.isVerifiedBook(row,now);
    const fields={}, failures=[];
    for(const field of ['bid_price','ask_price','bid_quantity','ask_quantity']) {
      const source=row.field_source?.[field]??row.quote_source;
      const received=Object.hasOwn(row.field_updated_at??{},field)?row.field_updated_at[field]:row.quote_updated_at;
      fields[field]={...observation(row[field],received,source,now,source==='websocket'?20000:30000,proofValid),
        groupUpdatedAt:row.quote_updated_at??null,groupEventMs:row.quote_event_ms??null,
        fieldEventMs:row.field_event_ms?.[field]??null,groupSource:row.quote_source??null};
      if(!fields[field].fresh)failures.push(field+':'+fields[field].state);
    }
    const markFields={};
    for(const field of ['mark_price','mark_iv','delta','gamma','theta','vega','bid_iv','ask_iv']) {
      const source=row.field_source?.[field]??row.mark_source;
      markFields[field]={...observation(row[field],row.field_updated_at?.[field]??row.mark_updated_at,
        source,now,source==='websocket'?20000:30000),groupUpdatedAt:row.mark_updated_at??null,
        groupEventMs:row.mark_event_ms??null,fieldEventMs:row.field_event_ms?.[field]??null};
      if(['mark_price','mark_iv'].includes(field)&&!markFields[field].fresh)failures.push(field+':'+markFields[field].state);
    }
    if(!index.fresh)failures.push('index:'+index.state);
    if(!catalog.fresh)failures.push('catalog:stale_or_unknown_time');
    const minimum=numeric(row.min_qty)>0?numeric(row.min_qty):.01;
    const quoteIssueMinimum=risk.quoteIssue(snapshot,row,{direction:'SELL',quantity:minimum},now);
    const quoteIssuePointOne=risk.quoteIssue(snapshot,row,{direction:'SELL',quantity:.1},now);
    const entry=engine.analyzeCandidate(snapshot,row,settings,now);
    out.push({symbol,missing:false,criticalFresh:failures.length===0,freshnessFailures:failures,
      quoteFields:fields,markFields,proofValid,proof:row.quote_verification??null,
      quoteVerifiedAt:row.quote_verified_at??null,quoteIssueMinimum,quoteIssuePointOne,
      engineIssue:entry.issue,category:category(entry.issue,row),calculable:Boolean(entry.metrics),
      engineWarnings:entry.warnings,metrics:entry.metrics?{
        quantity:entry.metrics.quantity,orderMargin:entry.metrics.orderMargin,
        netPremium:entry.metrics.netPremium,spreadPct:entry.metrics.spreadPct,
        marginRatio:entry.metrics.marginRatio}:null});
  }
  const strategy=engine.evaluate(snapshot,{},now);
  return {index,catalog,rows:out,criticalFresh:out.every(row=>row.criticalFresh),
    defaultStrategy:{issues:strategy.issues,includedSymbols:strategy.rows.map(row=>row.symbol),
      calculableSymbols:strategy.rows.filter(row=>row.metrics).map(row=>row.symbol),
      excludedSymbols:symbols.filter(symbol=>!strategy.rows.some(row=>row.symbol===symbol))}};
}
process.stdout.write(JSON.stringify({ready:true})+'\n');
readline.createInterface({input:process.stdin,crlfDelay:Infinity}).on('line',line=>{
  try {const input=JSON.parse(line);process.stdout.write(JSON.stringify({ok:true,
    analysis:analyze(input.snapshot,input.now,input.symbols)})+'\n');}
  catch(error){process.stdout.write(JSON.stringify({ok:false,errorType:error?.name??'Error'})+'\n');}
});
"""


class LocalOnlyRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        raise urllib.error.HTTPError(request.full_url, code, "Redirect rejected", headers, fp)


class NodeAnalyzer:
    def __init__(self, node):
        self.process = subprocess.Popen([node, "-e", NODE_HELPER, str(ROOT)], cwd=ROOT,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.lines = queue.Queue()

        def read_lines():
            try:
                for line in self.process.stdout:
                    self.lines.put(line)
            except (OSError, ValueError):
                pass
            finally:
                self.lines.put(None)

        threading.Thread(target=read_lines, name="focused-soak-node-reader", daemon=True).start()
        try:
            ready = self.receive().get("ready") is True
        except (OSError, RuntimeError, ValueError, queue.Empty):
            self.close()
            raise
        if not ready:
            self.close()
            raise RuntimeError("Node helper did not initialize")

    def receive(self):
        line = self.lines.get(timeout=5)
        if line is None:
            raise RuntimeError("Node helper exited")
        return json.loads(line)

    def analyze(self, snapshot, now, symbols):
        self.process.stdin.write(json.dumps({"snapshot": snapshot, "now": now, "symbols": symbols},
            ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n")
        self.process.stdin.flush()
        result = self.receive()
        if not result.get("ok"):
            raise RuntimeError("Node helper analysis failed")
        return result["analysis"]

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
        for stream in (self.process.stdin, self.process.stdout):
            if stream:
                stream.close()


def read_local(opener, port, route, symbols):
    # The origin is fixed to loopback and proxy/redirect handling is disabled.
    url = "http://127.0.0.1:%s/api/%s?" % (port, route) + urllib.parse.urlencode({"symbols": ",".join(symbols)})
    began = time.monotonic()
    try:
        with opener.open(urllib.request.Request(url, headers={"Accept": "application/json"}), timeout=5) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise ValueError("Oversized local telemetry response")
            value = json.loads(body.decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError("Invalid local telemetry response")
            return value, {"ok": True, "status": response.status,
                "latencyMs": round((time.monotonic() - began) * 1000, 2), "bytes": len(body)}
    except (OSError, ValueError) as error:
        # Exception messages may contain arbitrary response contents. Store only
        # type/status, never environment settings, credentials or raw errors.
        return None, {"ok": False, "status": getattr(error, "code", None),
            "errorType": type(error).__name__, "latencyMs": round((time.monotonic() - began) * 1000, 2)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=300, help="Observation seconds, default 300")
    parser.add_argument("--warmup", type=float, default=30, help="Report warmup separately, default 30 seconds")
    parser.add_argument("--interval", type=float, default=2, help="Focused telemetry interval, default 2 seconds")
    parser.add_argument("--watch-interval", type=float, default=10, help="Local public watch renewal, default 10 seconds")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--symbols", nargs="+", default=list(DEFAULT_SYMBOLS))
    parser.add_argument("--node", default=shutil.which("node") or "node")
    parser.add_argument("--output", type=Path, help="Report directory (default a timestamped verification directory)")
    args = parser.parse_args()
    if (not all(math.isfinite(value) for value in (args.duration, args.warmup, args.interval, args.watch_interval))
            or args.duration <= 0 or not 0 <= args.warmup < args.duration
            or args.interval < .5 or args.watch_interval < 5 or not 1 <= args.port <= 65535
            or not 1 <= len(args.symbols) <= 8 or any(not symbol.startswith("BTC-") for symbol in args.symbols)):
        parser.error("Invalid duration/warmup/interval/port or BTC contract list")
    args.symbols = list(dict.fromkeys(args.symbols))
    started_at = dt.datetime.now(BEIJING)
    output = args.output or ROOT / "verification" / ("focused-recovery-soak-" + started_at.strftime("%Y%m%d-%H%M%S"))
    output.mkdir(parents=True, exist_ok=True)
    frames_path, report_path = output / "frames.jsonl", output / "report.json"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), LocalOnlyRedirect())
    counts = {"all": collections.Counter(), "afterWarmup": collections.Counter()}
    failure_reasons = collections.Counter()
    category_counts = collections.Counter()
    maxima = {}
    first_failures = []
    watch_events = []
    analyzer, setup_failure = None, None
    try:
        analyzer = NodeAnalyzer(args.node)
    except (OSError, RuntimeError, ValueError, queue.Empty) as error:
        setup_failure = type(error).__name__
    started = time.monotonic()
    next_sample = next_watch = started
    interrupted = False

    def increment(key, measured, amount=1):
        counts["all"][key] += amount
        if measured:
            counts["afterWarmup"][key] += amount

    try:
        with frames_path.open("w", encoding="utf-8", newline="\n") as frames:
            while time.monotonic() - started < args.duration:
                current = time.monotonic()
                if current < next_sample:
                    time.sleep(min(.2, next_sample - current))
                    continue
                elapsed = current - started
                measured = elapsed >= args.warmup
                if current >= next_watch:
                    watched, transport = read_local(opener, args.port, "mark-watch", args.symbols)
                    accepted = watched.get("accepted", []) if watched else []
                    ok = transport["ok"] and accepted == args.symbols
                    watch_elapsed = time.monotonic() - started
                    watch_measured = watch_elapsed >= args.warmup
                    increment("watchSamples", watch_measured)
                    if not ok:
                        increment("watchFailures", watch_measured)
                    watch_events.append({"elapsedSeconds": round(watch_elapsed, 3), "transport": transport,
                                         "accepted": accepted, "ok": ok})
                    next_watch = time.monotonic() + args.watch_interval
                snapshot, transport = read_local(opener, args.port, "focused-market", args.symbols)
                now = int(time.time() * 1000)
                received_elapsed = time.monotonic() - started
                measured = received_elapsed >= args.warmup
                record = {"elapsedSeconds": round(received_elapsed, 3), "localReceivedAtMs": now,
                    "measured": measured, "transport": transport, "snapshot": snapshot, "analysis": None}
                increment("samples", measured)
                if not transport["ok"]:
                    increment("transportFailures", measured)
                elif analyzer is None:
                    increment("analysisFailures", measured)
                else:
                    try:
                        record["analysis"] = analyzer.analyze(snapshot, now, args.symbols)
                    except (OSError, RuntimeError, ValueError, queue.Empty) as error:
                        record["analysisErrorType"] = type(error).__name__
                        increment("analysisFailures", measured)
                    analysis = record["analysis"]
                    if analysis:
                        for name in ("index", "catalog"):
                            age = analysis[name]["ageMs"]
                            if age is not None:
                                maxima[name] = max(maxima.get(name, age), age)
                        if not analysis["criticalFresh"]:
                            increment("freshnessFailedSamples", measured)
                        for row in analysis["rows"]:
                            increment("contractSamples", measured)
                            if not row["criticalFresh"]:
                                increment("freshnessFailedContracts", measured)
                            if not row.get("calculable"):
                                increment("engineFailedContracts", measured)
                            if measured:
                                category_counts[row["category"]] += 1
                                for reason in row["freshnessFailures"]:
                                    failure_reasons[row["symbol"] + ":" + reason] += 1
                                if (row["freshnessFailures"] or row.get("engineIssue")) and len(first_failures) < 40:
                                    first_failures.append({"elapsedSeconds": record["elapsedSeconds"],
                                        "symbol": row["symbol"], "freshnessFailures": row["freshnessFailures"],
                                        "engineIssue": row.get("engineIssue"), "category": row["category"]})
                            for group in ("quoteFields", "markFields"):
                                for field, observation in row.get(group, {}).items():
                                    age = observation["ageMs"]
                                    if age is not None:
                                        key = row["symbol"] + ":" + field
                                        maxima[key] = max(maxima.get(key, age), age)
                frames.write(json.dumps(record, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n")
                frames.flush()
                next_sample += args.interval
                if next_sample < time.monotonic():
                    next_sample = time.monotonic() + args.interval
    except KeyboardInterrupt:
        interrupted = True
    finally:
        if analyzer:
            analyzer.close()

    elapsed = time.monotonic() - started
    measured = counts["afterWarmup"]
    gates = {"durationCompleted": not interrupted and elapsed >= args.duration,
        "hasPostWarmupSamples": measured["samples"] > 0,
        "actualUiAndEngineAnalysisAvailable": setup_failure is None and measured["analysisFailures"] == 0
            and measured["samples"] > 0 and measured["contractSamples"] == measured["samples"] * len(args.symbols),
        "localTelemetryRequestsSucceeded": measured["samples"] > 0 and measured["transportFailures"] == 0,
        "watchRenewalsSucceeded": measured["watchFailures"] == 0,
        "allCriticalMarketFieldsFresh": measured["contractSamples"] > 0 and measured["freshnessFailedSamples"] == 0,
        "allRequestedContractsEngineCalculable": measured["contractSamples"] > 0 and measured["engineFailedContracts"] == 0}
    report = {"startedAtBeijing": started_at.isoformat(), "finishedAtBeijing": dt.datetime.now(BEIJING).isoformat(),
        "requestedSeconds": args.duration, "observedSeconds": round(elapsed, 3), "warmupSeconds": args.warmup,
        "intervalSeconds": args.interval, "watchIntervalSeconds": args.watch_interval,
        "localOrigin": "http://127.0.0.1:%s" % args.port, "symbols": args.symbols,
        "gates": gates, "allGatesPassed": all(gates.values()),
        "dataRecoveryPassed": all(gates[key] for key in gates if key != "allRequestedContractsEngineCalculable"),
        "counts": {key: dict(value) for key, value in counts.items()},
        "postWarmupEngineCategories": dict(category_counts), "postWarmupFreshnessReasons": dict(failure_reasons),
        "maximumRawFieldAgeMsIncludingWarmup": maxima, "firstPostWarmupFailures": first_failures,
        "watchEvents": watch_events, "analysisSetupFailureType": setup_failure,
        "frames": str(frames_path.resolve()),
        "scope": "Public local telemetry only; no credentials, accounts or order endpoints. No direct upstream requests. "
                 "Watch renewals use the existing bounded local public-data recovery. Fresh book change-only fields "
                 "may have old change times only with the real current UI-validated WS certificate. "
                 "Mandatory fields: all four top-book fields, mark price, IV, BTC index and catalog time. "
                 "Optional Greek/IV fields retain independent raw ages. Strategy-filter exclusions are recorded, "
                 "and each requested contract is separately checked using the actual engine with default account settings."}
    report_path.write_text(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2), encoding="utf-8")
    print(json.dumps({"allGatesPassed": report["allGatesPassed"], "dataRecoveryPassed": report["dataRecoveryPassed"],
        "samples": counts["all"]["samples"], "postWarmupSamples": measured["samples"],
        "report": str(report_path.resolve()), "frames": str(frames_path.resolve())}, ensure_ascii=False))
    return 0 if report["allGatesPassed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

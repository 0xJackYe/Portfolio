"""Independently verify public order-book liquidity; never access an account."""
import concurrent.futures
import datetime as dt
import json
import pathlib
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent
SYMBOLS = [f"BTC-261030-{strike}-P" for strike in [60000, 64000, 65000, 70000, 75000]]


def fetch(symbol):
    url = "https://eapi.binance.com/eapi/v1/depth?" + urllib.parse.urlencode({"symbol": symbol, "limit": 10})
    metadata = {"symbol": symbol, "url": url, "started_local_utc": dt.datetime.now(dt.timezone.utc).isoformat()}
    req = urllib.request.Request(url, headers={"User-Agent": "local-btc-put-analysis/1.0"})
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                metadata.update({"http_status": response.status, "source_date": response.headers.get("Date"), "request_attempts": attempt + 1})
                payload = json.load(response)
            bids = payload.get("bids") or []
            asks = payload.get("asks") or []
            metadata.update({"ok": True, "T": payload.get("T"), "E": payload.get("E"), "lastUpdateId": payload.get("lastUpdateId"), "best_bid": bids[0] if bids else None, "best_ask": asks[0] if asks else None})
            return {"metadata": metadata, "payload": payload}
        except urllib.error.HTTPError as error:
            metadata.update({"ok": False, "http_status": error.code, "error": str(error), "body": error.read(2048).decode("utf-8", "replace"), "source_date": error.headers.get("Date"), "request_attempts": attempt + 1})
            return {"metadata": metadata}
        except (urllib.error.URLError, TimeoutError, ConnectionResetError) as error:
            if attempt:
                metadata.update({"ok": False, "error": repr(error), "request_attempts": attempt + 1})
                return {"metadata": metadata}
            time.sleep(1)
        except Exception as error:
            metadata.update({"ok": False, "error": repr(error), "request_attempts": attempt + 1})
            return {"metadata": metadata}


with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
    results = list(pool.map(fetch, SYMBOLS))
output = {"source": "Binance European Options public order-book depth", "public_only": True, "no_credentials": True, "limit": 10, "checks": results}
(ROOT / "depth_checks.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps([item["metadata"] for item in results], ensure_ascii=False, indent=2))

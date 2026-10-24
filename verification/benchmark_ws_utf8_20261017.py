"""Offline benchmark only; builds wire-shaped public frames from a saved cache."""
import json
import statistics
import time
from pathlib import Path

from websocket import ABNF
from websocket._abnf import continuous_frame
from websocket._utils import validate_utf8


def measure(fn, count=12):
    durations = []
    for _ in range(count):
        began = time.perf_counter()
        fn()
        durations.append((time.perf_counter() - began) * 1000)
    return {"median_ms": round(statistics.median(durations), 3),
            "min_ms": round(min(durations), 3), "max_ms": round(max(durations), 3),
            "iterations": count}


def main():
    root = Path(__file__).resolve().parent
    saved = json.loads((root / "ws-audit-ping-snapshot-20261017.json").read_text(encoding="utf8"))
    events = []
    for row in saved["options"]:
        event = {"e": "markPrice", "E": saved["server_now_ms"], "s": row["symbol"],
                 "i": saved["btc_index_price"]}
        for wire, name in {"mp": "mark_price", "vo": "mark_iv", "b": "bid_iv", "a": "ask_iv",
                           "d": "delta", "g": "gamma", "t": "theta", "v": "vega",
                           "bo": "bid_price", "ao": "ask_price", "bq": "bid_quantity",
                           "aq": "ask_quantity"}.items():
            event[wire] = row.get(name, "0")
        events.append(event)
    mark = json.dumps({"stream": "btcusdt@optionMarkPrice", "data": events},
                      separators=(",", ":"), ensure_ascii=False).encode("utf8")
    quote = json.dumps({"stream": "btc-261030-82000-p@bookTicker", "data": {
        "e": "bookTicker", "E": saved["server_now_ms"], "T": saved["server_now_ms"],
        "s": "BTC-261030-82000-P", "u": 928312981, "b": "1725.000", "B": "0.21",
        "a": "1740.000", "A": "0.45"}}, separators=(",", ":")).encode("utf8")
    def complete(data, skip):
        state = continuous_frame(False, skip)
        frame = ABNF(fin=1, opcode=ABNF.OPCODE_TEXT, data=data)
        state.add(frame)
        opcode, frame = state.extract(frame)
        return json.loads(frame.data)
    result = {"offline": True, "source": "Saved localhost public market cache, wire-shaped synthetic payload",
              "contract_count": len(events), "mark_frame_bytes": len(mark), "quote_frame_bytes": len(quote),
              "mark_validate_only": measure(lambda: validate_utf8(mark)),
              "mark_decode_json": measure(lambda: json.loads(mark)),
              "mark_complete_default": measure(lambda: complete(mark, False)),
              "mark_complete_skip": measure(lambda: complete(mark, True)),
              "quote_validate_only": measure(lambda: validate_utf8(quote), count=300),
              "quote_complete_default": measure(lambda: complete(quote, False), count=300),
              "quote_complete_skip": measure(lambda: complete(quote, True), count=300)}
    try:
        complete(b'{"data":"\xff"}', True)
        result["invalid_utf8_still_rejected"] = False
    except UnicodeDecodeError:
        result["invalid_utf8_still_rejected"] = True
    result["valid_utf8_json_parsed_identically"] = complete(mark, False) == complete(mark, True)
    destination = root / "ws-utf8-benchmark-20261017.json"
    destination.write_text(json.dumps(result, indent=2), encoding="utf8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()

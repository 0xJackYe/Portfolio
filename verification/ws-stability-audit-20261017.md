# WebSocket transport audit (read-only)

Audit window: 2026-10-17, approximately 06:22–06:25 Beijing time. The service was not restarted and no additional exchange sockets were opened. The only live requests were GETs of the existing localhost market cache. Application files were not modified by this audit.

## Observed live state

`ws-audit-ping-samples-20261017.json` records six samples, 06:22:11–06:22:54, separated by approximately eight seconds. All six had 700 subscribed and 700 verified option books; all four book connection generations remained unchanged and their PONG serials advanced by four or five. The October 30 chain had 102 verified contracts throughout. The underlying index receipt age was 0.48–1.49 seconds. Between samples, 112, 135, 116, 167 and 145 contracts changed their bid/ask values or quantities.

A further localhost read at approximately 06:23:01 showed the four book connections continuously open for approximately 32–75 minutes. Ticker and index connections had been open for approximately 154 minutes. The market connection remained affected by `MarketStreamSilent` and repeated physical generations. Thus the earlier 30-second book heartbeat failure was not reproduced during this quieter market sample, while the separate mark stream failure remained observable.

The bid-price receipt timestamp minus its exchange event timestamp, adjusted by the saved exchange clock offset, was median 157–168 ms across the four book groups, P90 190–234 ms and maximum 634 ms. These particular measurements do not show a seconds-long reader backlog. An old *event age* for an unchanged book is not evidence of backlog; receipt minus exchange event time is the relevant comparison.

## Library/protocol review

Installed library: websocket-client 1.8.0, Python 3.9. There is no wsaccel module installed.

- `WebSocket.recv_data(control_frame=True)` returns PONG frames and automatically replies to server PINGs. The application compares its own distinct nonce and current physical generation. No PONG API mismatch was found.
- `frame_buffer.recv_strict()` retains partial payload bytes in its buffer when the underlying socket times out. Its header/length state is reset only once a complete frame has been obtained. No timeout-related frame discard was found.
- An application PING approximately every ten seconds, plus one initial LIST request, is far below the documented ten incoming messages per second limit. Four groups of 175 book streams are below the documented 200 streams per connection limit.
- The official mark stream name and combined-stream path match the code. Official documentation still describes the all-option underlying mark feed as a 1000 ms stream. A healthy PONG alone does not establish that this periodic market feed is producing business data, so retaining the separate market-data silence detection is appropriate.

Official documentation read during this audit:

- https://developers.binance.com/en/docs/products/derivatives-trading-options/websocket-market-streams/Connect
- https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-options/api/ws-streams/market

## Offline UTF-8 benchmark and recommendation

`benchmark_ws_utf8_20261017.py` creates a wire-shaped synthetic mark frame from the saved public cache; it does not reproduce a captured raw exchange frame. It contains 700 contracts and 190,551 bytes. Results are saved in `ws-utf8-benchmark-20261017.json`:

| Operation | Median |
| --- | ---: |
| Pure Python frame UTF-8 validation | 39.384 ms |
| JSON decoding of the byte payload | 1.308 ms |
| Library complete-message extraction plus JSON, default | 41.000 ms |
| Same operation, skip_utf8_validation=True | 1.376 ms |
| 195-byte book message, default | 0.048 ms |
| 195-byte book message, skip validation | 0.006 ms |

Valid JSON decoded identically in both paths. An invalid UTF-8 byte inside a JSON string remained rejected by `json.loads(bytes)` with UnicodeDecodeError even when frame validation was skipped. Passing `skip_utf8_validation=True` to `create_connection` is a small, justified performance improvement: it removes a duplicate Python byte loop while preserving subsequent JSON decoding. It does not disable TLS validation or WebSocket opcode/RSV checks.

This approximately 40 ms cost per one-second mark array does **not**, by itself, prove the cause of a twenty-second heartbeat failure. It is a measurable optimization, not a demonstrated complete root-cause fix. The next useful live diagnostics are per-connection business frame counts, latest wire event lag, callback maximum duration and the final disconnect reason. These distinguish a slow callback/reader from a remotely silent or partially delivered stream. Extending freshness limits would not resolve either condition.

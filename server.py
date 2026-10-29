#!/usr/bin/env python3
"""BTC Options: a local, read-only Binance options dashboard.

    python server.py                 # opens http://127.0.0.1:8765/
    python server.py --port 8766 --no-browser
"""

import argparse
import sys
import threading
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from market import Market

WEB_DIR = (Path(__file__).resolve().parent / "web").resolve()
NAME = "BTCOptions"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]"}
SSE_KEEPALIVE_SECONDS = 15
SSE_MIN_INTERVAL = 0.25  # coalesce bursts of updates into one frame
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".woff2": "font/woff2",
}
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                               "base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
}


class Handler(BaseHTTPRequestHandler):
    server_version = NAME + "/2.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        # Reject other host names so a web page cannot reach this server through DNS rebinding.
        host = (self.headers.get("Host") or "").lower()
        if host.rpartition(":")[0] not in LOCAL_HOSTS and host not in LOCAL_HOSTS:
            self._send(403, b"Forbidden", "text/plain; charset=utf-8")
        elif self.path.split("?")[0] == "/api/market":
            self._send(200, self.server.market.frame()[1], "application/json; charset=utf-8")
        elif self.path.split("?")[0] == "/api/events":
            self._events()
        else:
            self._static(urllib.parse.unquote(urllib.parse.urlsplit(self.path).path))

    def _static(self, path):
        try:
            file = (WEB_DIR / ("index.html" if path == "/" else path.lstrip("/"))).resolve()
            found = WEB_DIR in file.parents and file.suffix in CONTENT_TYPES and file.is_file()
            body = file.read_bytes() if found else b""
        except (OSError, ValueError):  # e.g. a null byte or an over-long name
            found = False
        if not found:
            self._send(404, b"Not found", "text/plain; charset=utf-8")
            return
        cache = "max-age=604800" if file.suffix == ".woff2" else "no-cache"
        self._send(200, body, CONTENT_TYPES[file.suffix], cache)

    def _send(self, status, body, content_type, cache="no-store"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        for name, value in SECURITY_HEADERS.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _events(self):
        """Server-sent events: one snapshot per market change, shared by every tab."""
        market = self.server.market
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.close_connection = True
        self.connection.settimeout(30)
        revision = None
        try:
            self.wfile.write(b"retry: 2000\n\n")
            while not market.stopped:
                current = market.wait(revision, SSE_KEEPALIVE_SECONDS)
                if current == revision:
                    self.wfile.write(b": keepalive\n\n")
                else:
                    revision, body = market.frame()
                    self.wfile.write(b"data: " + body + b"\n\n")
                self.wfile.flush()
                if market.sleep(SSE_MIN_INTERVAL):
                    break
        except OSError:
            pass  # the tab was closed


class Server(ThreadingHTTPServer):
    daemon_threads = True
    # On Windows SO_REUSEADDR lets a second copy bind the same port; never allow that.
    allow_reuse_address = sys.platform != "win32"

    def __init__(self, address, market):
        self.market = market
        super().__init__(address, Handler)


def already_running(port):
    """True if this dashboard is already serving on the port."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open("http://127.0.0.1:%d/api/market" % port, timeout=1.5) as response:
            return response.headers.get("Server", "").startswith(NAME)
    except (OSError, ValueError):
        return False


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local BTC options dashboard (Binance public market data, read-only).")
    parser.add_argument("--port", type=int, default=8765, help="local port (default 8765)")
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser tab")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    url = "http://127.0.0.1:%d/" % args.port
    if already_running(args.port):
        print("BTC Options is already running: " + url)
        if not args.no_browser:
            webbrowser.open(url)
        return 0
    market = Market()
    try:
        server = Server(("127.0.0.1", args.port), market)
    except OSError:
        parser.error("port %d is in use; try --port %d" % (args.port, args.port + 1))
    market.start()
    print("BTC Options  " + url)
    print("Binance public market data, read-only. Press Ctrl+C to stop.")
    if not market.streaming:
        print("Live stream unavailable, refreshing every 15 s. Install it with:\n  \"%s\" -m pip install websocket-client"
              % sys.executable)
    if not args.no_browser:
        threading.Timer(0.5, webbrowser.open, (url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        market.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())

import contextlib
import http.client
import io
import json
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import server  # noqa: E402
from fake_binance import FakeBinance  # noqa: E402
from market import Market  # noqa: E402


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.binance = FakeBinance()
        self.market = Market(fetch=self.binance.fetch, connect=None)
        self.market.refresh_catalog()
        self.server = server.Server(("127.0.0.1", 0), self.market)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.market.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def get(self, path, host=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.putrequest("GET", path, skip_host=True)
        connection.putheader("Host", host or "127.0.0.1:%d" % self.port)
        connection.endheaders()
        response = connection.getresponse()
        body = response.read()
        connection.close()
        return response, body

    def test_market_snapshot(self):
        response, body = self.get("/api/market")
        self.assertEqual(200, response.status)
        self.assertEqual("application/json; charset=utf-8", response.getheader("Content-Type"))
        self.assertEqual("no-store", response.getheader("Cache-Control"))
        self.assertIn("default-src 'self'", response.getheader("Content-Security-Policy"))
        self.assertTrue(response.getheader("Server").startswith(server.NAME))
        snapshot = json.loads(body)
        self.assertEqual(20, len(snapshot["contracts"]))
        self.assertEqual(80000.0, snapshot["index"])

    def test_static_files(self):
        for path, content_type in (("/", "text/html; charset=utf-8"), ("/app.js", "text/javascript; charset=utf-8"),
                                   ("/payoff.js", "text/javascript; charset=utf-8"), ("/styles.css", "text/css; charset=utf-8"),
                                   ("/icon.svg", "image/svg+xml"), ("/fonts/inter.woff2", "font/woff2")):
            with self.subTest(path=path):
                response, body = self.get(path)
                self.assertEqual(200, response.status)
                self.assertEqual(content_type, response.getheader("Content-Type"))
                self.assertGreater(len(body), 100)
        self.assertEqual("max-age=604800", self.get("/fonts/inter.woff2")[0].getheader("Cache-Control"))
        self.assertIn(b"<title>BTC Options</title>", self.get("/")[1])

    def test_nothing_outside_the_web_folder(self):
        for path in ("/../market.py", "/%2e%2e/server.py", "/fonts/../../server.py", "/fonts/OFL.txt",
                     "/missing.js", "/%00.js", "/..%5cserver.py", "/" + "a" * 5000 + ".js"):
            with self.subTest(path=path[:40]):
                self.assertEqual(404, self.get(path)[0].status)

    def test_other_host_names_are_refused(self):
        self.assertEqual(403, self.get("/api/market", host="evil.example:%d" % self.port)[0].status)
        self.assertEqual(403, self.get("/", host="127.0.0.1.evil.example")[0].status)
        self.assertEqual(200, self.get("/api/market", host="localhost:%d" % self.port)[0].status)
        self.assertEqual(200, self.get("/api/market", host="localhost")[0].status)

    def test_events_stream_each_change(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request("GET", "/api/events")
        response = connection.getresponse()
        self.assertEqual("text/event-stream; charset=utf-8", response.getheader("Content-Type"))

        def next_snapshot():
            while True:
                line = response.fp.readline().decode()
                if line.startswith("data: "):
                    return json.loads(line[6:])

        self.assertEqual("retry: 2000\n", response.fp.readline().decode())
        first = next_snapshot()
        symbol = self.binance.put()
        self.market.apply_stream(self.binance.frame(self.binance.event(symbol, bo="4242", i="81234.5")))
        second = next_snapshot()
        self.assertEqual(81234.5, second["index"])
        self.assertEqual(4242.0, next(c for c in second["contracts"] if c["symbol"] == symbol)["bid"])
        self.assertNotEqual(first["index"], second["index"])
        connection.close()

    def test_only_get_is_supported(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request("POST", "/api/market", body=b"{}")
        self.assertEqual(501, connection.getresponse().status)
        connection.close()

    def test_a_second_launch_reuses_the_running_dashboard(self):
        self.assertTrue(server.already_running(self.port))
        output = io.StringIO()
        with mock.patch.object(server, "Market") as market, contextlib.redirect_stdout(output):
            self.assertEqual(0, server.main(["--port", str(self.port), "--no-browser"]))
        market.assert_not_called()
        self.assertIn("already running", output.getvalue())


class MainTest(unittest.TestCase):
    def test_nothing_running_on_a_closed_port(self):
        probe = server.Server(("127.0.0.1", 0), Market(fetch=FakeBinance().fetch, connect=None))
        port = probe.server_address[1]
        probe.server_close()
        self.assertFalse(server.already_running(port))

    def test_invalid_port(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            server.main(["--port", "70000"])


if __name__ == "__main__":
    unittest.main()

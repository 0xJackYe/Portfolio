"""Offline unit tests: never start applications, request tasks, or use a network."""
import contextlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock
import urllib.error

import start_workspace as startup


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        for name in ("chrome.exe", "Skyline.exe", "launch_btc_terminal.py"):
            (self.root / name).touch()
        self.config = startup.Config(self.root / "chrome.exe", self.root / "Skyline.exe",
                                     "\\WorkStartup\\Skyline", self.root,
                                     network_wait_seconds=1, poll_interval_seconds=0.25)
        self.state = self.root / "state"
        self.log = mock.Mock()
        self.terminal = mock.Mock()
        self.terminal.windows_logon_key.return_value = "boot/logon/session"
        self.terminal.startup_lock.side_effect = lambda **kwargs: contextlib.nullcontext()
        self.terminal.open_for_logon.side_effect = self.fake_terminal_open
        self.browser = mock.Mock(return_value=True)

    def tearDown(self):
        self.temporary.cleanup()

    def fake_terminal_open(self, **kwargs):
        self.assertTrue(kwargs["autostart"])
        self.assertEqual(kwargs["key_provider"](), "boot/logon/session")
        return kwargs["opener"]("http://127.0.0.1:8766/")

    def run_fake(self, **kwargs):
        clock_value = [0.0]
        def sleep(delay):
            clock_value[0] += delay
        defaults = dict(running=mock.Mock(return_value=True), runner=mock.Mock(),
                        probe=mock.Mock(return_value=(True, "403")), browser=self.browser,
                        clock=lambda: clock_value[0], sleep=sleep)
        defaults.update(kwargs)
        return startup.run_workspace(self.config, self.terminal, self.state, self.log, **defaults)

    def config_file(self, **updates):
        data = {"chrome_path": str(self.config.chrome_path),
                "vpn_exe_path": str(self.config.vpn_exe_path),
                "vpn_task_name": self.config.vpn_task_name,
                "project_root": str(self.root)}
        data.update(updates)
        path = self.root / "config.json"
        path.write_text(json.dumps(data), encoding="utf-8-sig")
        return path

    def test_config_defaults_and_absolute_files(self):
        config = startup.load_config(self.config_file())
        self.assertEqual(config.terminal_port, 8766)
        self.assertEqual(config.network_wait_seconds, 60)
        self.assertEqual(config.vpn_core_process_name, "skyline-core.exe")
        self.assertEqual(config.chrome_path, self.root / "chrome.exe")

    def test_invalid_config_rejected_without_any_process_or_network(self):
        cases = [{"chrome_path": "relative.exe"}, {"terminal_port": True},
                 {"network_wait_seconds": float("nan")}, {"poll_interval_seconds": 0},
                 {"vpn_core_process_name": "folder\\core.exe"}, {"vpn_task_name": ""}]
        for update in cases:
            with self.subTest(update=update), self.assertRaises(ValueError):
                startup.load_config(self.config_file(**update))

    def test_process_query_matches_full_case_insensitive_image_name(self):
        runner = mock.Mock(return_value=subprocess.CompletedProcess([], 0, '"Skyline.EXE","42"\n', ""))
        self.assertTrue(startup.process_running("skyline.exe", runner))
        runner.return_value.stdout = "信息: 没有运行的任务匹配指定标准。"
        self.assertFalse(startup.process_running("skyline.exe", runner))
        self.assertEqual(runner.call_args.args[0],
                         ["tasklist.exe", "/FI", "IMAGENAME eq skyline.exe", "/FO", "CSV", "/NH"])

    def test_already_running_vpn_never_requests_task(self):
        runner = mock.Mock()
        self.assertTrue(startup.ensure_vpn(self.config, self.log, running=lambda name: True, runner=runner))
        runner.assert_not_called()

    def test_absent_vpn_requests_exact_task_without_connection_arguments(self):
        runner = mock.Mock(return_value=subprocess.CompletedProcess([], 0, "OK", ""))
        self.assertTrue(startup.ensure_vpn(self.config, self.log, running=lambda name: False, runner=runner))
        self.assertEqual(runner.call_args.args[0],
                         ["schtasks.exe", "/Run", "/TN", self.config.vpn_task_name])
        self.assertNotIn("shell", runner.call_args.kwargs)

    def test_https_403_is_reachable_but_is_not_a_login_check(self):
        error = urllib.error.HTTPError(startup.CHATGPT_URL, 403, "Forbidden", {}, None)
        opener = mock.Mock(side_effect=error)
        self.assertEqual(startup.https_reachable(1.5, opener), (True, "403"))
        request = opener.call_args.args[0]
        self.assertEqual(request.full_url, startup.CHATGPT_URL)
        self.assertEqual(request.get_method(), "HEAD")

    def test_network_timeout_still_opens_chatgpt_and_terminal(self):
        runner = mock.Mock(return_value=subprocess.CompletedProcess([], 1, "", "denied"))
        probe = mock.Mock()
        self.assertEqual(self.run_fake(running=lambda name: False, runner=runner, probe=probe), 0)
        self.assertEqual([call.args[0] for call in self.browser.call_args_list],
                         ["http://127.0.0.1:8766/#options", startup.CHATGPT_URL])
        probe.assert_not_called()
        self.assertTrue(any("Timed out" in call.args[0] for call in self.log.call_args_list))

    def test_chrome_uses_explicit_executable_and_no_elevation_or_shell(self):
        popen = mock.Mock()
        self.assertTrue(startup.open_chrome(self.config, startup.CHATGPT_URL, popen))
        self.assertEqual(popen.call_args.args[0],
                         [str(self.config.chrome_path), "--new-tab", startup.CHATGPT_URL])
        self.assertNotIn("shell", popen.call_args.kwargs)
        self.assertNotIn("runas", str(popen.call_args))

    def test_locks_are_distinct_and_terminal_readiness_precedes_page(self):
        self.assertEqual(self.run_fake(), 0)
        locks = self.terminal.startup_lock.call_args_list
        self.assertNotEqual(locks[0].kwargs["root"], locks[1].kwargs["root"])
        self.assertEqual(locks[1].kwargs["root"], self.config.project_root)
        names = [call[0] for call in self.terminal.mock_calls]
        self.assertLess(names.index("ensure_server"), names.index("open_for_logon"))
        self.terminal.ensure_server.assert_called_once_with(
            port=8766, root=self.config.project_root, timeout=45)

    def test_same_login_deduplicates_chatgpt_but_keeps_terminal_own_marker(self):
        self.run_fake()
        self.browser.reset_mock()
        probe = mock.Mock()
        self.run_fake(probe=probe)
        probe.assert_not_called()
        self.browser.assert_called_once_with("http://127.0.0.1:8766/#options")
        self.assertEqual(self.terminal.ensure_server.call_count, 2)
        self.assertEqual(self.terminal.open_for_logon.call_count, 2)

    def test_failed_chatgpt_open_does_not_prevent_terminal_or_suppress_retry(self):
        def fail_chatgpt(url):
            if url == startup.CHATGPT_URL:
                raise OSError("cannot start chrome")
            return True
        self.browser.side_effect = fail_chatgpt
        self.assertEqual(self.run_fake(), 1)
        self.assertFalse(startup.marker_path(self.config, self.state).exists())
        self.assertEqual(self.browser.call_args_list[0].args[0], "http://127.0.0.1:8766/#options")
        self.assertEqual(sum(call.args[0] == startup.CHATGPT_URL for call in self.browser.call_args_list), 3)
        self.browser.side_effect = None
        self.run_fake()
        self.assertTrue(startup.marker_path(self.config, self.state).exists())

    def test_terminal_failure_does_not_open_its_page_or_reopen_chatgpt(self):
        self.terminal.ensure_server.side_effect = RuntimeError("port occupied")
        self.assertEqual(self.run_fake(), 1)
        self.browser.assert_called_once_with(startup.CHATGPT_URL)
        self.terminal.open_for_logon.assert_not_called()
        self.browser.reset_mock()
        self.run_fake()
        self.browser.assert_not_called()

    def test_reachable_https_without_core_is_not_accepted(self):
        probe = mock.Mock(return_value=(True, "200"))
        self.run_fake(running=lambda name: name == "Skyline.exe", probe=probe)
        probe.assert_not_called()

    def test_process_query_consuming_deadline_does_not_start_late_https_probe(self):
        clock_value = [0.0]
        def running(name):
            clock_value[0] += 2.0
            return True
        probe = mock.Mock()
        value = startup.wait_for_network(self.config, self.log, running=running, probe=probe,
                                         clock=lambda: clock_value[0], sleep=mock.Mock())
        self.assertFalse(value)
        probe.assert_not_called()

    def test_check_only_queries_and_printable_evidence_without_creating_state(self):
        runner = mock.Mock(return_value=subprocess.CompletedProcess([], 0, "task exists", ""))
        self.terminal.probe_server.return_value = "ready"
        value = startup.check_configuration(
            self.config, self.terminal, running=lambda name: True, runner=runner,
            probe=lambda timeout: (True, "403"), elevated=lambda: False)
        self.assertTrue(value["vpn_connection_ready_approximate"])
        self.assertFalse(value["chatgpt_login_verified"])
        self.assertTrue(value["terminal_ready"])
        self.assertEqual(runner.call_args.args[0],
                         ["schtasks.exe", "/Query", "/TN", self.config.vpn_task_name, "/FO", "CSV", "/NH"])
        self.terminal.ensure_server.assert_not_called()
        self.browser.assert_not_called()
        self.assertFalse(self.state.exists())
        json.dumps(value)

    def test_check_main_does_not_make_logger_or_run_workspace(self):
        path = self.config_file()
        with mock.patch.object(startup, "import_terminal", return_value=self.terminal), \
             mock.patch.object(startup, "check_configuration", return_value={"config_valid": True}), \
             mock.patch.object(startup, "make_logger") as logger, \
             mock.patch.object(startup, "run_workspace") as run, mock.patch("builtins.print"):
            self.assertEqual(startup.main(["--config", str(path), "--check"]), 0)
        logger.assert_not_called()
        run.assert_not_called()

    def test_local_service_and_options_page_are_ready_before_vpn_or_network_wait(self):
        events = []
        self.terminal.ensure_server.side_effect = lambda **kwargs: events.append("server-ready")
        def browser(url):
            events.append(url)
            return True
        def running(name):
            events.append("vpn-check")
            return True
        def probe(timeout):
            events.append("network-check")
            return True, "403"
        self.assertEqual(self.run_fake(browser=browser, running=running, probe=probe), 0)
        options_index = events.index("http://127.0.0.1:8766/#options")
        self.assertLess(events.index("server-ready"), options_index)
        self.assertLess(options_index, events.index("vpn-check"))
        self.assertLess(options_index, events.index("network-check"))
        self.assertLess(events.index("network-check"), events.index(startup.CHATGPT_URL))

    def test_slow_or_absent_network_never_delays_the_local_page(self):
        moments = []
        clock_value = [0.0]
        def browser(url):
            moments.append((url, clock_value[0]))
            return True
        def sleep(delay):
            clock_value[0] += delay
        self.assertEqual(self.run_fake(browser=browser, running=lambda name: False,
                                       runner=mock.Mock(return_value=subprocess.CompletedProcess([], 1)),
                                       clock=lambda: clock_value[0], sleep=sleep), 0)
        self.assertEqual(moments, [("http://127.0.0.1:8766/#options", 0.0),
                                   (startup.CHATGPT_URL, self.config.network_wait_seconds)])

    def test_transient_chrome_spawn_failure_retries_with_bounded_backoff(self):
        self.browser.side_effect = [OSError("profile starting"), False, True, True]
        sleeps = []
        self.assertEqual(self.run_fake(sleep=sleeps.append), 0)
        self.assertEqual(sleeps, [1, 2])
        self.assertEqual([call.args[0] for call in self.browser.call_args_list],
                         ["http://127.0.0.1:8766/#options"] * 3 + [startup.CHATGPT_URL])
        self.assertTrue(startup.marker_path(self.config, self.state).exists())

    def test_failed_local_chrome_open_does_not_block_chatgpt_or_claim_success(self):
        self.browser.side_effect = lambda url: url == startup.CHATGPT_URL
        self.assertEqual(self.run_fake(), 1)
        status = json.loads((self.state / "last-run.json").read_text(encoding="utf-8"))
        self.assertTrue(status["terminal_ready"])
        self.assertFalse(status["terminal_open_requested"])
        self.assertFalse(status["terminal_already_opened"])
        self.assertTrue(status["chatgpt_open_requested"])
        self.assertFalse(status["success"])
        self.assertIn("three attempts", status["terminal_error"])
        self.assertTrue(startup.marker_path(self.config, self.state).exists())

    def test_network_probe_exception_still_opens_chatgpt_after_local_page(self):
        self.assertEqual(self.run_fake(probe=mock.Mock(side_effect=OSError("network stack starting"))), 0)
        self.assertEqual([call.args[0] for call in self.browser.call_args_list],
                         ["http://127.0.0.1:8766/#options", startup.CHATGPT_URL])
        status = json.loads((self.state / "last-run.json").read_text(encoding="utf-8"))
        self.assertFalse(status["network_reachable"])
        self.assertEqual(status["network_error"], "network stack starting")
        self.assertTrue(status["success"])

    def test_local_failure_is_recorded_while_chatgpt_still_opens(self):
        self.terminal.ensure_server.side_effect = RuntimeError("port occupied")
        self.assertEqual(self.run_fake(), 1)
        status = json.loads((self.state / "last-run.json").read_text(encoding="utf-8"))
        self.assertEqual(status["phase"], "complete")
        self.assertEqual(status["exit_code"], 1)
        self.assertFalse(status["terminal_ready"])
        self.assertFalse(status["terminal_open_requested"])
        self.assertEqual(status["terminal_error"], "port occupied")
        self.assertTrue(status["chatgpt_open_requested"])
        self.assertFalse(status["success"])
        self.assertIn("started_utc", status)
        self.assertIn("finished_utc", status)

    def test_status_is_written_before_network_wait_and_records_success(self):
        def probe(timeout):
            current = json.loads((self.state / "last-run.json").read_text(encoding="utf-8"))
            self.assertEqual(current["phase"], "network")
            self.assertTrue(current["terminal_ready"])
            self.assertTrue(current["terminal_open_requested"])
            self.assertFalse(current["chatgpt_open_requested"])
            return True, "403"
        self.assertEqual(self.run_fake(probe=probe), 0)
        status = json.loads((self.state / "last-run.json").read_text(encoding="utf-8"))
        self.assertEqual(status["phase"], "complete")
        self.assertEqual(status["exit_code"], 0)
        self.assertEqual(status["terminal_url"], "http://127.0.0.1:8766/#options")
        self.assertTrue(status["success"])

    def test_real_terminal_marker_deduplicates_both_pages_on_same_login(self):
        real_terminal = startup.import_terminal(Path(__file__).resolve().parents[1])
        self.terminal.open_for_logon.side_effect = real_terminal.open_for_logon
        self.assertEqual(self.run_fake(), 0)
        self.assertEqual(self.browser.call_count, 2)
        self.browser.reset_mock()
        self.assertEqual(self.run_fake(), 0)
        self.browser.assert_not_called()
        self.assertEqual(self.terminal.ensure_server.call_count, 2, "a repeat still repairs the service")
        status = json.loads((self.state / "last-run.json").read_text(encoding="utf-8"))
        self.assertTrue(status["terminal_already_opened"])
        self.assertTrue(status["chatgpt_already_opened"])
        self.assertFalse(status["terminal_open_requested"])
        self.assertFalse(status["chatgpt_open_requested"])

    def test_failed_terminal_spawn_has_no_marker_and_later_invocation_repairs_it(self):
        real_terminal = startup.import_terminal(Path(__file__).resolve().parents[1])
        self.terminal.open_for_logon.side_effect = real_terminal.open_for_logon
        self.browser.side_effect = lambda url: url == startup.CHATGPT_URL
        self.assertEqual(self.run_fake(), 1)
        terminal_marker = self.root / "terminal" / "logs" / "last-startup-logon-8766.json"
        self.assertFalse(terminal_marker.exists())
        self.browser.reset_mock(side_effect=True)
        self.assertEqual(self.run_fake(), 0)
        self.browser.assert_called_once_with("http://127.0.0.1:8766/#options")
        self.assertTrue(terminal_marker.exists())

    def test_terminal_route_mapping_is_exact_and_uses_configured_port(self):
        self.config = startup.Config(self.config.chrome_path, self.config.vpn_exe_path,
                                     self.config.vpn_task_name, self.root, terminal_port=9191)
        def open_terminal(**kwargs):
            kwargs["opener"]("http://127.0.0.1:9191/")
            kwargs["opener"]("http://127.0.0.1:9191/other")
            return True
        self.terminal.open_for_logon.side_effect = open_terminal
        self.assertEqual(self.run_fake(), 0)
        self.assertEqual([call.args[0] for call in self.browser.call_args_list],
                         ["http://127.0.0.1:9191/#options", "http://127.0.0.1:9191/other", startup.CHATGPT_URL])

    def test_configuration_failure_is_logged_before_runtime_loading(self):
        with mock.patch.object(startup, "state_directory", return_value=self.state), \
             mock.patch.object(startup, "make_logger", return_value=self.log), \
             mock.patch.object(startup, "load_config", side_effect=ValueError("bad config")), \
             mock.patch.object(startup, "import_terminal") as terminal, mock.patch("sys.stderr", None):
            self.assertEqual(startup.main([]), 1)
        self.assertIn("validating configuration", self.log.call_args_list[0].args[0])
        terminal.assert_not_called()
        status = json.loads((self.state / "last-run.json").read_text(encoding="utf-8"))
        self.assertEqual(status["phase"], "failed")
        self.assertEqual(status["error"], "bad config")

    def test_elevated_launcher_never_starts_apps_or_network(self):
        path = self.config_file()
        with mock.patch.object(startup, "state_directory", return_value=self.state), \
             mock.patch.object(startup, "make_logger", return_value=self.log), \
             mock.patch.object(startup, "import_terminal", return_value=self.terminal), \
             mock.patch.object(startup, "is_elevated", return_value=True), \
             mock.patch.object(startup, "run_workspace") as run, mock.patch("sys.stderr", None):
            self.assertEqual(startup.main(["--config", str(path)]), 1)
        run.assert_not_called()
        self.assertIn("ordinary login user", self.log.call_args_list[-1].args[0])

    def test_terminal_import_failure_is_logged_and_written_to_status(self):
        path = self.config_file()
        for error in (ImportError("missing launcher dependency"), SyntaxError("invalid launcher code")):
            with self.subTest(error=type(error).__name__), \
                 mock.patch.object(startup, "state_directory", return_value=self.state), \
                 mock.patch.object(startup, "make_logger", return_value=self.log), \
                 mock.patch.object(startup, "import_terminal", side_effect=error), \
                 mock.patch.object(startup, "run_workspace") as run, mock.patch("sys.stderr", None):
                self.assertEqual(startup.main(["--config", str(path)]), 1)
                run.assert_not_called()
                status = json.loads((self.state / "last-run.json").read_text(encoding="utf-8"))
                self.assertEqual(status["phase"], "failed")
                self.assertEqual(status["error"], str(error))

    def test_status_io_failure_never_prevents_browser_launch(self):
        with mock.patch.object(startup.os, "replace", side_effect=OSError("read-only state")):
            self.assertEqual(self.run_fake(), 0)
        self.assertEqual(self.browser.call_count, 2)
        self.assertTrue(any("Could not save workspace startup status" in call.args[0]
                            for call in self.log.call_args_list))


if __name__ == "__main__":
    unittest.main()

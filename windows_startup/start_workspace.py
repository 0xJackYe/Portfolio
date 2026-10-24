"""Current-user login startup. Install nothing; VPN elevation belongs to its task.

Configuration is read from config.json beside this file. This program never
supplies VPN connection arguments, credentials, or an elevation request to Chrome.
"""
import argparse
import csv
from dataclasses import dataclass
import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request


CHATGPT_URL = "https://chatgpt.com/"
HERE = Path(__file__).resolve().parent
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass(frozen=True)
class Config:
    chrome_path: Path
    vpn_exe_path: Path
    vpn_task_name: str
    project_root: Path
    terminal_port: int = 8766
    network_wait_seconds: float = 60.0
    terminal_wait_seconds: float = 45.0
    network_probe_timeout_seconds: float = 5.0
    poll_interval_seconds: float = 2.0
    vpn_core_process_name: str = "skyline-core.exe"


def load_config(path):
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("config.json must contain an object.")

    def absolute_path(name, directory=False):
        value = data.get(name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Missing absolute path: " + name)
        candidate = Path(value)
        if not candidate.is_absolute():
            raise ValueError(name + " must be an absolute path.")
        candidate = candidate.resolve()
        if not (candidate.is_dir() if directory else candidate.is_file()):
            raise ValueError(name + " does not exist.")
        if not directory and candidate.suffix.lower() != ".exe":
            raise ValueError(name + " must identify an .exe file.")
        return candidate

    def number(name, default, minimum, maximum):
        value = data.get(name, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(name + " must be numeric.")
        if not minimum <= value <= maximum:
            raise ValueError(name + " is outside its allowed range.")
        return float(value)

    chrome = absolute_path("chrome_path")
    vpn = absolute_path("vpn_exe_path")
    root = absolute_path("project_root", directory=True)
    if not (root / "launch_btc_terminal.py").is_file():
        raise ValueError("project_root is missing launch_btc_terminal.py.")
    task = data.get("vpn_task_name")
    if not isinstance(task, str) or not task.strip() or any(ord(c) < 32 for c in task):
        raise ValueError("vpn_task_name must be a nonempty Windows task name.")
    port = data.get("terminal_port", 8766)
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("terminal_port must be an integer from 1 to 65535.")
    core = data.get("vpn_core_process_name", "skyline-core.exe")
    if (not isinstance(core, str) or not core.lower().endswith(".exe")
            or any(c in core for c in "\\/\r\n\0") or core != core.strip()):
        raise ValueError("vpn_core_process_name must be an executable filename.")
    return Config(chrome, vpn, task, root, port,
                  number("network_wait_seconds", 60, 0, 600),
                  number("terminal_wait_seconds", 45, 1, 180),
                  number("network_probe_timeout_seconds", 5, 0.1, 30),
                  number("poll_interval_seconds", 2, 0.1, 30), core)


def state_directory(environ=None):
    value = (os.environ if environ is None else environ).get("LOCALAPPDATA")
    if not value or not Path(value).is_absolute():
        raise RuntimeError("LOCALAPPDATA is unavailable or is not absolute.")
    return Path(value) / "WorkStartup"


def make_logger(state):
    path = Path(state) / "logs" / "startup.log"

    def log(message):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Bound this small diagnostic log without introducing dependencies.
            if path.exists() and path.stat().st_size > 1024 * 1024:
                os.replace(str(path), str(path.with_suffix(".previous.log")))
            with path.open("a", encoding="utf-8") as output:
                output.write(dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
                             + " " + str(message).replace("\n", " ").replace("\r", " ") + "\n")
        except OSError:
            pass
    return log


def import_terminal(root):
    spec = importlib.util.spec_from_file_location("work_startup_terminal_launcher",
                                                str(Path(root) / "launch_btc_terminal.py"))
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load the terminal launcher.")
    module = importlib.util.module_from_spec(spec)
    previous_bytecode_setting = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous_bytecode_setting
    return module


def is_elevated():
    if os.name != "nt":
        return False
    import ctypes
    return bool(ctypes.windll.shell32.IsUserAnAdmin())


def process_running(image_name, runner=subprocess.run):
    result = runner(["tasklist.exe", "/FI", "IMAGENAME eq " + image_name, "/FO", "CSV", "/NH"],
                    capture_output=True, text=True, errors="replace", timeout=5,
                    creationflags=NO_WINDOW)
    if result.returncode:
        raise RuntimeError("Could not inspect running process: " + image_name)
    # No dependency on the language of tasklist's empty-result message.
    return any(row and row[0].casefold() == image_name.casefold()
               for row in csv.reader(result.stdout.splitlines()))


def ensure_vpn(config, log, running=process_running, runner=subprocess.run):
    try:
        if running(config.vpn_exe_path.name) or running(config.vpn_core_process_name):
            log("Skyline is already running; no duplicate task launch requested.")
            return True
        result = runner(["schtasks.exe", "/Run", "/TN", config.vpn_task_name],
                        capture_output=True, text=True, errors="replace", timeout=15,
                        creationflags=NO_WINDOW)
        if result.returncode:
            log("Skyline scheduled task request failed (exit %s)." % result.returncode)
            return False
        log("Requested the configured Skyline scheduled task; native autoconnect is responsible for connection.")
        return True
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        log("Skyline task could not be requested: " + str(exc))
        return False


def https_reachable(timeout, opener=urllib.request.urlopen):
    request = urllib.request.Request(CHATGPT_URL, method="HEAD",
                                     headers={"User-Agent": "WorkStartup/1.0"})
    try:
        with opener(request, timeout=timeout) as response:
            return True, str(response.getcode())
    except urllib.error.HTTPError as exc:
        # 403/429 and other origin HTTP responses prove reachability, not login.
        return True, str(exc.code)
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        return False, type(exc).__name__


def wait_for_network(config, log, running=process_running, probe=https_reachable,
                     clock=time.monotonic, sleep=time.sleep):
    deadline = clock() + config.network_wait_seconds
    while True:
        remaining = deadline - clock()
        if remaining <= 0:
            log("Timed out waiting for Skyline core and ChatGPT HTTPS; browser opening will still be attempted.")
            return False
        try:
            core_ready = running(config.vpn_core_process_name)
        except (OSError, RuntimeError, subprocess.TimeoutExpired):
            core_ready = False
        remaining = deadline - clock()
        if remaining <= 0:
            continue
        if core_ready:
            reachable, status = probe(min(config.network_probe_timeout_seconds, remaining))
            if reachable:
                log("Skyline core is present; ChatGPT HTTPS responded %s (connectivity only, not login verification)." % status)
                return True
        remaining = deadline - clock()
        if remaining > 0:
            sleep(min(config.poll_interval_seconds, remaining))


def open_chrome(config, url, popen=subprocess.Popen):
    # Popen inherits the ordinary login user's token; no runas / shell / task.
    popen([str(config.chrome_path), "--new-tab", url], cwd=str(config.project_root),
          stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
          creationflags=NO_WINDOW)
    return True


def check_configuration(config, terminal, running=process_running,
                        runner=subprocess.run, probe=https_reachable,
                        elevated=is_elevated):
    """Read-only diagnostic: no task Run, Chrome, log, or completion marker."""
    result = {"config_valid": True, "chrome_path": str(config.chrome_path),
              "vpn_exe_path": str(config.vpn_exe_path), "vpn_task_name": config.vpn_task_name,
              "project_root": str(config.project_root), "terminal_port": config.terminal_port,
              "current_process_elevated": elevated(), "chatgpt_login_verified": False}
    for field, image in (("vpn_gui_running", config.vpn_exe_path.name),
                         ("vpn_core_running", config.vpn_core_process_name)):
        try:
            result[field] = running(image)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            result[field] = None
            result[field + "_error"] = str(exc)
    try:
        query = runner(["schtasks.exe", "/Query", "/TN", config.vpn_task_name, "/FO", "CSV", "/NH"],
                       capture_output=True, text=True, errors="replace", timeout=15,
                       creationflags=NO_WINDOW)
        result["vpn_task_query"] = {"found": query.returncode == 0, "returncode": query.returncode}
    except (OSError, subprocess.TimeoutExpired) as exc:
        result["vpn_task_query"] = {"found": None, "error": str(exc)}
    try:
        result["terminal_status"] = terminal.probe_server(config.terminal_port, timeout=1.0)
    except (OSError, RuntimeError) as exc:
        result["terminal_status"] = "probe-error"
        result["terminal_error"] = str(exc)
    result["terminal_ready"] = result["terminal_status"] == "ready"
    reachable, status = probe(config.network_probe_timeout_seconds)
    result["chatgpt_https_reachable"] = reachable
    result["chatgpt_https_status"] = status
    result["vpn_connection_ready_approximate"] = bool(result["vpn_core_running"] and reachable)
    result["connection_evidence_note"] = (
        "Core presence plus HTTPS reachability is approximate evidence only; "
        "the VPN route and ChatGPT account login were not verified.")
    return result


def marker_path(config, state):
    identity = os.path.normcase(str(config.project_root)) + ":" + str(config.terminal_port)
    suffix = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    return Path(state) / ("workspace-logon-" + suffix + ".json")


def read_marker(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, UnicodeError):
        return {}


def save_marker(path, value, log):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value), encoding="utf-8")
        os.replace(str(temporary), str(path))
    except OSError as exc:
        log("Could not save ChatGPT login-open marker; a later launch may reopen it: " + str(exc))


def save_run_status(state, value, log):
    """Best-effort diagnostics; a failed status write never prevents startup."""
    try:
        path = Path(state) / "last-run.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".%s.tmp" % os.getpid())
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(str(temporary), str(path))
    except OSError as exc:
        log("Could not save workspace startup status: " + str(exc))


def run_workspace(config, terminal, state, log, running=process_running,
                  runner=subprocess.run, probe=https_reachable, browser=None,
                  clock=time.monotonic, sleep=time.sleep):
    browser = browser or (lambda url: open_chrome(config, url))

    def open_with_retry(url):
        # Login can briefly race Chrome/profile initialization. Retry only a
        # rejected or failed spawn, never an accepted request or page loading.
        for attempt in range(3):
            if attempt:
                sleep(attempt)
            try:
                if browser(url):
                    return True
                error = RuntimeError("Chrome did not accept the open request.")
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
                error = exc
            log("Chrome open attempt %s failed for %s: %s" % (attempt + 1, url, error))
        raise RuntimeError("Chrome open request failed after three attempts: " + str(error))

    terminal_root_url = "http://127.0.0.1:%s/" % config.terminal_port
    options_url = terminal_root_url + "#options"

    def open_options(url):
        # The generic terminal launcher keeps its own default route. Only its
        # exact expected local root is mapped to the requested options page.
        return open_with_retry(options_url if url == terminal_root_url else url)

    # Use a DISTINCT root to avoid reentering the terminal's nonrecursive mutex.
    workspace_lock_root = Path(state) / "workspace-launch-mutex"
    with terminal.startup_lock(root=workspace_lock_root, port=config.terminal_port, timeout_ms=1000):
        try:
            login = terminal.windows_logon_key()
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            login = None
            log("Login identity unavailable; no persistent ChatGPT deduplication: " + str(exc))
        marker = marker_path(config, state)
        previous = read_marker(marker)
        already_opened = (login is not None and previous.get("logon") == login
                          and previous.get("chatgpt_opened") is True)
        status = {"version": 1, "started_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                  "logon": login, "phase": "terminal", "success": False,
                  "terminal_url": options_url, "terminal_ready": False,
                  "terminal_open_requested": False, "terminal_already_opened": False,
                  "chatgpt_open_requested": False, "chatgpt_already_opened": already_opened,
                  "vpn_available_or_requested": None, "network_reachable": None}
        save_run_status(state, status, log)
        had_error = False
        # Even a repeat invocation repairs a stopped terminal; the existing
        # terminal marker independently decides whether its browser tab opens.
        # The local dashboard must not wait for VPN or Internet availability.
        try:
            with terminal.startup_lock(root=config.project_root, port=config.terminal_port):
                terminal.ensure_server(port=config.terminal_port, root=config.project_root,
                                       timeout=config.terminal_wait_seconds)
                status["terminal_ready"] = True
                kwargs = {"root": config.project_root, "port": config.terminal_port,
                          "autostart": True, "opener": open_options}
                if login is not None:
                    kwargs["key_provider"] = lambda: login
                opened = terminal.open_for_logon(**kwargs)
                status["terminal_open_requested"] = bool(opened)
                status["terminal_already_opened"] = not bool(opened)
                log("Terminal Chrome open requested." if opened else "Terminal already opened for this login; service reused.")
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            had_error = True
            status["terminal_error"] = str(exc)
            log("Terminal startup failed: " + str(exc))

        status["phase"] = "vpn"
        save_run_status(state, status, log)
        status["vpn_available_or_requested"] = ensure_vpn(config, log, running=running, runner=runner)
        if not already_opened:
            status["phase"] = "network"
            save_run_status(state, status, log)
            try:
                status["network_reachable"] = wait_for_network(
                    config, log, running=running, probe=probe, clock=clock, sleep=sleep)
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
                status["network_reachable"] = False
                status["network_error"] = str(exc)
                log("Network readiness check failed; Chrome opening will still be attempted: " + str(exc))
            status["phase"] = "chatgpt"
            save_run_status(state, status, log)
            try:
                open_with_retry(CHATGPT_URL)
                status["chatgpt_open_requested"] = True
                log("Requested ChatGPT in Chrome; page load and account login were not verified.")
                if login is not None:
                    save_marker(marker, {"logon": login, "chatgpt_opened": True}, log)
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
                had_error = True
                status["chatgpt_error"] = str(exc)
                log("Could not open ChatGPT in Chrome: " + str(exc))
        else:
            log("ChatGPT was already requested for this login; preserving its existing tab.")
        status.update(phase="complete", success=not had_error,
                      finished_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                      exit_code=1 if had_error else 0)
        save_run_status(state, status, log)
    return 1 if had_error else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Open the configured VPN, ChatGPT and local Bitcoin terminal at login.")
    parser.add_argument("--config", type=Path, default=HERE / "config.json")
    parser.add_argument("--check", action="store_true", help="Print read-only JSON diagnostics; do not start applications.")
    args = parser.parse_args(argv)
    if os.name != "nt":
        if sys.stderr is not None:
            print("This launcher is Windows-only.", file=sys.stderr)
        return 1
    log = lambda message: None
    state = None
    try:
        if not args.check:
            state = state_directory()
            log = make_logger(state)
            log("Workspace login startup requested; validating configuration.")
        config = load_config(args.config)
        terminal = import_terminal(config.project_root)
        if args.check:
            print(json.dumps(check_configuration(config, terminal), ensure_ascii=False, indent=2))
            return 0
        if is_elevated():
            raise RuntimeError("Run this launcher as the ordinary login user. Only the separate Skyline task may be elevated.")
        return run_workspace(config, terminal, state, log)
    except (OSError, ValueError, RuntimeError, ImportError, SyntaxError, subprocess.TimeoutExpired) as exc:
        log("Workspace startup ended: " + str(exc))
        if state is not None:
            save_run_status(state, {"version": 1, "phase": "failed", "success": False,
                                   "error": str(exc), "exit_code": 1,
                                   "finished_utc": dt.datetime.now(dt.timezone.utc).isoformat()}, log)
        if args.check:
            print(json.dumps({"config_valid": False, "error": str(exc)}, ensure_ascii=False, indent=2))
            return 1
        if sys.stderr is not None:
            print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

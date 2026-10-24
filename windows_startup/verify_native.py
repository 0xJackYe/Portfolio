"""Read-only startup verification, intended to run as the actual login user.

The sole write is the JSON report explicitly selected by --output. Registry
values and unrelated startup commands are hashed rather than disclosed.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.error
import urllib.request

try:
    import winreg
except ImportError:
    winreg = None


RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
APPROVED = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved"
TEAMS = (r"Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion"
         r"\AppModel\SystemAppData\MSTeams_8wekyb3d8bbwe\TeamsTfwStartupTask")
APPS = {"Steam", "Feishu", "Teams"}
WORK_RUN = "WorkStartup Workspace"
MAX_JSON = 32 * 1024 * 1024
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def sha256(value):
    return hashlib.sha256(value).hexdigest()


def stable_hash(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":")).encode("utf-8"))


def json_file(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError, UnicodeError):
        return None


def registry_value(path, name, view):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0,
                            winreg.KEY_READ | view) as key:
            try:
                value, kind = winreg.QueryValueEx(key, name)
                return {"key_exists": True, "exists": True,
                        "kind": kind, "value": value}
            except FileNotFoundError:
                return {"key_exists": True, "exists": False}
    except FileNotFoundError:
        return {"key_exists": False, "exists": False}
    except OSError as exc:
        return {"key_exists": None, "exists": None,
                "error": type(exc).__name__ + ": " + str(exc)}


def registry_targets(runtime):
    pythonw = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Python/Python39/pythonw.exe"
    command = ('"%s" "%s" --config "%s"' %
               (pythonw, runtime / "start_workspace.py", runtime / "config.json"))
    for view_name, view in (("Registry64", winreg.KEY_WOW64_64KEY),
                            ("Registry32", winreg.KEY_WOW64_32KEY)):
        for name in sorted(APPS):
            for path in (RUN, APPROVED + r"\Run", APPROVED + r"\Run32"):
                yield view_name, view, path, name, "absent" if path == RUN else "disabled", None
    yield "Registry64", winreg.KEY_WOW64_64KEY, RUN, WORK_RUN, "command", command
    yield "Registry64", winreg.KEY_WOW64_64KEY, APPROVED + r"\Run", WORK_RUN, "enabled", None
    yield "Registry64", winreg.KEY_WOW64_64KEY, APPROVED + r"\StartupFolder", "Work Startup.lnk", "enabled", None
    yield "Registry64", winreg.KEY_WOW64_64KEY, TEAMS, "State", "package", 1
    yield "Registry64", winreg.KEY_WOW64_64KEY, TEAMS, "UserEnabledStartupOnce", "package", 0


def check_registry(runtime):
    checks = []
    for view_name, view, path, name, expected, expected_value in registry_targets(runtime):
        read = registry_value(path, name, view)
        value = read.pop("value", None)
        result = {"view": view_name, "path": path, "name": name,
                  "expected": expected, **read}
        if isinstance(value, bytes):
            result["approval_state"] = value[0] if value else None
            result["value_sha256"] = sha256(value)
        elif expected == "package" and isinstance(value, int):
            result["state"] = value
        elif read.get("exists"):
            result["value_sha256"] = stable_hash(value)
        if read.get("error"):
            passed = False
        elif expected == "absent":
            passed = read["exists"] is False
        elif expected == "command":
            passed = read["exists"] is True and value == expected_value
        elif expected == "package":
            # The installer deliberately avoids inventing a missing Teams app.
            result["applicable"] = read["key_exists"] is True
            passed = not result["applicable"] or (read.get("kind") == winreg.REG_DWORD
                                                  and value == expected_value)
        else:
            passed = (read["exists"] is True and read.get("kind") == winreg.REG_BINARY
                      and isinstance(value, bytes) and len(value) == 12
                      and value[0] == (3 if expected == "disabled" else 2))
        result["passed"] = passed
        checks.append(result)
    return checks


def unrelated_fingerprints():
    """Capture only names/types/digests outside the explicitly managed values."""
    values = []
    paths = (RUN, APPROVED + r"\Run", APPROVED + r"\Run32", APPROVED + r"\StartupFolder")
    for view_name, view in (("Registry64", winreg.KEY_WOW64_64KEY),
                            ("Registry32", winreg.KEY_WOW64_32KEY)):
        for path in paths:
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0,
                                    winreg.KEY_READ | view) as key:
                    for index in range(winreg.QueryInfoKey(key)[1]):
                        name, value, kind = winreg.EnumValue(key, index)
                        if name.casefold() in {value.casefold() for value in APPS | {WORK_RUN, "Work Startup.lnk"}}:
                            continue
                        digest = sha256(value) if isinstance(value, bytes) else stable_hash(value)
                        values.append({"view": view_name, "path": path, "name": name,
                                       "kind": kind, "value_sha256": digest})
            except FileNotFoundError:
                continue
            except OSError as exc:
                values.append({"view": view_name, "path": path,
                               "error": type(exc).__name__ + ": " + str(exc)})
    values.sort(key=lambda entry: (entry["view"], entry["path"], entry.get("name", "")))
    return {"entries": values, "sha256": stable_hash(values)}


def task_and_process_status():
    # This reads task definitions/results and process identity only. It does not
    # invoke a task, expand a command line, or change any task setting.
    script = r"""
$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$tasks=@(foreach($name in @('WorkStartup - Workspace','WorkStartup - Skyline VPN')) {
  $task=Get-ScheduledTask -TaskName $name -TaskPath '\' -ErrorAction SilentlyContinue
  if($null -eq $task){[pscustomobject]@{name=$name;exists=$false};continue}
  $info=Get-ScheduledTaskInfo -TaskName $name -TaskPath '\'
  [pscustomobject]@{name=$name;exists=$true;enabled=$task.Settings.Enabled;
    state=[string]$task.State;run_level=[string]$task.Principal.RunLevel;
    user=$task.Principal.UserId;logon_type=[string]$task.Principal.LogonType;
    description=$task.Description;last_result=$info.LastTaskResult;
    last_run=$info.LastRunTime.ToUniversalTime().ToString('o');
    triggers=@($task.Triggers|Select-Object Enabled,Delay,UserId);
    xml=[string](Export-ScheduledTask -TaskName $name -TaskPath '\')}
})
$names=@('chrome.exe','python.exe','pythonw.exe','steam.exe','Feishu.exe',
  'Teams.exe','ms-teams.exe','skyline.exe','skyline-core.exe')
$processes=@(Get-CimInstance Win32_Process|Where-Object {$_.Name -in $names}|
  ForEach-Object {[pscustomobject]@{name=$_.Name;pid=$_.ProcessId}})
[pscustomobject]@{tasks=$tasks;processes=$processes}|ConvertTo-Json -Depth 8 -Compress
"""
    executable = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    try:
        completed = subprocess.run([str(executable), "-NoProfile", "-NonInteractive", "-Command", script],
                                   capture_output=True, timeout=30, creationflags=NO_WINDOW)
        if completed.returncode:
            return {"error": "PowerShell read-only query exited %d" % completed.returncode}
        data = json.loads(completed.stdout.decode("utf-8-sig"))
        for task in data.get("tasks", []):
            xml = task.pop("xml", None)
            if isinstance(xml, str):
                task["xml_sha256"] = normalized_xml_hash(xml)
        return data
    except (OSError, ValueError, UnicodeError, subprocess.TimeoutExpired) as exc:
        return {"error": type(exc).__name__ + ": " + str(exc)}


def normalized_xml_hash(text):
    return sha256(text.lstrip("\ufeff").replace("\r\n", "\n").strip().encode("utf-8"))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None


def local_api(port, endpoint):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open("http://127.0.0.1:%d%s" % (port, endpoint), timeout=8) as response:
            raw = response.read(MAX_JSON + 1)
            if len(raw) > MAX_JSON:
                return {"http_status": response.status, "error": "Response exceeds size limit"}
            data = json.loads(raw)
            result = {"http_status": response.status, "server": response.headers.get("Server"),
                      "json_object": isinstance(data, dict)}
            if not isinstance(data, dict):
                return result
            if endpoint == "/api/market":
                rows = data.get("options", [])
                rows = rows if isinstance(rows, list) else []
                realtime = data.get("realtime") or {}
                result.update(option_count=len(rows),
                              verified_book_count=sum(1 for row in rows if isinstance(row, dict)
                                                      and isinstance(row.get("quote_verification"), dict)
                                                      and row["quote_verification"].get("verified") is True),
                              btc_index_available=isinstance(data.get("btc_index_price"), (int, float, str))
                              and data.get("btc_index_price") not in (None, "", 0, "0"),
                              stale=data.get("stale"),
                              realtime_connected=realtime.get("connected") if isinstance(realtime, dict) else None)
            elif endpoint == "/api/terminal":
                result["settings_present"] = isinstance(data.get("settings"), dict)
            return result
    except urllib.error.HTTPError as exc:
        return {"http_status": exc.code, "error": "HTTP %d" % exc.code}
    except (OSError, ValueError, UnicodeError) as exc:
        return {"http_status": None, "error": type(exc).__name__ + ": " + str(exc)}


def startup_files():
    folder = Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs/Startup"
    files = []
    if folder.is_dir():
        for path in sorted(folder.iterdir(), key=lambda value: value.name.casefold()):
            if path.is_file():
                try:
                    files.append({"name": path.name, "bytes": path.stat().st_size,
                                  "sha256": sha256(path.read_bytes())})
                except OSError as exc:
                    files.append({"name": path.name, "error": type(exc).__name__})
    return {"path": str(folder), "exists": folder.is_dir(), "files": files,
            "workspace_shortcut_exists": (folder / "Work Startup.lnk").is_file()}


def collect(args):
    runtime = Path(os.environ.get("LOCALAPPDATA", "")) / "WorkStartup"
    config = json_file(runtime / "config.json")
    fields = ("chrome_path", "vpn_exe_path", "vpn_task_name", "project_root", "terminal_port")
    config_summary = {key: config.get(key) for key in fields} if config else None
    statuses = {}
    for filename in ("status.json", "startup-policy-status.json", "last-run.json"):
        value = json_file(runtime / filename)
        allowed = ("Success", "State", "DisabledRunNames", "WorkspaceTaskInstalled",
                   "WorkspaceTaskEnabled", "WorkspaceTaskError", "UpdatedUtc", "phase", "success",
                   "terminal_ready", "terminal_open_requested", "terminal_already_opened",
                   "chatgpt_open_requested", "chatgpt_already_opened", "vpn_available_or_requested",
                   "network_reachable", "exit_code", "started_utc", "finished_utc", "error")
        statuses[filename] = {key: value[key] for key in allowed if key in value} if value else None
    checks = check_registry(runtime)
    unrelated = unrelated_fingerprints()
    system = task_and_process_status()
    port = config.get("terminal_port", 8766) if config else 8766
    port = port if isinstance(port, int) and not isinstance(port, bool) and 1 <= port <= 65535 else 8766
    report = {"generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
              "read_only": True, "user_profile": os.environ.get("USERPROFILE"),
              "python": sys.executable, "runtime_path": str(runtime), "runtime_exists": runtime.is_dir(),
              "config": config_summary, "status": statuses, "registry": checks,
              "registry_passed": len(checks) == 23 and all(check["passed"] for check in checks),
              "unrelated_startup": unrelated, "startup_folder": startup_files(), **system,
              "api_health": local_api(port, "/api/health"),
              "api_terminal": local_api(port, "/api/terminal"),
              "api_market": local_api(port, "/api/market")}
    terminal = report["api_terminal"]
    report["dashboard_ready"] = (terminal.get("http_status") == 200
                                 and terminal.get("settings_present") is True
                                 and str(terminal.get("server", "")).startswith("BitcoinTerminal/"))
    if args.baseline:
        previous = json_file(args.baseline)
        old = previous.get("unrelated_startup", {}) if previous else {}
        report["unrelated_startup_baseline_matches"] = (old.get("sha256") == unrelated["sha256"]
                                                        if old.get("sha256") else None)
    if args.vpn_xml_baseline:
        try:
            raw = args.vpn_xml_baseline.read_bytes()
            encoding = "utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
            expected = normalized_xml_hash(raw.decode(encoding))
            vpn = next((task for task in report.get("tasks", [])
                        if task.get("name") == "WorkStartup - Skyline VPN"), {})
            report["vpn_task_baseline_matches"] = vpn.get("xml_sha256") == expected
        except (OSError, UnicodeError) as exc:
            report["vpn_task_baseline_error"] = type(exc).__name__ + ": " + str(exc)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="Absolute path for this verification JSON report.")
    parser.add_argument("--baseline", type=Path, help="Prior verification JSON whose unrelated startup digests should match.")
    parser.add_argument("--vpn-xml-baseline", type=Path, help="Earlier exported VPN task XML to compare without changing the task.")
    args = parser.parse_args(argv)
    if not args.output.is_absolute():
        parser.error("--output must be an absolute file path")
    if os.name != "nt" or winreg is None:
        parser.error("This verification must run under Windows as the login user")
    report = collect(args)
    # No parent directories are created, so an incorrect destination is visible.
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "registry_passed": report["registry_passed"],
                      "dashboard_ready": report["dashboard_ready"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

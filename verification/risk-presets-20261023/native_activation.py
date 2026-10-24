"""One-shot activation in the real logged-in user's Windows process context."""
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

DIRECTORY = Path(__file__).resolve().parent
ROOT = DIRECTORY.parent.parent
sys.path.insert(0, str(ROOT))
from option_ai_service import KeyVault
from launch_btc_terminal import ensure_server


def read(path):
    with urllib.request.urlopen("http://127.0.0.1:8766" + path, timeout=5) as response:
        return json.load(response)


def main():
    mode = json.loads((DIRECTORY / "native-command.json").read_text(encoding="utf-8"))["mode"]
    result = {"mode": mode, "native_key_readable": KeyVault().read() is not None}
    try:
        if not result["native_key_readable"]:
            raise RuntimeError("native_vault_unreadable")
        if mode == "activate":
            # Stop only the loopback listener whose exact script path belongs
            # to this workspace. Unrelated processes are never selected.
            script = r'''
$ErrorActionPreference = 'Stop'
$listener = Get-NetTCPConnection -LocalAddress '127.0.0.1' -LocalPort 8766 -State Listen -ErrorAction SilentlyContinue
if ($listener) {
  $owned = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $listener.OwningProcess)
  if ($owned.CommandLine -notlike '*D:\Users\yxh\Desktop\options\btc_terminal_server.py*' -or $owned.ExecutablePath -notlike '*\Python39\pythonw.exe') { throw 'Unowned listener' }
  Stop-Process -Id $owned.ProcessId -ErrorAction Stop
}
'''
            completed = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                                       capture_output=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
            if completed.returncode:
                raise RuntimeError("owned_listener_restart_failed")
            ensure_server(root=ROOT, timeout=40)
            result["ai_status"] = read("/api/option-ai/status")
            result["terminal_available"] = isinstance(read("/api/terminal").get("settings"), dict)
            deadline = time.monotonic() + 35
            while True:
                market = read("/api/market")
                if (market.get("options") and market.get("status") == "SUCCESS" and not market.get("stale")) or time.monotonic() >= deadline:
                    break
                time.sleep(.5)
            result["market"] = {"options": len(market.get("options", [])), "revision": market.get("revision"),
                                "instance_id": market.get("instance_id"), "fetched_at": market.get("fetched_at"),
                                "status": market.get("status"), "stale": market.get("stale")}
            result["passed"] = bool(result["ai_status"].get("configured") and result["terminal_available"]
                                    and result["market"]["options"] and result["market"]["status"] == "SUCCESS"
                                    and not result["market"]["stale"])
        elif mode == "preflight":
            result["passed"] = True
        else:
            raise RuntimeError("unsupported_mode")
    except Exception as exc:
        # Public codes only; no raw vault, transport or provider exception.
        result.update(passed=False, error=type(exc).__name__)
    (DIRECTORY / ("native-" + mode + ".json")).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0 if result.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())

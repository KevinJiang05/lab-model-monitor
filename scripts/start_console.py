"""Start/reuse the loopback console with the project's own Python environment."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import webbrowser
from pathlib import Path
from time import monotonic, sleep
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent


def health(url: str) -> bool:
    try:
        with urlopen(url + "api/health", timeout=1) as response:
            result = json.loads(response.read(1024))
    except (URLError, OSError):
        return False
    except (ValueError, TypeError):
        raise RuntimeError("This port belongs to another service.") from None
    if not isinstance(result, dict) or result.get("service") != "lab-model-monitor-console":
        raise RuntimeError("This port belongs to another service.")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Open the local model-monitor console.")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Port must be between 1024 and 65535.")
    python = ROOT / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if not python.exists():
        raise RuntimeError("Independent Python environment is missing.")
    url = f"http://127.0.0.1:{args.port}/"
    if not health(url):
        logs = ROOT / "runtime" / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        with (logs / "console.stdout.log").open("a", encoding="utf-8") as output, (logs / "console.stderr.log").open("a", encoding="utf-8") as error:
            process = subprocess.Popen([str(python), "-X", "utf8", "-m", "lab_model_monitor", "console", "--port", str(args.port)],
                cwd=ROOT, stdin=subprocess.DEVNULL, stdout=output, stderr=error,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                start_new_session=sys.platform != "win32")
        deadline = monotonic() + 8
        while monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("Console could not start. Check runtime/logs/console.stderr.log.")
            if health(url):
                break
            sleep(.2)
        else:
            process.terminate()
            raise RuntimeError("Console startup did not complete.")
    if not args.no_browser:
        webbrowser.open(url)
    print("Local console: " + url)


if __name__ == "__main__":
    main()

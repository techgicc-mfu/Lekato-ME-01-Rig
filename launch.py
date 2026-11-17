"""Desktop app-window launcher for ME-01 Rig."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Sequence

from me01_rig.device_service import DeviceService
from me01_rig.protocol import ProtocolError
from me01_rig.server import create_server
from me01_rig.winmm_midi import MidiTransportError


def _candidate_browser_paths() -> list[Path]:
    """Return standard Windows installation paths for Edge first, then Chrome."""
    pf_x86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
    pf = os.environ.get("PROGRAMFILES", r"C:\Program Files")
    local_app = os.environ.get("LOCALAPPDATA", "")

    candidates: list[Path] = [
        Path(pf_x86) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(pf) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
    ]
    if local_app:
        candidates.append(Path(local_app) / "Microsoft" / "Edge" / "Application" / "msedge.exe")

    candidates.extend(
        [
            Path(pf) / "Google" / "Chrome" / "Application" / "chrome.exe",
            Path(pf_x86) / "Google" / "Chrome" / "Application" / "chrome.exe",
        ]
    )
    if local_app:
        candidates.append(Path(local_app) / "Google" / "Chrome" / "Application" / "chrome.exe")

    return candidates


def find_app_browser() -> Path | None:
    """Locate Microsoft Edge or Google Chrome executable for --app window mode."""
    for candidate in _candidate_browser_paths():
        if candidate.is_file():
            return candidate

    for exe_name in ("msedge.exe", "msedge", "chrome.exe", "chrome"):
        found = shutil.which(exe_name)
        if found:
            path = Path(found)
            if path.is_file():
                return path
    return None


def _browser_profile_dir() -> Path:
    local_app = os.environ.get("LOCALAPPDATA")
    base = Path(local_app) if local_app else Path.home() / "AppData" / "Local"
    return base / "ME01-Rig" / "browser-profile"


def build_browser_command(browser_path: Path, url: str, user_data_dir: Path) -> list[str]:
    """Build Chromium --app launch flags for an isolated desktop-style window."""
    return [
        str(browser_path),
        f"--app={url}",
        f"--user-data-dir={user_data_dir}",
        "--new-window",
    ]


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch ME-01 Rig desktop editor")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Start directly in offline Demo mode without probing USB-MIDI ports",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Run the HTTP server without launching a browser window",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host interface to bind (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="Port to bind (default: 0 for an ephemeral free port)",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None) -> int:
    """Start DeviceService + HTTP server, open Edge/Chrome app window, and clean up on exit."""
    args = _parse_args(argv)
    app_dir = Path(__file__).resolve().parent
    backup_dir = app_dir / "backups"
    fixture_path = app_dir / "tests" / "fixtures" / "me01_captured_vectors.json"

    service = DeviceService(backup_dir=backup_dir, fixture_path=fixture_path)
    server = None
    server_thread: threading.Thread | None = None
    browser_proc: subprocess.Popen[bytes] | None = None
    try:
        if args.demo:
            service.enter_demo_mode()
        else:
            try:
                service.connect()
            except (MidiTransportError, ProtocolError, OSError):
                service.enter_demo_mode()

        server = create_server(service, host=args.host, port=args.port)
        bound_host, bound_port = server.server_address[:2]
        url = f"http://{bound_host}:{bound_port}/"

        server_thread = threading.Thread(
            target=server.serve_forever,
            name="me01-http-server",
            daemon=True,
        )
        server_thread.start()

        if args.no_browser:
            print(f"ME-01 Rig listening at {url}", flush=True)
            while server_thread.is_alive():
                server_thread.join(timeout=0.5)
        else:
            browser = find_app_browser()
            if browser is not None:
                profile_dir = _browser_profile_dir()
                profile_dir.mkdir(parents=True, exist_ok=True)
                cmd = build_browser_command(browser, url, profile_dir)
                browser_proc = subprocess.Popen(cmd)
                while server_thread.is_alive():
                    if browser_proc.poll() is not None:
                        break
                    time.sleep(0.2)
            else:
                webbrowser.open(url)
                print(f"ME-01 Rig listening at {url}", flush=True)
                while server_thread.is_alive():
                    server_thread.join(timeout=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        if server_thread is not None:
            server_thread.join(timeout=2.0)
        service.disconnect()

    return 0


if __name__ == "__main__":
    sys.exit(main())

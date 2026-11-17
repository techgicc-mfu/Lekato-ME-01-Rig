"""Localhost stdlib HTTP JSON API and static file server for ME-01 Rig."""

from __future__ import annotations

import json
import mimetypes
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from .device_service import DeviceService
from .protocol import FactorySlotLockedError, ProtocolError
from .winmm_midi import MidiTransportError

_MAX_JSON_BODY_BYTES = 10 * 1024 * 1024

_STATIC_CONTENT_TYPES: dict[str, str] = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}


class _BadRequestError(ValueError):
    """Raised when an HTTP request has malformed JSON or invalid parameter types."""


def _require_int_value(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _BadRequestError(f"Field '{name}' must be an int, got {type(value).__name__}")
    return value


def _require_int_field(payload: dict[str, Any], key: str) -> int:
    if key not in payload:
        raise _BadRequestError(f"Missing required field: {key}")
    return _require_int_value(payload[key], key)


def _require_bool_field(
    payload: dict[str, Any],
    key: str,
    *,
    default: bool | None = None,
) -> bool:
    if key not in payload:
        if default is not None:
            return default
        raise _BadRequestError(f"Missing required field: {key}")
    value = payload[key]
    if not isinstance(value, bool):
        raise _BadRequestError(f"Field '{key}' must be a boolean, got {type(value).__name__}")
    return value


def _require_str_field(payload: dict[str, Any], key: str) -> str:
    if key not in payload:
        raise _BadRequestError(f"Missing required field: {key}")
    value = payload[key]
    if not isinstance(value, str):
        raise _BadRequestError(f"Field '{key}' must be a string, got {type(value).__name__}")
    return value


def _require_int_list_field(payload: dict[str, Any], key: str) -> list[int]:
    if key not in payload:
        raise _BadRequestError(f"Missing required field: {key}")
    value = payload[key]
    if not isinstance(value, list):
        raise _BadRequestError(f"Field '{key}' must be a list of ints, got {type(value).__name__}")
    return [_require_int_value(item, f"{key}[{idx}]") for idx, item in enumerate(value)]


def _guess_content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in _STATIC_CONTENT_TYPES:
        return _STATIC_CONTENT_TYPES[suffix]
    guessed, _ = mimetypes.guess_type(path.name)
    if not guessed:
        return "application/octet-stream"
    if guessed.startswith("text/") and "charset=" not in guessed:
        return f"{guessed}; charset=utf-8"
    return guessed


class ME01HTTPServer(ThreadingHTTPServer):
    """Threaded HTTP server carrying the DeviceService and static directory."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        server_address: tuple[str, int],
        service: DeviceService,
        static_dir: Path,
    ) -> None:
        self.service = service
        self.static_dir = Path(static_dir)
        super().__init__(server_address, ME01RequestHandler)


class ME01RequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for ME-01 JSON API endpoints and static assets."""

    server: ME01HTTPServer

    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/api" or path.startswith("/api/"):
            self._handle_api_request("GET", path)
            return
        self._serve_static(path)

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        if path == "/api" or path.startswith("/api/"):
            self._handle_api_request("POST", path)
            return
        self._send_json(404, {"error": "Not found"}, no_store=False)

    def _handle_api_request(self, method: str, path: str) -> None:
        try:
            if method == "GET":
                self._dispatch_get(path)
            else:
                self._dispatch_post(path)
        except FactorySlotLockedError as exc:
            self._send_json(403, {"error": str(exc)})
        except (ProtocolError, _BadRequestError) as exc:
            self._send_json(400, {"error": str(exc)})
        except MidiTransportError as exc:
            self._send_json(502, {"error": str(exc)})
        except Exception as exc:
            self._send_json(500, {"error": str(exc)})

    def _dispatch_get(self, path: str) -> None:
        svc = self.server.service
        if path in ("/api/state", "/api/status"):
            self._send_json(200, svc.get_state())
            return
        if path == "/api/ports":
            self._send_json(200, {"ports": svc.list_ports()})
            return
        if path == "/api/presets":
            self._send_json(200, {"presets": svc.get_presets()})
            return
        if path == "/api/backup/export":
            meta = svc.export_backup()
            backup_data = json.loads(Path(meta["path"]).read_text(encoding="utf-8"))
            export_payload = {
                **backup_data,
                "path": meta["path"],
                "filename": meta.get("filename"),
            }
            self._send_json(
                200,
                export_payload,
                content_type="application/json",
                extra_headers={
                    "Content-Disposition": 'attachment; filename="me01-backup.json"'
                },
            )
            return
        self._send_json(404, {"error": "Not found"})

    def _dispatch_post(self, path: str) -> None:
        svc = self.server.service
        if path == "/api/shutdown":
            self._send_json(200, {"ok": True})
            threading.Thread(
                target=self.server.shutdown,
                name="me01-http-shutdown",
                daemon=True,
            ).start()
            return

        body = self._read_json_body()

        if path == "/api/connect":
            in_id = (
                _require_int_value(body["in_id"], "in_id")
                if body.get("in_id") is not None
                else None
            )
            out_id = (
                _require_int_value(body["out_id"], "out_id")
                if body.get("out_id") is not None
                else None
            )
            auto_backup = _require_bool_field(body, "auto_backup", default=True)
            self._send_json(200, svc.connect(in_id=in_id, out_id=out_id, auto_backup=auto_backup))
            return

        if path == "/api/disconnect":
            svc.disconnect()
            self._send_json(200, svc.get_state())
            return

        if path == "/api/demo":
            self._send_json(200, svc.enter_demo_mode())
            return

        if path == "/api/preset/load":
            preset_id = _require_int_field(body, "preset_id")
            self._send_json(200, svc.load_preset(preset_id))
            return

        if path == "/api/ram/refresh":
            self._send_json(200, svc.refresh_ram())
            return

        if path == "/api/ram/revert":
            self._send_json(200, svc.revert_to_slot())
            return

        if path == "/api/ram/undo":
            self._send_json(200, svc.undo())
            return

        if path == "/api/ram/toggle":
            block_id = _require_int_field(body, "block_id")
            enabled = _require_bool_field(body, "enabled")
            self._send_json(200, svc.toggle_block(block_id, enabled))
            return

        if path == "/api/ram/model":
            block_id = _require_int_field(body, "block_id")
            model_id = _require_int_field(body, "model_id")
            self._send_json(200, svc.change_model(block_id, model_id))
            return

        if path == "/api/ram/knob":
            addr = _require_int_field(body, "addr")
            value = _require_int_field(body, "value")
            self._send_json(200, svc.change_knob(addr, value))
            return

        if path == "/api/ram/order":
            order = _require_int_list_field(body, "order")
            self._send_json(200, svc.change_routing(order))
            return

        if path == "/api/ram/apply":
            raw_hex = _require_str_field(body, "raw_hex")
            try:
                raw_bytes = bytes.fromhex(raw_hex)
            except ValueError as exc:
                raise _BadRequestError(f"Invalid raw_hex: {exc}") from exc
            self._send_json(200, svc.apply_preset_to_ram(raw_bytes))
            return

        if path == "/api/flash/save":
            preset_id = _require_int_field(body, "preset_id")
            allow_factory = _require_bool_field(body, "allow_factory", default=False)
            self._send_json(200, svc.save_flash_slot(preset_id, allow_factory=allow_factory))
            return

        if path == "/api/backup/audition":
            preset_id = _require_int_field(body, "preset_id")
            backup_data = self._extract_backup_payload(body, allow_top_level=True)
            self._send_json(200, svc.audition_backup_preset(backup_data, preset_id))
            return

        if path == "/api/backup/restore":
            slot_ids = _require_int_list_field(body, "slot_ids")
            allow_factory = _require_bool_field(body, "allow_factory", default=False)
            backup_data = self._extract_backup_payload(
                body, allow_top_level=("presets_hex" in body)
            )
            self._send_json(
                200,
                svc.batch_restore_backup(backup_data, slot_ids, allow_factory=allow_factory),
            )
            return

        self._send_json(404, {"error": "Not found"})

    @staticmethod
    def _extract_backup_payload(
        body: dict[str, Any], *, allow_top_level: bool
    ) -> dict[str, Any]:
        if "backup" in body:
            backup_data = body["backup"]
            if not isinstance(backup_data, dict):
                raise _BadRequestError("Field 'backup' must be a JSON object")
            return backup_data
        if allow_top_level:
            return body
        raise _BadRequestError("Missing required field: backup")

    def _read_json_body(self) -> dict[str, Any]:
        raw_len = self.headers.get("Content-Length")
        if raw_len is None:
            return {}
        try:
            content_len = int(raw_len)
        except ValueError as exc:
            raise _BadRequestError("Invalid Content-Length header") from exc
        if content_len < 0:
            raise _BadRequestError("Negative Content-Length header")
        if content_len > _MAX_JSON_BODY_BYTES:
            raise _BadRequestError("Request body too large")
        if content_len == 0:
            return {}

        raw_bytes = self.rfile.read(content_len)
        if len(raw_bytes) != content_len:
            raise _BadRequestError("Incomplete request body")
        try:
            text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise _BadRequestError(f"Request body must be valid UTF-8: {exc}") from exc
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise _BadRequestError(f"Malformed JSON body: {exc}") from exc
        if not isinstance(parsed, dict):
            raise _BadRequestError("JSON request body must be an object")
        return parsed

    def _serve_static(self, raw_path: str) -> None:
        decoded = unquote(raw_path)
        if "\x00" in decoded or "\\" in decoded:
            self._send_text(404, "Not found")
            return

        static_root = self.server.static_dir
        if not static_root.is_dir():
            self._send_text(404, "Not found")
            return

        base_dir = static_root.resolve()
        rel = "index.html" if decoded in ("", "/") else decoded.lstrip("/")
        if not rel or rel.endswith("/"):
            self._send_text(404, "Not found")
            return

        candidate = (base_dir / rel).resolve()
        if (
            not candidate.is_relative_to(base_dir)
            or candidate == base_dir
            or not candidate.is_file()
        ):
            self._send_text(404, "Not found")
            return

        data = candidate.read_bytes()
        content_type = _guess_content_type(candidate)
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
        self.wfile.flush()

    def _send_json(
        self,
        status: int,
        payload: dict[str, Any],
        *,
        no_store: bool = True,
        content_type: str = "application/json; charset=utf-8",
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        if no_store:
            self.send_header("Cache-Control", "no-store")
        if extra_headers:
            for key, value in extra_headers.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(encoded)
        self.wfile.flush()

    def _send_text(self, status: int, text: str) -> None:
        encoded = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)
        self.wfile.flush()


def create_server(
    service: DeviceService,
    host: str = "127.0.0.1",
    port: int = 0,
    static_dir: Path | None = None,
) -> ThreadingHTTPServer:
    """Create a threaded localhost HTTP server bound to the given host and port."""
    resolved_static = (
        Path(static_dir)
        if static_dir is not None
        else Path(__file__).resolve().parent / "static"
    )
    return ME01HTTPServer((host, port), service=service, static_dir=resolved_static)

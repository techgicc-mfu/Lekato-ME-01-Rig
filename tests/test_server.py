from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import launch
from me01_rig.device_service import DeviceService
from me01_rig.protocol import PresetImage
from me01_rig.server import create_server
from me01_rig.winmm_midi import MidiPortPair, MidiTransportError
from tests.test_device_service import FIXTURE_PATH, FakeTransport


class ServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name)
        self.backup_dir = self.tmp_path / "backups"
        self.fixture_data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    def _start_server(
        self,
        *,
        demo: bool = True,
        static_dir: Path | None = None,
        transport_factory: Any = None,
        port_finder: Any = None,
    ) -> tuple[DeviceService, Any, int]:
        service = DeviceService(
            backup_dir=self.backup_dir,
            fixture_path=FIXTURE_PATH,
            transport_factory=transport_factory,
            port_finder=port_finder,
            poll_interval_s=60.0,
        )
        if demo:
            service.enter_demo_mode()
        if static_dir is None:
            static_dir = self.tmp_path / "missing_static"

        server = create_server(service, host="127.0.0.1", port=0, static_dir=static_dir)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def _cleanup() -> None:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2.0)
            service.disconnect()

        self.addCleanup(_cleanup)
        return service, server, int(server.server_address[1])

    @staticmethod
    def _request(
        port: int,
        method: str,
        path: str,
        body: bytes | str | dict[str, Any] | list[Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5.0)
        try:
            req_headers = dict(headers or {})
            payload: bytes | None
            if body is None:
                payload = None
            elif isinstance(body, bytes):
                payload = body
            elif isinstance(body, str):
                payload = body.encode("utf-8")
            else:
                payload = json.dumps(body).encode("utf-8")
                req_headers.setdefault("Content-Type", "application/json")

            conn.request(method, path, body=payload, headers=req_headers)
            resp = conn.getresponse()
            raw = resp.read()
            resp_headers = {k.lower(): v for k, v in resp.getheaders()}
            return resp.status, resp_headers, raw
        finally:
            conn.close()

    def _json_request(
        self,
        port: int,
        method: str,
        path: str,
        body: bytes | str | dict[str, Any] | list[Any] | None = None,
    ) -> tuple[int, dict[str, str], dict[str, Any]]:
        status, headers, raw = self._request(port, method, path, body=body)
        return status, headers, json.loads(raw.decode("utf-8"))

    def test_get_state_and_presets(self) -> None:
        pairs = [MidiPortPair(in_id=2, in_name="SINCO USB-MIDI", out_id=3, out_name="SINCO USB-MIDI", match_score=140)]
        _, _, port = self._start_server(demo=True, port_finder=lambda: pairs)

        status, headers, state = self._json_request(port, "GET", "/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("cache-control"), "no-store")
        self.assertTrue(state["demo"])
        self.assertFalse(state["connected"])
        self.assertEqual(len(state["amps"]), 20)
        self.assertEqual(len(state["cabs"]), 20)
        self.assertEqual(len(state["presets_summary"]), 80)
        self.assertIsInstance(state["ram"], dict)
        self.assertEqual(len(state["ram"]["blocks"]), 6)

        status_alias, _, state_alias = self._json_request(port, "GET", "/api/status")
        self.assertEqual(status_alias, 200)
        self.assertEqual(state_alias["active_preset"], state["active_preset"])

        status_ports, _, ports_data = self._json_request(port, "GET", "/api/ports")
        self.assertEqual(status_ports, 200)
        self.assertEqual(len(ports_data["ports"]), 1)
        self.assertEqual(ports_data["ports"][0]["in_id"], 2)

        status_presets, _, presets_data = self._json_request(port, "GET", "/api/presets")
        self.assertEqual(status_presets, 200)
        self.assertEqual(len(presets_data["presets"]), 80)
        self.assertEqual(presets_data["presets"][0]["label"], "P01")
        self.assertEqual(presets_data["presets"][79]["label"], "P80")

    def test_invalid_inputs_return_400_403(self) -> None:
        _, _, port = self._start_server(demo=True)

        bad_400_cases: list[tuple[str, Any]] = [
            ("/api/ram/order", {"order": [0, 0, 1, 2, 3, 4]}),
            ("/api/ram/knob", {"addr": 21, "value": 50}),
            ("/api/ram/knob", {"addr": 32, "value": 150}),
            ("/api/ram/knob", {"addr": True, "value": 50}),
            ("/api/ram/knob", {"addr": 0}),
            ("/api/ram/toggle", {"block_id": 0, "enabled": 1}),
            ("/api/ram/model", {"block_id": 0, "model_id": 99}),
            ("/api/ram/apply", {"raw_hex": "zzzz"}),
            ("/api/flash/save", {"preset_id": 80}),
            ("/api/flash/save", {"preset_id": 5, "allow_factory": "true"}),
            ("/api/ram/order", "{not valid json"),
            ("/api/ram/order", [0, 1, 2, 3, 4, 5]),
        ]
        for path, body in bad_400_cases:
            with self.subTest(path=path, body=body):
                status, headers, data = self._json_request(port, "POST", path, body=body)
                self.assertEqual(status, 400)
                self.assertEqual(headers.get("cache-control"), "no-store")
                self.assertIn("error", data)

        for body in ({"preset_id": 5, "allow_factory": False}, {"preset_id": 5}):
            status, _, data = self._json_request(port, "POST", "/api/flash/save", body=body)
            self.assertEqual(status, 403)
            self.assertIn("error", data)

        status_404, _, data_404 = self._json_request(port, "GET", "/api/nonexistent")
        self.assertEqual(status_404, 404)
        self.assertEqual(data_404, {"error": "Not found"})

    def test_valid_ram_edits_and_flash_save(self) -> None:
        _, _, port = self._start_server(demo=True)

        status, _, state = self._json_request(port, "POST", "/api/preset/load", {"preset_id": 79})
        self.assertEqual(status, 200)
        self.assertEqual(state["active_preset"], 79)

        status, _, state = self._json_request(port, "POST", "/api/ram/toggle", {"block_id": 2, "enabled": True})
        self.assertEqual(status, 200)
        self.assertEqual(state["ram"]["states"][2], 1)

        status, _, state = self._json_request(port, "POST", "/api/ram/model", {"block_id": 2, "model_id": 3})
        self.assertEqual(status, 200)
        self.assertEqual(state["ram"]["models"][2], 3)

        status, _, state = self._json_request(port, "POST", "/api/ram/knob", {"addr": 0, "value": 77})
        self.assertEqual(status, 200)
        self.assertEqual(state["ram"]["volume"], 77)

        status, _, state = self._json_request(
            port, "POST", "/api/ram/order", {"order": [5, 1, 0, 2, 3, 4]}
        )
        self.assertEqual(status, 200)
        self.assertEqual(state["ram"]["order"], [5, 1, 0, 2, 3, 4])
        undo_before = state["undo_depth"]
        self.assertGreaterEqual(undo_before, 1)

        status, _, state = self._json_request(port, "POST", "/api/ram/undo")
        self.assertEqual(status, 200)
        self.assertEqual(state["undo_depth"], undo_before - 1)
        self.assertNotEqual(state["ram"]["order"], [5, 1, 0, 2, 3, 4])

        target_img = PresetImage.from_bytes(bytes.fromhex(self.fixture_data["presets_hex"][10]))
        status, _, state = self._json_request(
            port, "POST", "/api/ram/apply", {"raw_hex": target_img.to_bytes().hex()}
        )
        self.assertEqual(status, 200)
        self.assertEqual(state["ram"]["raw_hex"], target_img.to_bytes().hex())

        status, headers, exported = self._json_request(port, "GET", "/api/backup/export")
        self.assertEqual(status, 200)
        self.assertIn("attachment", headers.get("content-disposition", ""))
        self.assertEqual(len(exported["presets_hex"]), 80)
        self.assertTrue(Path(exported["path"]).is_file())

        status, _, saved = self._json_request(
            port, "POST", "/api/flash/save", {"preset_id": 79, "allow_factory": False}
        )
        self.assertEqual(status, 200)
        self.assertTrue(saved["verified"])
        self.assertEqual(saved["preset_id"], 79)
        self.assertEqual(saved["presets_summary"][79]["raw_hex"], target_img.to_bytes().hex())

        status, _, refreshed = self._json_request(port, "POST", "/api/ram/refresh")
        self.assertEqual(status, 200)
        self.assertEqual(refreshed["active_preset"], 79)

        status, _, reverted = self._json_request(port, "POST", "/api/ram/revert")
        self.assertEqual(status, 200)
        self.assertEqual(reverted["ram"]["raw_hex"], target_img.to_bytes().hex())

    def test_backup_audition_and_restore(self) -> None:
        _, _, port = self._start_server(demo=True)

        status, _, backup = self._json_request(port, "GET", "/api/backup/export")
        self.assertEqual(status, 200)

        # Modify slot 79 and RAM, then audition slot 3 from backup (wrapped and unwrapped forms).
        self._json_request(port, "POST", "/api/preset/load", {"preset_id": 79})
        self._json_request(port, "POST", "/api/ram/knob", {"addr": 0, "value": 99})
        self._json_request(port, "POST", "/api/flash/save", {"preset_id": 79, "allow_factory": False})

        status, _, state = self._json_request(
            port, "POST", "/api/backup/audition", {"backup": backup, "preset_id": 3}
        )
        self.assertEqual(status, 200)
        self.assertEqual(state["ram"]["raw_hex"], backup["presets_hex"][3])

        unwrapped = {**backup, "preset_id": 4}
        status, _, state = self._json_request(port, "POST", "/api/backup/audition", unwrapped)
        self.assertEqual(status, 200)
        self.assertEqual(state["ram"]["raw_hex"], backup["presets_hex"][4])

        # Factory restore without allow_factory -> 403
        status, _, err = self._json_request(
            port, "POST", "/api/backup/restore", {"backup": backup, "slot_ids": [0], "allow_factory": False}
        )
        self.assertEqual(status, 403)
        self.assertIn("error", err)

        # User slot restore -> 200
        status, _, restored = self._json_request(
            port, "POST", "/api/backup/restore", {"backup": backup, "slot_ids": [79]}
        )
        self.assertEqual(status, 200)
        self.assertTrue(restored["verified"])
        self.assertEqual(restored["restored_slots"], [79])
        self.assertEqual(restored["presets_summary"][79]["raw_hex"], backup["presets_hex"][79])

    def test_connect_disconnect_demo_and_transport_error_502(self) -> None:
        fake = FakeTransport(self.fixture_data)
        pairs = [MidiPortPair(in_id=0, in_name="SINCO", out_id=1, out_name="SINCO", match_score=140)]
        _, _, port = self._start_server(
            demo=False,
            transport_factory=lambda in_id, out_id: fake,
            port_finder=lambda: pairs,
        )

        # Disconnected write -> 502 MidiTransportError
        status, _, err = self._json_request(
            port, "POST", "/api/ram/toggle", {"block_id": 0, "enabled": True}
        )
        self.assertEqual(status, 502)
        self.assertIn("error", err)

        # Connect with FakeTransport
        status, _, state = self._json_request(
            port, "POST", "/api/connect", {"in_id": 0, "out_id": 1, "auto_backup": False}
        )
        self.assertEqual(status, 200)
        self.assertTrue(state["connected"])
        self.assertFalse(state["demo"])

        # Transport failure during write -> 502
        def _boom(_tr: Any, _req: Any) -> None:
            raise MidiTransportError("USB unplugged")

        fake.on_transact = _boom
        status, _, err = self._json_request(
            port, "POST", "/api/ram/toggle", {"block_id": 0, "enabled": False}
        )
        self.assertEqual(status, 502)
        self.assertIn("USB unplugged", err["error"])
        fake.on_transact = None

        status, _, state = self._json_request(port, "POST", "/api/disconnect")
        self.assertEqual(status, 200)
        self.assertFalse(state["connected"])
        self.assertFalse(state["demo"])

        status, _, state = self._json_request(port, "POST", "/api/demo")
        self.assertEqual(status, 200)
        self.assertTrue(state["demo"])

    def test_static_files_and_path_traversal_guard(self) -> None:
        static_dir = self.tmp_path / "static"
        static_dir.mkdir()
        (static_dir / "index.html").write_text("<h1>ME-01 Rig</h1>", encoding="utf-8")
        (static_dir / "styles.css").write_text("body { color: #fff; }", encoding="utf-8")
        (static_dir / "app.js").write_text("console.log('ok');", encoding="utf-8")
        (self.tmp_path / "secret.txt").write_text("top-secret", encoding="utf-8")

        _, _, port = self._start_server(demo=True, static_dir=static_dir)

        status, headers, body = self._request(port, "GET", "/")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("content-type"), "text/html; charset=utf-8")
        self.assertIn(b"ME-01 Rig", body)

        status, headers, _ = self._request(port, "GET", "/styles.css")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("content-type"), "text/css; charset=utf-8")

        status, headers, _ = self._request(port, "GET", "/app.js")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("content-type"), "application/javascript; charset=utf-8")

        for traversal_path in ("/../secret.txt", "/%2e%2e/secret.txt", "/missing.js", "/bad:name"):
            status, _, _ = self._request(port, "GET", traversal_path)
            self.assertEqual(status, 404)

    def test_shutdown_endpoint(self) -> None:
        service = DeviceService(
            backup_dir=self.backup_dir,
            fixture_path=FIXTURE_PATH,
            poll_interval_s=60.0,
        )
        service.enter_demo_mode()
        server = create_server(service, host="127.0.0.1", port=0, static_dir=self.tmp_path / "none")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(service.disconnect)
        self.addCleanup(server.server_close)

        port = int(server.server_address[1])
        status, _, data = self._json_request(port, "POST", "/api/shutdown")
        self.assertEqual(status, 200)
        self.assertEqual(data, {"ok": True})
        thread.join(timeout=3.0)
        self.assertFalse(thread.is_alive())

    def test_launcher_find_app_browser_and_main(self) -> None:
        edge_dir = self.tmp_path / "Edge" / "Application"
        chrome_dir = self.tmp_path / "Chrome" / "Application"
        edge_dir.mkdir(parents=True)
        chrome_dir.mkdir(parents=True)
        edge_exe = edge_dir / "msedge.exe"
        chrome_exe = chrome_dir / "chrome.exe"
        chrome_exe.write_bytes(b"")

        # When only Chrome exists in candidate paths, Chrome is returned
        with (
            mock.patch.object(launch, "_candidate_browser_paths", return_value=[edge_exe, chrome_exe]),
            mock.patch("shutil.which", return_value=None),
        ):
            self.assertEqual(launch.find_app_browser(), chrome_exe)

        # When Edge also exists, Edge takes priority
        edge_exe.write_bytes(b"")
        with (
            mock.patch.object(launch, "_candidate_browser_paths", return_value=[edge_exe, chrome_exe]),
            mock.patch("shutil.which", return_value=None),
        ):
            self.assertEqual(launch.find_app_browser(), edge_exe)

        # When neither exists, None is returned
        with (
            mock.patch.object(launch, "_candidate_browser_paths", return_value=[self.tmp_path / "missing.exe"]),
            mock.patch("shutil.which", return_value=None),
        ):
            self.assertIsNone(launch.find_app_browser())

        # Verify launch.main starts in demo mode (--demo --no-browser) and shuts down cleanly via /api/shutdown
        started_port: list[int] = []
        ready = threading.Event()
        orig_create_server = launch.create_server

        def _spy_create_server(*args: Any, **kwargs: Any) -> Any:
            srv = orig_create_server(*args, **kwargs)
            started_port.append(int(srv.server_address[1]))
            ready.set()
            return srv

        def _trigger_shutdown() -> None:
            if ready.wait(timeout=5.0) and started_port:
                self._json_request(started_port[0], "POST", "/api/shutdown")

        shutter = threading.Thread(target=_trigger_shutdown, daemon=True)
        shutter.start()
        with mock.patch.object(launch, "create_server", side_effect=_spy_create_server):
            exit_code = launch.main(["--demo", "--no-browser", "--port", "0"])
        shutter.join(timeout=2.0)
        self.assertEqual(exit_code, 0)
        self.assertEqual(len(started_port), 1)

    def test_launcher_disconnects_on_startup_failure(self) -> None:
        mock_service = mock.MagicMock(spec=DeviceService)
        with (
            mock.patch.object(launch, "DeviceService", return_value=mock_service),
            mock.patch.object(launch, "create_server", side_effect=OSError("port in use")),
        ):
            with self.assertRaises(OSError):
                launch.main(["--no-browser", "--port", "8765"])

        mock_service.connect.assert_called_once_with()
        mock_service.disconnect.assert_called_once_with()

    def test_models_rename_audition_and_library_routes(self) -> None:
        import base64

        _, _, port = self._start_server(demo=True)

        # 1. GET /api/models/library
        status_lib, _, lib_body = self._json_request(port, "GET", "/api/models/library")
        self.assertEqual(status_lib, 200)
        self.assertIn("library", lib_body)
        self.assertIn("categories", lib_body["library"])

        # 2. POST /api/models/rename
        status_ren, _, ren_body = self._json_request(
            port,
            "POST",
            "/api/models/rename",
            {"category": "amp", "slot": 1, "name": "AC30 TopBoost"},
        )
        self.assertEqual(status_ren, 200)
        self.assertTrue(ren_body["ok"])
        self.assertEqual(ren_body["name"], "AC30 TopBoost")
        self.assertEqual(ren_body["state"]["amps"][1], "AC30 TopBoost")

        # Invalid rename
        status_bad, _, bad_body = self._json_request(
            port,
            "POST",
            "/api/models/rename",
            {"category": "mod", "slot": 1, "name": "InvalidCat"},
        )
        self.assertEqual(status_bad, 400)
        self.assertIn("error", bad_body)

        # 3. POST /api/models/audition
        status_aud, _, aud_body = self._json_request(
            port,
            "POST",
            "/api/models/audition",
            {"category": "amp", "slot": 3},
        )
        self.assertEqual(status_aud, 200)
        self.assertTrue(aud_body["ok"])
        amp_blk = next(b for b in aud_body["state"]["ram"]["blocks"] if b["block_id"] == 1)
        self.assertEqual(amp_blk["model_id"], 3)
        self.assertTrue(amp_blk["enabled"])

        # 4. POST /api/models/validate_import
        raw_am4 = b"AM4\x003VAVE_TS\x00\x00\x00\x00\x00" + b"\x00" * 100
        b64_content = base64.b64encode(raw_am4).decode("ascii")
        status_imp, _, imp_body = self._json_request(
            port,
            "POST",
            "/api/models/validate_import",
            {"filename": "TS9.am4", "content_base64": b64_content},
        )
        self.assertEqual(status_imp, 200)
        self.assertTrue(imp_body["ok"])
        self.assertEqual(imp_body["kind"], "amp")
        self.assertEqual(imp_body["details"]["name"], "3VAVE_TS")

        # Invalid import
        status_bad_imp, _, bad_imp_body = self._json_request(
            port,
            "POST",
            "/api/models/validate_import",
            {"filename": "corrupt.am4", "content_base64": "Tm90VmFsaWQ="},
        )
        self.assertEqual(status_bad_imp, 400)
        self.assertIn("error", bad_imp_body)

    def test_capture_manager_integration_end_to_end(self) -> None:
        import base64

        _, _, port = self._start_server(demo=True)

        # 1. Fetch curated library
        s_lib, _, b_lib = self._json_request(port, "GET", "/api/models/library")
        self.assertEqual(s_lib, 200)
        categories = b_lib["library"]["categories"]
        od_cat = next(c for c in categories if c["id"] == "overdrives")
        self.assertGreaterEqual(len(od_cat["models"]), 3)

        # 2. Validate import of user capture
        raw_am4 = b"AM4\x00TS808 Custom\x00\x00" + b"\x00" * 100
        b64 = base64.b64encode(raw_am4).decode("ascii")
        s_val, _, b_val = self._json_request(
            port,
            "POST",
            "/api/models/validate_import",
            {"filename": "TS808.am4", "content_base64": b64},
        )
        self.assertEqual(s_val, 200)
        self.assertEqual(b_val["details"]["name"], "TS808 Custom")

        # 3. Rename AMP slot 0 to the validated capture name
        s_ren, _, b_ren = self._json_request(
            port,
            "POST",
            "/api/models/rename",
            {"category": "amp", "slot": 0, "name": b_val["details"]["name"]},
        )
        self.assertEqual(s_ren, 200)
        self.assertEqual(b_ren["state"]["amps"][0], "TS808 Custom")

        # 4. Audition slot 0 in live RAM
        s_aud, _, b_aud = self._json_request(
            port,
            "POST",
            "/api/models/audition",
            {"category": "amp", "slot": 0},
        )
        self.assertEqual(s_aud, 200)
        amp_blk = next(b for b in b_aud["state"]["ram"]["blocks"] if b["block_id"] == 1)
        self.assertEqual(amp_blk["model_id"], 0)
        self.assertTrue(amp_blk["enabled"])

        # 5. Query /api/state to verify roundtrip state sync
        s_st, _, b_st = self._json_request(port, "GET", "/api/state")
        self.assertEqual(s_st, 200)
        self.assertEqual(b_st["amps"][0], "TS808 Custom")
        amp_st = next(b for b in b_st["ram"]["blocks"] if b["block_id"] == 1)
        self.assertEqual(amp_st["model_id"], 0)
        self.assertTrue(amp_st["enabled"])


if __name__ == "__main__":
    unittest.main()

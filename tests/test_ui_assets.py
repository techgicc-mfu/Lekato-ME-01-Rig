from __future__ import annotations

import http.client
import json
import re
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any

from me01_rig.device_service import DeviceService
from me01_rig.server import create_server
from tests.test_device_service import FIXTURE_PATH

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = REPO_ROOT / "me01_rig" / "static"
INDEX_HTML = STATIC_DIR / "index.html"
STYLES_CSS = STATIC_DIR / "styles.css"
APP_JS = STATIC_DIR / "app.js"
SERVER_PY = REPO_ROOT / "me01_rig" / "server.py"


class UIAssetsTests(unittest.TestCase):
    def _start_demo_server(self) -> int:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        service = DeviceService(
            backup_dir=Path(tmp.name) / "backups",
            fixture_path=FIXTURE_PATH,
            poll_interval_s=60.0,
        )
        service.enter_demo_mode()

        server = create_server(service, host="127.0.0.1", port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def _cleanup() -> None:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2.0)
            service.disconnect()

        self.addCleanup(_cleanup)
        return int(server.server_address[1])

    @staticmethod
    def _get(port: int, path: str) -> tuple[int, dict[str, str], bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5.0)
        try:
            conn.request("GET", path)
            resp = conn.getresponse()
            raw = resp.read()
            headers = {k.lower(): v for k, v in resp.getheaders()}
            return resp.status, headers, raw
        finally:
            conn.close()

    def test_static_files_exist_and_are_100_percent_offline(self) -> None:
        for asset in (INDEX_HTML, STYLES_CSS, APP_JS):
            self.assertTrue(asset.is_file(), f"Missing static UI asset: {asset}")
            content = asset.read_text(encoding="utf-8")
            self.assertGreater(len(content.strip()), 0, f"Empty static UI asset: {asset}")
            self.assertNotRegex(
                content,
                r"""https?://|<(?:script|link|img|iframe)[^>]*(?:src|href)\s*=\s*["']\s*//|@import|url\(\s*["']?\s*(?:https?:)?//""",
                f"External URL found in {asset.name}; UI must work 100% offline",
            )

    def test_server_serves_static_ui_and_demo_endpoints(self) -> None:
        port = self._start_demo_server()

        status, headers, html_raw = self._get(port, "/")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("content-type"), "text/html; charset=utf-8")
        html_text = html_raw.decode("utf-8")
        self.assertIn("ME-01", html_text)
        self.assertIn("/styles.css", html_text)
        self.assertIn("/app.js", html_text)

        status_css, headers_css, css_raw = self._get(port, "/styles.css")
        self.assertEqual(status_css, 200)
        self.assertEqual(headers_css.get("content-type"), "text/css; charset=utf-8")
        self.assertIn("#0d0e10", css_raw.decode("utf-8").lower())

        status_js, headers_js, js_raw = self._get(port, "/app.js")
        self.assertEqual(status_js, 200)
        self.assertEqual(headers_js.get("content-type"), "application/javascript; charset=utf-8")
        self.assertGreater(len(js_raw), 500)

        status_state, _, state_raw = self._get(port, "/api/state")
        self.assertEqual(status_state, 200)
        state: dict[str, Any] = json.loads(state_raw.decode("utf-8"))
        self.assertTrue(state["demo"])
        self.assertEqual(len(state["amps"]), 20)
        self.assertEqual(len(state["cabs"]), 20)
        self.assertEqual(len(state["ram"]["blocks"]), 6)

        status_presets, _, presets_raw = self._get(port, "/api/presets")
        self.assertEqual(status_presets, 200)
        presets_data = json.loads(presets_raw.decode("utf-8"))
        self.assertEqual(len(presets_data["presets"]), 80)

    def test_app_js_passes_node_syntax_check(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("node executable not found on PATH")
        self.assertTrue(APP_JS.is_file(), f"Missing {APP_JS}")
        proc = subprocess.run(
            [node, "--check", str(APP_JS)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            proc.returncode,
            0,
            f"node --check failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}",
        )

    def test_app_js_api_routes_align_with_server_py(self) -> None:
        self.assertTrue(APP_JS.is_file(), f"Missing {APP_JS}")
        js_text = APP_JS.read_text(encoding="utf-8")
        server_text = SERVER_PY.read_text(encoding="utf-8")

        js_routes = set(re.findall(r"""["'`](?:/api/[a-zA-Z0-9_/-]+)["'`]""", js_text))
        js_routes = {item.strip("\"'`") for item in js_routes}
        server_routes = set(re.findall(r"""["'](/api/[a-zA-Z0-9_/-]+)["']""", server_text))

        self.assertTrue(js_routes, "Expected /api/... routes in app.js")
        unknown_routes = js_routes - server_routes
        self.assertEqual(
            unknown_routes,
            set(),
            f"app.js references routes missing from server.py: {sorted(unknown_routes)}",
        )

        expected_core_routes = {
            "/api/state",
            "/api/ports",
            "/api/presets",
            "/api/connect",
            "/api/disconnect",
            "/api/demo",
            "/api/preset/load",
            "/api/ram/refresh",
            "/api/ram/revert",
            "/api/ram/undo",
            "/api/ram/toggle",
            "/api/ram/model",
            "/api/ram/knob",
            "/api/ram/order",
            "/api/flash/save",
            "/api/backup/export",
            "/api/backup/audition",
            "/api/backup/restore",
        }
        missing_core = expected_core_routes - js_routes
        self.assertEqual(
            missing_core,
            set(),
            f"app.js missing core backend endpoints: {sorted(missing_core)}",
        )

    def test_required_ui_controls_labels_and_xss_safety(self) -> None:
        self.assertTrue(INDEX_HTML.is_file(), f"Missing {INDEX_HTML}")
        self.assertTrue(APP_JS.is_file(), f"Missing {APP_JS}")
        html_text = INDEX_HTML.read_text(encoding="utf-8")
        js_text = APP_JS.read_text(encoding="utf-8")
        combined = f"{html_text}\n{js_text}"

        required_tokens = [
            "ME-01",
            "RIG",
            "Earlier",
            "Later",
            "+ parallel",
            "Save to Slot",
            "Refresh RAM",
            "Revert",
            "Undo",
            "Tap Tempo",
            "BPM",
            "Backup",
            "AI Gate MS",
            "V17+",
            "High Cut",
            "5.0",
            "18.0",
            "Unlock Factory",
            "Audition in RAM",
            "Batch Flash Restore",
            "1200",
            "50",
        ]
        for token in required_tokens:
            self.assertIn(token, combined, f"Expected UI token missing: {token!r}")

        self.assertNotIn(".innerHTML", js_text, "Use DOM APIs / textContent instead of innerHTML")
        self.assertNotIn("insertAdjacentHTML", js_text, "Avoid insertAdjacentHTML for XSS safety")

    def test_ui_focus_and_restore_summary_guards(self) -> None:
        js_text = APP_JS.read_text(encoding="utf-8")
        self.assertIn("renderedInspectorKey", js_text)
        self.assertIn("restoreSummaryText", js_text)
        self.assertIn("app.knobQueue.get(addr) !== entry", js_text)
        self.assertIn('event.target.value = ""', js_text)

    def test_skeuomorphic_pedal_templates_and_themes(self) -> None:
        html_text = INDEX_HTML.read_text(encoding="utf-8")
        css_text = STYLES_CSS.read_text(encoding="utf-8")
        js_text = APP_JS.read_text(encoding="utf-8")

        # 1. Template exists in index.html
        self.assertIn('id="tpl-pedal-skeuo"', html_text)

        # 2. Required SVG elements in template
        for el in (
            "svg-chassis-bevel",
            "svg-chassis-screw",
            "svg-jack-left",
            "svg-jack-right",
            "svg-switch-ring",
            "svg-switch-plunger",
            "svg-led-jewel",
        ):
            self.assertIn(el, html_text, f"Missing SVG template element: {el}")

        # 3. CSS theme classes in styles.css
        for theme in (
            "pedal-theme-smart-signal",
            "pedal-theme-silver-squeeze",
            "pedal-theme-blues-racer",
            "pedal-theme-phase-91",
            "pedal-theme-double-vision",
            "pedal-theme-lightning-mistress",
            "pedal-theme-digital-echo",
        ):
            self.assertIn(theme, css_text, f"Missing CSS theme class: {theme}")

        # 4. app.js references tpl-pedal-skeuo
        self.assertIn("tpl-pedal-skeuo", js_text)

    def test_interactive_rotary_knobs_and_tooltip(self) -> None:
        html_text = INDEX_HTML.read_text(encoding="utf-8")
        css_text = STYLES_CSS.read_text(encoding="utf-8")
        js_text = APP_JS.read_text(encoding="utf-8")

        # 1. Floating tooltip element in index.html
        self.assertIn('id="knob-floating-tooltip"', html_text)

        # 2. Rotary knob CSS classes in styles.css
        for cls in (
            "rotary-knob-group",
            "rotary-dial",
            "rotary-notch",
            "rotary-dot",
            "knob-floating-tooltip",
        ):
            self.assertIn(cls, css_text, f"Missing knob CSS class: {cls}")

        # 3. Pointer drag & wheel listeners with setPointerCapture
        self.assertIn("setPointerCapture", js_text)
        self.assertIn("releasePointerCapture", js_text)
        self.assertIn("pointerdown", js_text)
        self.assertIn("pointermove", js_text)
        self.assertIn("pointerup", js_text)

        # 4. Value clamping and queueKnobChange integration
        self.assertIn("clampInt", js_text)
        self.assertIn("queueKnobChange", js_text)

    def test_dynamic_patch_cable_routing(self) -> None:
        html_text = INDEX_HTML.read_text(encoding="utf-8")
        css_text = STYLES_CSS.read_text(encoding="utf-8")
        js_text = APP_JS.read_text(encoding="utf-8")

        # 1. #patch-cables-svg overlay in index.html
        self.assertIn('id="patch-cables-svg"', html_text)

        # 2. CSS classes in styles.css
        for cls in (
            "patch-cables-layer",
            "patch-cable-outer",
            "patch-cable-inner",
            "patch-cable-dimmed",
        ):
            self.assertIn(cls, css_text, f"Missing patch cable CSS class: {cls}")

        # 3. renderPatchCables with Bezier paths in app.js
        self.assertIn("renderPatchCables", js_text)
        self.assertIn("patch-cable-dimmed", js_text)
        self.assertIn("ResizeObserver", js_text)

    def test_photorealistic_amp_head_and_cab_stage(self) -> None:
        html_text = INDEX_HTML.read_text(encoding="utf-8")
        css_text = STYLES_CSS.read_text(encoding="utf-8")
        js_text = APP_JS.read_text(encoding="utf-8")

        # 1. #amp-stage-view exists in index.html
        self.assertIn('id="amp-stage-view"', html_text)

        # 2. Required Amp Head elements in html / css
        for cls in (
            "amp-head-enclosure",
            "amp-tolex",
            "amp-faceplate",
            "amp-model-badge",
            "amp-jewel-lamp",
            "amp-chicken-knobs",
            "amp-power-toggle",
        ):
            self.assertTrue(cls in html_text or cls in css_text, f"Missing Amp Head element: {cls}")

        # 3. Required Cabinet elements in html / css
        for cls in (
            "cab-enclosure",
            "cab-grille-cloth",
            "cab-piping",
            "cab-corners",
            "cab-knobs",
        ):
            self.assertTrue(cls in html_text or cls in css_text, f"Missing Cabinet element: {cls}")

        # 4. renderAmpStage in app.js
        self.assertIn("renderAmpStage", js_text)

        # 5. Omit ghost controls (Mono/Stereo, Standby, Presence on Amp head)
        self.assertNotIn("amp-standby", html_text.lower())
        self.assertNotIn("amp-presence", html_text.lower())

    def test_section_tabs_and_signal_flow_minimap(self) -> None:
        html_text = INDEX_HTML.read_text(encoding="utf-8")
        css_text = STYLES_CSS.read_text(encoding="utf-8")
        js_text = APP_JS.read_text(encoding="utf-8")

        # 1. #section-tabs and tab buttons in index.html
        self.assertIn('id="section-tabs"', html_text)
        for tab_id in ("tab-pedalera", "tab-pedales", "tab-amp", "tab-post-amp"):
            self.assertIn(tab_id, html_text, f"Missing section tab: {tab_id}")

        # 2. #signal-flow-minimap in index.html
        self.assertIn('id="signal-flow-minimap"', html_text)

        # 3. CSS classes in styles.css
        for cls in (
            "section-tabs",
            "section-tab",
            "signal-flow-minimap",
            "minimap-node",
            "minimap-chip",
        ):
            self.assertIn(cls, css_text, f"Missing minimap CSS class: {cls}")

        # 4. setSectionTab and dynamic filtering in app.js
        self.assertIn("setSectionTab", js_text)
        self.assertIn("renderSignalFlowMinimap", js_text)

    def test_effects_library_and_presets_drawer(self) -> None:
        html_text = INDEX_HTML.read_text(encoding="utf-8")
        css_text = STYLES_CSS.read_text(encoding="utf-8")
        js_text = APP_JS.read_text(encoding="utf-8")

        # 1. #effects-drawer, #presets-drawer, #effects-search in index.html
        self.assertIn('id="effects-drawer"', html_text)
        self.assertIn('id="presets-drawer"', html_text)
        self.assertIn('id="effects-search"', html_text)

        # 2. Toggle buttons exist
        self.assertIn('id="btn-toggle-presets"', html_text)
        self.assertIn('id="btn-toggle-effects"', html_text)

        # 3. CSS drawer classes
        for cls in (
            "drawer-panel",
            "drawer-open",
            "effects-category",
            "effects-grid",
            "effect-card-tile",
        ):
            self.assertIn(cls, css_text, f"Missing drawer CSS class: {cls}")

        # 4. Keyboard shortcuts and drawer handlers in app.js
        self.assertIn("togglePresetsDrawer", js_text)
        self.assertIn("toggleEffectsDrawer", js_text)
        self.assertIn("renderEffectsLibrary", js_text)

    def test_comprehensive_skeuomorphic_ui_integration(self) -> None:
        port = self._start_demo_server()

        # 1. Verify HTML served contains all UltraRig components
        status, headers, html_raw = self._get(port, "/")
        self.assertEqual(status, 200)
        html_text = html_raw.decode("utf-8")
        for token in (
            "signal-flow-minimap",
            "section-tabs",
            "tab-pedalera",
            "tab-pedales",
            "tab-amp",
            "tab-post-amp",
            "amp-stage-view",
            "amp-head-enclosure",
            "cab-enclosure",
            "patch-cables-svg",
            "presets-drawer",
            "effects-drawer",
            "btn-toggle-presets",
            "btn-toggle-effects",
            "knob-floating-tooltip",
        ):
            self.assertIn(token, html_text, f"Token missing from served index.html: {token}")

        # 2. Verify styles.css served contains skeuomorphic theme rules
        status_css, _, css_raw = self._get(port, "/styles.css")
        self.assertEqual(status_css, 200)
        css_text = css_raw.decode("utf-8")
        for rule in (
            "pedal-svg-skeuo",
            "rotary-knob-group",
            "patch-cables-layer",
            "amp-tolex",
            "section-tabs",
            "drawer-panel",
            "pedal-theme-smart-signal",
        ):
            self.assertIn(rule, css_text, f"Rule missing from served styles.css: {rule}")

        # 3. Verify app.js is served clean and offline
        status_js, _, js_raw = self._get(port, "/app.js")
        self.assertEqual(status_js, 200)
        js_text = js_raw.decode("utf-8")
        self.assertNotIn(".innerHTML", js_text)
        self.assertNotIn("insertAdjacentHTML", js_text)

    def test_review_findings_knob_wiring_and_drawer_sync(self) -> None:
        js_text = APP_JS.read_text(encoding="utf-8")

        # [CRITICAL-1]: queueKnobChange is explicitly defined as a function
        self.assertRegex(js_text, r"function\s+queueKnobChange\s*\(")
        self.assertIn("scheduleKnobWrite", js_text)

        # [IMPORTANT-1]: renderAll updates effects library when drawer is open
        self.assertRegex(
            js_text,
            r'renderEffectsLibrary\(\);\s*\}\s*if\s*\(!els\["modal-backup"\]',
        )

        # [IMPORTANT-2]: knob.label fallback and formatKnobDisplay usage
        self.assertIn("knob.label", js_text)
        self.assertIn("formatKnobDisplay", js_text)

        # [IMPORTANT-3]: data-cx and data-cy on rotary-knob-group, rotary-pointer-group target
        self.assertIn('group.setAttribute("data-cx"', js_text)
        self.assertIn('group.setAttribute("data-cy"', js_text)
        self.assertIn(".rotary-pointer-group", js_text)

    def test_capture_manager_markup_and_css(self) -> None:
        html_text = INDEX_HTML.read_text(encoding="utf-8")
        css_text = STYLES_CSS.read_text(encoding="utf-8")

        # 1. HTML triggers
        self.assertIn('id="btn-open-capture-mgr"', html_text)
        self.assertIn('id="btn-drawer-open-capture-mgr"', html_text)

        # 2. HTML modal structure
        self.assertIn('id="modal-capture-manager"', html_text)
        self.assertIn('data-close-modal="modal-capture-manager"', html_text)
        self.assertIn('id="tab-cap-amps"', html_text)
        self.assertIn('id="tab-cap-cabs"', html_text)
        self.assertIn('id="capture-slot-search"', html_text)
        self.assertIn('id="capture-slots-grid"', html_text)
        self.assertIn('id="capture-library-panel"', html_text)
        self.assertIn('id="capture-file-dropzone"', html_text)
        self.assertIn('id="capture-file-input"', html_text)

        # 3. CSS skeuomorphic classes
        for cls in (
            "capture-manager-modal",
            "capture-slots-grid",
            "capture-slot-card",
            "capture-slot-badge",
            "capture-slot-led",
            "capture-audition-btn",
            "capture-rename-btn",
            "capture-library-panel",
            "capture-dropzone",
        ):
            self.assertIn(cls, css_text, f"Missing Capture Manager CSS class: {cls}")

    def test_capture_manager_frontend_logic(self) -> None:
        js_text = APP_JS.read_text(encoding="utf-8")

        # 1. Functions defined
        for fn in (
            "openCaptureManager",
            "closeCaptureManager",
            "renderCaptureManagerSlots",
            "renderCaptureLibrary",
            "auditionCaptureSlot",
            "renameCaptureSlot",
            "validateAndImportCapture",
        ):
            self.assertIn(fn, js_text, f"Missing Capture Manager function: {fn}")

        # 2. REST API endpoints called
        for endpoint in (
            "/api/models/library",
            "/api/models/rename",
            "/api/models/audition",
            "/api/models/validate_import",
        ):
            self.assertIn(endpoint, js_text, f"Missing API endpoint in app.js: {endpoint}")

        # 3. Cache element IDs
        for el_id in (
            "btn-open-capture-mgr",
            "btn-drawer-open-capture-mgr",
            "modal-capture-manager",
            "tab-cap-amps",
            "tab-cap-cabs",
            "capture-slot-search",
            "capture-slots-grid",
            "capture-library-panel",
            "capture-file-dropzone",
            "capture-file-input",
        ):
            self.assertIn(f'"{el_id}"', js_text, f"Element ID {el_id} missing from cacheElements in app.js")

        # 4. Keyboard shortcuts
        self.assertIn('"modal-capture-manager"', js_text)
        self.assertRegex(
            js_text,
            r'case\s+["\']KeyC["\']|key === ["\']c["\']|key === ["\']C["\']|ev\.code === ["\']KeyC["\']',
        )


if __name__ == "__main__":
    unittest.main()

# LEKATO ME-01 Capture & IR Manager Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a safe, native 20-slot Neural Capture & Cabinet IR Manager for the LEKATO ME-01 rig, enabling slot renaming to pedal flash, 1-click live auditioning, a curated community library of Overdrives/Amps, and `.am4`/`.wav` import validation.

**Architecture:** Extend `protocol.py` with `SPACE_NAMES` (0x05) write frames and capture/IR header parsers; extend `device_service.py` with `rename_slot()`, `audition_slot()`, and bundled library extraction; expose REST endpoints in `server.py`; and build a skeuomorphic modal UI in `index.html`/`styles.css`/`app.js` with zero dependencies and strict XSS safety.

**Tech Stack:** Python 3.10+ (standard library only), WinMM MIDI, vanilla HTML5 / SVG / CSS3, vanilla ES2022 JavaScript.

**Spec:** [docs/specs/2026-11-17-me01-capture-and-ir-manager-design.md](file:///C:/Users/IT%20Tech/Documents/Lekato/ME01-Rig/docs/specs/2026-11-17-me01-capture-and-ir-manager-design.md)

## Global Constraints

- 100% offline: no CDNs, external fonts, or online asset dependencies.
- Zero usage of `.innerHTML` or `insertAdjacentHTML` in `app.js` (DOM text/element APIs only).
- Hardware safety: preserve 50ms knob coalescing, 1200ms edit suppression, factory slot lock (`P01..P40`), and `ACK_FRAME` verification on all writes.
- Slot constraints: exactly 20 AMP slots (Block 1) and 20 CAB slots (Block 5); name records exactly 14 bytes NUL-padded ASCII.
- All unit tests run under `python -W error -m unittest discover -v` with zero errors.

## Review Focus

1. **Name record length and character bounds:** Ensure slot names $> 13$ characters are safely truncated to fit the 14-byte NUL-terminated buffer without corrupting adjacent slots.
2. **Category and slot boundary guards:** Reject invalid categories (not `"amp"` or `"cab"`) and out-of-range slot indices ($< 0$ or $\ge 20$) with 400 Bad Request.
3. **Malformatted capture/WAV file upload:** Reject corrupt or truncated `.am4`/`.wav` files with informative user-facing errors rather than 500 server crashes.
4. **Live RAM audition synchronization:** Ensure auditioning a slot updates `active_preset` model and enables the block so sound is immediately outputted through the hardware.
5. **Escape key and drawer/modal collision:** Ensure pressing `Escape` closes the Capture Manager modal cleanly without misaligning other modals or drawers.

---

### Task 1: Protocol Layer Extension for Slot Renaming & Header Parsers (`protocol.py`)

**Files:**
- Modify: `me01_rig/protocol.py`
- Test: `tests/test_protocol.py`

- [ ] **Step 1: Write failing tests for slot renaming and header parsing**
  Add `test_encode_name_record_and_build_rename_slot` and `test_capture_and_wav_header_parsers` to `tests/test_protocol.py`.
- [ ] **Step 2: Run test to confirm it fails**
  Run `python -W error -m unittest tests.test_protocol -k test_encode_name_record_and_build_rename_slot -v`.
- [ ] **Step 3: Implement `encode_name_record`, `build_rename_slot`, `parse_capture_header`, and `parse_wav_header`**
  In `me01_rig/protocol.py`:
  - `encode_name_record(name: str) -> bytes`: Strips whitespace, encodes ASCII, truncates to 13 bytes, right-pads to 14 bytes with `\0`.
  - `build_rename_slot(category: str, slot: int, name: str) -> bytes`: Validates category (`"amp"`, `"cab"`), validates `0 <= slot < 20`, builds SysEx command `0x22` with `SPACE_NAMES` (0x05) and address `ADDR_AMP_NAMES + slot * 14` or `ADDR_CAB_NAMES + slot * 14`.
  - `parse_capture_header(data: bytes) -> dict[str, Any]`: Validates `AM4\0`, `AM3\0`, `AM2\0` or `CAB\0` magic; extracts model name string; calculates payload size.
  - `parse_wav_header(data: bytes) -> dict[str, Any]`: Validates RIFF/WAVE header, extracts channels, sample rate, bit depth, and sample length.
- [ ] **Step 4: Verify tests pass**
  Run `python -W error -m unittest tests.test_protocol -v`.
- [ ] **Step 5: Commit changes**
  Commit as `feat(protocol): add slot rename builder and capture/wav header validators`.

---

### Task 2: Device Service Slot Renaming, Auditioning & Library Catalog (`device_service.py`)

**Files:**
- Modify: `me01_rig/device_service.py`
- Test: `tests/test_device_service.py`

- [ ] **Step 1: Write failing tests for device service rename, audition, and library**
  Add `test_rename_slot_and_audition_in_demo_and_live` and `test_get_capture_library` to `tests/test_device_service.py`.
- [ ] **Step 2: Run test to confirm it fails**
  Run `python -W error -m unittest tests.test_device_service -k test_rename_slot_and_audition -v`.
- [ ] **Step 3: Implement `rename_slot()`, `audition_slot()`, and `get_curated_library()` in `DeviceService`**
  In `me01_rig/device_service.py`:
  - `rename_slot(category: str, slot: int, name: str) -> dict`: In demo mode, updates `self._amps` or `self._cabs`. In hardware mode, sends rename frame via `transport.transact`, checks `is_ack_frame`, re-reads 280-byte name table, updates internal state, and increments edit sequence.
  - `audition_slot(category: str, slot: int) -> dict`: Sets live RAM model for Block 1 (if amp) or Block 5 (if cab) using `build_change_model`, enables the block if bypassed via `build_toggle_block`, and returns updated state.
  - `get_curated_library() -> dict`: Returns structured catalog of verified Overdrives (`3VAVE_TS`, `4RAT_OD`, `7MS_GV2`, `6VAVE_DS`, `6 marshalldri`), Clean Amps, High Gain Amps, Bass Amps, and Cabinet IRs with tags and descriptions.
- [ ] **Step 4: Verify tests pass**
  Run `python -W error -m unittest tests.test_device_service -v`.
- [ ] **Step 5: Commit changes**
  Commit as `feat(service): implement slot renaming, auditioning, and curated tone library`.

---

### Task 3: REST API Endpoints for Capture & IR Management (`server.py`)

**Files:**
- Modify: `me01_rig/server.py`
- Test: `tests/test_server.py`

- [ ] **Step 1: Write failing tests for capture manager endpoints**
  Add `test_models_rename_audition_and_library_routes` to `tests/test_server.py`.
- [ ] **Step 2: Run test to confirm it fails**
  Run `python -W error -m unittest tests.test_server -k test_models_rename_audition_and_library_routes -v`.
- [ ] **Step 3: Implement `/api/models/rename`, `/api/models/audition`, `/api/models/library`, `/api/models/validate_import`**
  In `me01_rig/server.py`:
  - Route `POST /api/models/rename`: parses JSON `category`, `slot`, `name`; invokes `service.rename_slot()`; returns 200 with updated state or 400 on error.
  - Route `POST /api/models/audition`: parses JSON `category`, `slot`; invokes `service.audition_slot()`; returns 200 with updated state.
  - Route `GET /api/models/library`: returns curated capture library dictionary.
  - Route `POST /api/models/validate_import`: parses JSON `filename`, `content_base64`; validates with `parse_capture_header` or `parse_wav_header`; returns metadata.
- [ ] **Step 4: Verify tests pass**
  Run `python -W error -m unittest tests.test_server -v`.
- [ ] **Step 5: Commit changes**
  Commit as `feat(server): add REST endpoints for slot renaming, auditioning, and library`.

---

### Task 4: Skeuomorphic Capture & IR Manager Modal Markup & Styles (`index.html`, `styles.css`)

**Files:**
- Modify: `me01_rig/static/index.html`
- Modify: `me01_rig/static/styles.css`
- Test: `tests/test_ui_assets.py`

- [ ] **Step 1: Write failing tests for Capture Manager modal elements and CSS**
  Add `test_capture_manager_markup_and_css` to `tests/test_ui_assets.py`.
- [ ] **Step 2: Run test to confirm it fails**
  Run `python -W error -m unittest tests.test_ui_assets -k test_capture_manager_markup_and_css -v`.
- [ ] **Step 3: Add Capture Manager Modal to `index.html` and styles to `styles.css`**
  - Add `#btn-open-capture-mgr` to top bar `.top-actions` and `#btn-drawer-open-capture-mgr` in Effects Drawer.
  - Add `#modal-capture-manager` container with:
    - Modal header with title "Gestor de Capturas & IRs", close button.
    - Category tabs: `[Preamps & Overdrives (20)]` (`#tab-cap-amps`) and `[Cabinets & IRs (20)]` (`#tab-cap-cabs`).
    - Search input (`#capture-slot-search`) and Filter chips (`[Todos]`, `[Overdrive]`, `[Clean]`, `[High Gain]`, `[Bass]`).
    - 20-Slot grid container (`#capture-slots-grid`).
    - Curated Library drawer panel (`#capture-library-panel`).
    - File Dropzone (`#capture-file-dropzone`).
  - Add skeuomorphic styling in `styles.css`: slot card with metal foil trim, slot number badge, active LED, audition speaker icon button, rename pencil icon button, library drawer, and drag dropzone.
- [ ] **Step 4: Verify tests pass**
  Run `python -W error -m unittest tests.test_ui_assets -k test_capture_manager_markup_and_css -v`.
- [ ] **Step 5: Commit changes**
  Commit as `feat(ui): add capture and ir manager modal markup and skeuomorphic styles`.

---

### Task 5: Interactive Slot Management, Audition, Rename, & Import Logic (`app.js`)

**Files:**
- Modify: `me01_rig/static/app.js`
- Test: `tests/test_ui_assets.py`

- [ ] **Step 1: Write failing tests for Capture Manager frontend logic**
  Add `test_capture_manager_frontend_logic` to `tests/test_ui_assets.py`.
- [ ] **Step 2: Run test to confirm it fails**
  Run `python -W error -m unittest tests.test_ui_assets -k test_capture_manager_frontend_logic -v`.
- [ ] **Step 3: Implement Capture Manager controller in `app.js`**
  In `me01_rig/static/app.js`:
  - `openCaptureManager(category = "amp")`, `closeCaptureManager()`.
  - `renderCaptureManagerSlots()`: Renders 20 slots dynamically for selected category (`amp` or `cab`). Displays slot index, current name from `app.state.amps`/`cabs`, active indicator if currently chosen in RAM.
  - Inline rename handler: clicking rename toggles an inline input field with Save (`Enter`) and Cancel (`Escape`). Calls `POST /api/models/rename` and updates UI upon success.
  - 1-click Audition handler: clicking audition button calls `POST /api/models/audition` and marks slot active in live RAM.
  - Curated library browser: renders categorized preset captures from `/api/models/library`; selecting a preset prompts to assign to the selected slot.
  - Drag-and-drop / file input handler: reads local file as base64, sends to `POST /api/models/validate_import`, and displays validated metadata.
  - Keyboard handlers: `Escape` closes Capture Manager modal; hotkey `C` opens Capture Manager.
- [ ] **Step 4: Run node syntax check and unit test**
  Run `node --check me01_rig/static/app.js`.
  Run `python -W error -m unittest tests.test_ui_assets -v`.
- [ ] **Step 5: Commit changes**
  Commit as `feat(ui): implement interactive slot auditioning, renaming, library picker, and import logic`.

---

### Task 6: Comprehensive Verification & Live Physical ME-01 Testing

**Files:**
- Modify: `tests/test_ui_assets.py`
- Modify: `tests/test_winmm_transport.py`

- [ ] **Step 1: Write integration tests covering end-to-end capture manager flow**
  Add test covering live query, rename roundtrip, and state sync.
- [ ] **Step 2: Run full test suite across entire repository**
  Run `python -W error -m unittest discover -v` (all tests must pass with 0 errors).
- [ ] **Step 3: Test live on connected physical LEKATO ME-01**
  Verify slot querying, live auditioning, and slot renaming on connected hardware.
- [ ] **Step 4: Commit changes**
  Commit as `test(integration): verify capture manager end-to-end and on physical ME-01`.

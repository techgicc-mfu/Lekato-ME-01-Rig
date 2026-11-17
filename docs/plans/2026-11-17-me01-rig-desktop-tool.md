# ME-01 Rig Windows Desktop Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an UltraRig-inspired dark Windows desktop pedalboard editor (`ME-01 Rig`) for the LEKATO ME-01 (`ME-01_016`) over USB-MIDI (`winmm.dll`) with live 6-block chain reordering, block/model/knob editing, automatic 80-preset backups, and verified flash saves.

**Architecture:** A zero-dependency Python (`3.15.1`) backend handles Base-128 Sinco SysEx framing, `winmm.dll` (`CALLBACK_EVENT`) USB-MIDI transport, background RAM/preset sync, and JSON backup/restore via a localhost `ThreadingHTTPServer`. A standalone Edge/Chrome `--app` window renders an UltraRig-styled HTML/CSS/JS pedalboard communicating with the backend over local REST endpoints.

**Tech Stack:** Python 3.15.1 stdlib (`ctypes`, `winmm.dll`, `kernel32.dll`, `http.server`, `unittest`), vanilla HTML5 / CSS3 / ES6 JavaScript, Microsoft Edge or Google Chrome (`--app` mode).

**Spec:** [2026-11-17-me01-desktop-tool-design.md](file:///c:/Users/IT%20Tech/Documents/Lekato/ME01-Rig/docs/specs/2026-11-17-me01-desktop-tool-design.md)

## Global Constraints

- **Python runtime:** Python 3.15.1 standard library only — zero `pip install` or `npm install` packages.
- **Workspace location:** All project files live under `C:\Users\IT Tech\Documents\Lekato\ME01-Rig\`; not a Git repo, so verify each task with `python -m unittest`.
- **Wire protocol:** Base-128 LSB-first SysEx (`F0 ... F7`); outbound `encode7` emits trailing partial byte only when `bits > 0`; inbound `decode7` accepts both flush-byte and non-flush-byte payloads. Checksum is `(~sum(frame[6:-1])) & 0xFF` (body only, excluding 6-byte `00 59 cmd len24` header).
- **Write safety:** Every `0x22` command must pass the protocol allowlist (never `0x21` erase, never OTA/firmware, never indices `>= 80`), wait for its 8-byte ACK `00 59 00 01 00 00 00 ff` under the transport mutex, and never automatically overwrite flash on UI parameter edits.
- **Factory guard:** Slots `0..39` (`P01–P40`) are soft-locked by default on `Save to Slot` and batch flash restore unless `allow_factory=True` is explicitly passed.
- **CAB High Cut wire parity:** Always store and transmit raw `0..100` (`0 = 5.0 kHz`, `100 = 18.0 kHz`); never invert the wire integer.
- **WinMM SysEx reliability:** Use `CALLBACK_EVENT` (`0x50000`) with 8 × 8192-byte input `MIDIHDR` buffers and immediate `midiInAddBuffer` re-queueing after each `MHDR_DONE`.

## Review Focus

- **Malformed/foreign inbound SysEx:** Truncated frames, non-`00 59` frames (e.g., `F0 7E ... F7`), or bad checksums must fail cleanly without crashing `decode7` or poisoning the parser state (pinned in Task 1).
- **Numeric-leading real AMP/CAB names (`412 Mesa Stan`, `4x12_ MESA_Bo`, `04E_Vox 5 AC3`):** Name decoding must only strip exact `str(slot_index + 1)` when appropriate rather than greedy `/^\d+/` which would corrupt `412 Mesa Stan` (pinned in Task 1).
- **Stale queue / reply desync after timeout or extra packet:** `WinMMTransport.transact` must drain any stale queued input notifications before transmitting the next command and enforce single-mutex serialization (pinned in Task 2).
- **Polling vs active slider edits & failed flash-save handling:** Polling must respect the `1200 ms` edit-suppression window; flash-save read-back mismatch triggers at most one pre-save restore attempt and surfaces the pre-write backup file path without looping on USB error (pinned in Task 3).
- **Invalid/hostile HTTP API write inputs:** Non-permutation routing (`[0,0,1,2,3,4]`), out-of-range slots (`80`, `-1`), out-of-range knobs, and Factory writes (`0..39`) without `allow_factory=True` must return HTTP 400/403 before touching hardware (pinned in Task 4).

---

### Task 1: Fixtures, Sinco Base-128 Codec, Preset Schema, and Write Allowlist

**Files:**
- Create: `me01_rig/__init__.py`
- Create: `me01_rig/protocol.py`
- Create: `tests/__init__.py`
- Create: `tests/fixtures/me01_captured_vectors.json`
- Create: `tests/test_protocol.py`

**Interfaces:**
- Produces in `me01_rig/protocol.py`:
  - `BLOCK_IDS = (0, 1, 2, 3, 4, 5)` and `BLOCK_NAMES = ("FX", "AMP", "MOD", "DLY", "REV", "CAB")`
  - `BLOCKS: dict[int, BlockSpec]` (all FX `0..3`, AMP `0..19`, MOD `0..6`, DLY `0..4`, REV `0..5`, CAB `0..19` definitions and knob slot tables; `FX` slot `3` tagged `min_fw=17`)
  - `encode7(raw: bytes) -> bytes` and `decode7(packed: bytes) -> bytes`
  - `wrap_sysex(raw_frame: bytes) -> bytes` and `unwrap_sysex(sysex_bytes: bytes) -> bytes`
  - `build_frame(cmd: int, body: bytes) -> bytes` and `parse_frame(frame: bytes) -> ParsedFrame` (`cmd`, `body`, `space`, `address`, `size`, `data`)
  - `build_identity_query() -> bytes`, `build_read_request(space: int, addr: int, size: int) -> bytes`
  - `build_load_preset(preset_id: int) -> bytes`, `build_toggle_block(block_id: int, enabled: bool) -> bytes`, `build_change_model(block_id: int, model_id: int) -> bytes`, `build_change_knob(addr: int, value: int) -> bytes`, `build_change_routing(order: Sequence[int]) -> bytes`, `build_save_flash(preset_id: int, raw92: bytes, *, allow_factory: bool = False) -> bytes`
  - `is_ack_frame(frame: bytes) -> bool`
  - `decode_name_table(data280: bytes) -> list[str]`
  - `format_knob_display(block_id: int, model_id: int, slot: int, raw_value: int) -> str` and `bpm_to_delay_raw(bpm: float, delay_model_id: int) -> int`
  - `class PresetImage`: `.from_bytes(raw92: bytes) -> PresetImage`, `.to_bytes() -> bytes`, `.to_dict() -> dict`, `.from_dict(d: dict) -> PresetImage`
  - `class ProtocolError(ValueError)`

- [ ] **Step 1: Create `tests/fixtures/me01_captured_vectors.json` from `backups/me01-initial-backup.json`**
  Extract `identity`, `active_preset`, `amps`, `cabs`, `ram_hex`, `presets_hex[0]` (`P01`), `presets_hex[71]` (`P72`), `presets_hex[79]` (`P80`), and `captured_vectors` (`ident_raw`, `sync_raw`, `ram_raw`, `amps_raw`, `cabs_raw`) into `tests/fixtures/me01_captured_vectors.json`.

- [ ] **Step 2: Write failing tests in `tests/test_protocol.py`**
  Cover:
  - `test_encode7_decode7_and_captured_vectors`: assert `wrap_sysex(build_identity_query()) == bytes.fromhex("f0003245000000407ff7")`, and verify `unwrap_sysex` + `parse_frame` on every captured vector in `me01_captured_vectors.json` (`ident_raw`, `sync_raw`, `ram_raw`, `amps_raw`, `cabs_raw`), confirming checksums and `decode_name_table` preserve `412 Mesa Stan` / `4x12_ MESA_Bo` / `04E_Vox 5 AC3` while stripping exact slot prefixes like `1AC-SeVin` -> `AC-SeVin`, `12MESA_412` -> `MESA_412`.
  - `test_malformed_sysex_rejected`: verify truncated packets, missing `F0`/`F7`, foreign SysEx `F0 7E 7F 06 01 F7`, non-`00 59` headers, and corrupted checksum byte raise `ProtocolError`.
  - `test_preset_image_roundtrip`: parse `ram_hex` (`P72` = vol `100`, routing `[0, 1, 5, 2, 3, 4]`, states `[1,1,0,1,1,1]`, models `[2,18,0,2,1,11]`) and `P01`, mutate fields, verify `.to_bytes()` is 92 bytes and lossless round-trip matches original hex.
  - `test_write_allowlist_and_validation`: verify `build_change_routing([0,1,5,2,3,4])` emits checksum `0xD4`, rejects duplicates `[0,0,1,2,3,4]` or wrong length; `build_change_knob` rejects odd/unknown addresses (`0x15`) and clamps/rejects out-of-range values; `build_save_flash(0, raw92)` raises `ProtocolError` unless `allow_factory=True`, and rejects `preset_id=80` or `len(raw92)!=92`; `is_ack_frame(bytes.fromhex("00590001000000ff"))` returns `True`.
  - `test_knob_scales_and_rev_models`: verify `format_knob_display` for CAB L-Cut (`0` -> `"20 Hz"`, `24` -> `"87 Hz"`), CAB H-Cut (`0` -> `"5.0 kHz"`, `100` -> `"18.0 kHz"`), DLY Dual vs Dtape (`50..500 ms` vs `100..1000 ms`), `bpm_to_delay_raw`, and `REV` models `0..5` each have 5 active knobs (`Room`/`Hall` slot 4 = `"Depth"`, slot 5 = Ghost/`None`).

- [ ] **Step 3: Run `python -m unittest tests/test_protocol.py -v` to confirm failure**
  Expected: FAIL with `ModuleNotFoundError: No module named 'me01_rig'`.

- [ ] **Step 4: Implement `me01_rig/__init__.py` and `me01_rig/protocol.py`**
  Implement the Base-128 codec, frame builder/parser, name decoder (stripping leading `str(idx + 1)` only when followed by a non-digit ASCII character or letter so `412 Mesa Stan` at slot 17 is not mangled, while `12MESA_412` at slot 12 becomes `MESA_412`), 92-byte `PresetImage`, complete block/model/knob dictionary, and strict write-command builders.

- [ ] **Step 5: Run `python -m unittest tests/test_protocol.py -v` to verify pass**
  Expected: PASS (all tests green).

---

### Task 2: WinMM USB-MIDI Transport (`winmm.dll`)

**Files:**
- Create: `me01_rig/winmm_midi.py`
- Create: `tests/test_winmm_transport.py`

**Interfaces:**
- Produces in `me01_rig/winmm_midi.py`:
  - `@dataclass class MidiPortPair`: `in_id: int`, `in_name: str`, `out_id: int`, `out_name: str`, `match_score: int`
  - `enumerate_midi_ports() -> tuple[list[tuple[int, str]], list[tuple[int, str]]]`
  - `find_candidate_pairs() -> list[MidiPortPair]`
  - `class MidiTransportError(RuntimeError)`
  - `class WinMMTransport`:
    - `__init__(self, in_id: int, out_id: int, buffer_count: int = 8, buffer_size: int = 8192)`
    - `open() -> None`, `close() -> None`, `is_open: bool`
    - `transact(self, sysex_out: bytes, timeout_ms: int = 800) -> bytes` (mutex-locked, drains any stale queued `MHDR_DONE` packets before sending `sysex_out`, waits via `WaitForSingleObject` on `CALLBACK_EVENT`, re-queues `MIDIHDR` via `midiInAddBuffer`, raises `MidiTransportError` on timeout or WinMM error)
    - Context manager support (`__enter__`, `__exit__`)

- [ ] **Step 1: Write failing tests in `tests/test_winmm_transport.py`**
  Cover (using fake/stubbed WinMM API object injection for deterministic offline testing):
  - `test_port_enumeration_and_pair_matching`: pairs `USB-Midi` input/output cleanly ahead of `Microsoft GS Wavetable Synth`.
  - `test_transact_drains_stale_buffer_before_sending`: injects a stale queued SysEx reply sitting in the input ring before calling `transact`, verifies `transact` discards the stale frame and returns only the fresh reply matching the new send.
  - `test_transact_timeout_and_requeue`: verifies `MIDIHDR` buffers are always re-queued after `MHDR_DONE` even across >16 consecutive calls, and `MidiTransportError` is raised cleanly on timeout while unlocking the mutex.
  - `test_live_me01_readonly_if_connected` (skipped automatically if `USB-Midi` is not present): opens `WinMMTransport`, sends `wrap_sysex(build_identity_query())`, asserts decoded `ME-01_` reply.

- [ ] **Step 2: Run `python -m unittest tests/test_winmm_transport.py -v` to confirm failure**
  Expected: FAIL with `ModuleNotFoundError: No module named 'me01_rig.winmm_midi'`.

- [ ] **Step 3: Implement `me01_rig/winmm_midi.py`**
  Use `ctypes` against `winmm.dll` and `kernel32.dll` (`CALLBACK_EVENT = 0x50000`, `MIDIHDR` with `c_void_p` `lpData`, 8 × 8192-byte buffers, non-blocking drain before send, mutex-protected `transact`, safe `close` calling `midiInStop`/`midiInReset`/`midiInUnprepareHeader`). Allow passing an optional `winmm_lib` / `kernel32_lib` dependency in constructor for deterministic unit tests.

- [ ] **Step 4: Run `python -m unittest tests/test_winmm_transport.py -v` to verify pass**
  Expected: PASS (live test passes if ME-01 is plugged in, offline tests pass unconditionally).

---

### Task 3: Device Service (Handshake, Sync Polling, Undo, Backups, Safe Flash Save)

**Files:**
- Create: `me01_rig/device_service.py`
- Create: `tests/test_device_service.py`

**Interfaces:**
- Consumes: `me01_rig.protocol.*`, `me01_rig.winmm_midi.*`
- Produces in `me01_rig/device_service.py`:
  - `class DeviceService`:
    - `__init__(self, backup_dir: Path, fixture_path: Path, transport_factory: Callable[[int, int], Any] | None = None, poll_interval_s: float = 1.8, suppress_window_s: float = 1.2)`
    - `connect(self, in_id: int | None = None, out_id: int | None = None, auto_backup: bool = True) -> dict` (reads `0x11`, AMP names, CAB names, active preset, live RAM, all 80 slots; writes timestamped backup JSON if none created this session)
    - `enter_demo_mode(self) -> dict` (loads `tests/fixtures/me01_captured_vectors.json` as offline sandbox)
    - `disconnect(self) -> None`
    - `get_state(self) -> dict` (thread-safe snapshot: `connected`, `demo`, `identity`, `ports`, `active_preset`, `amps`, `cabs`, `ram`, `presets_summary`, `dirty_from_slot`, `undo_depth`, `last_backup_path`, `last_error`)
    - `poll_once(self) -> bool` (skips mutating cached RAM while `time.monotonic() - last_edit_ts < suppress_window_s`; refreshes `active_preset` and `ram` when not suppressed)
    - `load_preset(self, preset_id: int) -> dict` (sends `0xE0000000 + preset_id`, verifies ACK, immediately re-reads RAM `0x10000000`)
    - `refresh_ram(self) -> dict` (non-destructively reads `0x10000000` and updates state)
    - `revert_to_slot(self) -> dict` (reloads `active_preset` via `load_preset`)
    - `toggle_block(self, block_id: int, enabled: bool) -> dict`
    - `change_model(self, block_id: int, model_id: int) -> dict` (sends `0x22`, verifies ACK, immediately re-reads RAM `0x10000000`)
    - `change_knob(self, addr: int, value: int) -> dict` (marks edit suppression timestamp, sends `0x22`, verifies ACK)
    - `change_routing(self, order: list[int]) -> dict`
    - `apply_preset_to_ram(self, raw92: bytes, push_undo: bool = True) -> dict` (diffs against current RAM and sends `0x22` routing/toggles/models/knobs/volume, re-reads RAM)
    - `undo(self) -> dict`
    - `save_flash_slot(self, preset_id: int, allow_factory: bool = False) -> dict` (pre-reads slot + writes pre-write backup file, sends `0x22` flash save, waits up to 3000 ms for ACK, reads back `preset_id * 92` and checks byte equality; if mismatched over working transport, executes single pre-save restore write and raises error with backup path)
    - `export_backup(self, path: Path | None = None) -> dict`
    - `audition_backup_preset(self, backup_data: dict, preset_id: int) -> dict`
    - `batch_restore_backup(self, backup_data: dict, slot_ids: list[int], allow_factory: bool = False) -> dict`

- [ ] **Step 1: Write failing tests in `tests/test_device_service.py`**
  Use an in-memory `FakeTransport` implementing the exact `0x11`/`0x23`/`0x22` byte protocol backed by 80 flash slots + live RAM + AMP/CAB tables from `me01_captured_vectors.json`:
  - `test_connect_handshake_and_auto_backup`: verifies `0x11` + AMP/CAB tables + 80 presets read, and auto-backup JSON written in temp dir.
  - `test_poll_respects_edit_suppression_window`: simulates local `change_knob`, verifies `poll_once()` within `suppress_window_s` does NOT overwrite local state with stale fake RAM, and DOES sync once window expires.
  - `test_change_model_rereads_ram_and_undo_restores`: verifies `change_model` triggers a fresh RAM read and `undo()` replays the prior 92 bytes cleanly.
  - `test_flash_save_readback_mismatch_triggers_single_restore`: injects a corrupted read-back on first write in `FakeTransport`, verifies pre-write backup file was saved, exactly one restore write was attempted (no infinite loop), and an error citing the backup path is raised.
  - `test_batch_restore_respects_factory_lock_and_audition`: verifies `batch_restore_backup` rejects `0..39` unless `allow_factory=True`, and `audition_backup_preset` updates live RAM without modifying flash slots.

- [ ] **Step 2: Run `python -m unittest tests/test_device_service.py -v` to confirm failure**
  Expected: FAIL with `ModuleNotFoundError: No module named 'me01_rig.device_service'`.

- [ ] **Step 3: Implement `me01_rig/device_service.py`**
  Implement `DeviceService` with daemon polling thread, undo stack (bounded e.g. 30 snapshots), atomic backup JSON writes, and strict pre-read/read-back flash-save state machine. (In Demo mode, all edits operate cleanly on the in-memory `FakeState` so the user can explore the full UI even unplugged.)

- [ ] **Step 4: Run `python -m unittest tests/test_device_service.py -v` to verify pass**
  Expected: PASS.

---

### Task 4: Localhost HTTP JSON Server & Launcher

**Files:**
- Create: `me01_rig/server.py`
- Create: `launch.py`
- Create: `ME01-Rig.bat`
- Create: `tests/test_server.py`

**Interfaces:**
- Consumes: `me01_rig.device_service.DeviceService`
- Produces in `me01_rig/server.py`:
  - `create_server(service: DeviceService, host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer`
  - All JSON routes returning `200` JSON on success, `400` / `403` / `409` JSON `{"error": "..."}` on validation/factory-lock/transport errors:
    - `GET /api/state`, `GET /api/ports`, `GET /api/presets`
    - `POST /api/connect`, `POST /api/disconnect`, `POST /api/demo`
    - `POST /api/preset/load` (`{"preset_id": int}`)
    - `POST /api/ram/refresh`, `POST /api/ram/revert`, `POST /api/ram/undo`
    - `POST /api/ram/toggle` (`{"block_id": int, "enabled": bool}`)
    - `POST /api/ram/model` (`{"block_id": int, "model_id": int}`)
    - `POST /api/ram/knob` (`{"addr": int, "value": int}`)
    - `POST /api/ram/order` (`{"order": list[int]}`)
    - `POST /api/flash/save` (`{"preset_id": int, "allow_factory": bool}`)
    - `GET /api/backup/export`, `POST /api/backup/audition`, `POST /api/backup/restore`
    - `POST /api/shutdown`
- Produces in `launch.py`:
  - `find_app_browser() -> Path | None` (checks Edge then Chrome installed paths)
  - `main()` starting `create_server`, launching browser `--app=http://127.0.0.1:<port>/ --user-data-dir=...`, and shutting down cleanly when browser exits or on Ctrl+C.

- [ ] **Step 1: Write failing tests in `tests/test_server.py`**
  Spin up `create_server` on `127.0.0.1:0` with `DeviceService` in Demo mode (plus `FakeTransport` mode):
  - `test_get_state_and_presets`: verifies `GET /api/state` and `GET /api/presets` return 80 presets, 20 amps, 20 cabs, and valid active RAM dict.
  - `test_invalid_inputs_return_400_403`: sends `POST /api/ram/order` with `{"order": [0,0,1,2,3,4]}` -> HTTP 400; `POST /api/ram/knob` with `{"addr": 21, "value": 50}` or `{"addr": 32, "value": 150}` -> HTTP 400; `POST /api/flash/save` with `{"preset_id": 5, "allow_factory": false}` -> HTTP 403; `POST /api/flash/save` with `{"preset_id": 80}` -> HTTP 400.
  - `test_valid_ram_edits_and_flash_save`: verifies toggle, model change, knob update, order change, undo, export backup JSON, and `P80` (`preset_id=79`) flash save return `200` and update state consistently.

- [ ] **Step 2: Run `python -m unittest tests/test_server.py -v` to confirm failure**
  Expected: FAIL with `ModuleNotFoundError: No module named 'me01_rig.server'`.

- [ ] **Step 3: Implement `me01_rig/server.py`, `launch.py`, and `ME01-Rig.bat`**
  Implement strict JSON body parsing, validation error mapping (`ProtocolError` -> 400, factory-lock error -> 403, `MidiTransportError` -> 502), static file serving from `me01_rig/static/`, and clean Edge/Chrome `--app` launcher in `launch.py` + double-clickable `ME01-Rig.bat`.

- [ ] **Step 4: Run `python -m unittest tests/test_server.py -v` to verify pass**
  Expected: PASS.

---

### Task 5: UltraRig-Inspired Dark Pedalboard Web UI

**Files:**
- Create: `me01_rig/static/index.html`
- Create: `me01_rig/static/styles.css`
- Create: `me01_rig/static/app.js`
- Create: `tests/test_ui_assets.py`

**Interfaces:**
- Consumes: Task 4 REST API endpoints (`/api/state`, `/api/presets`, `/api/connect`, `/api/demo`, `/api/preset/load`, `/api/ram/*`, `/api/flash/save`, `/api/backup/*`, `/api/ports`)
- Produces: Complete single-page UltraRig-styled pedalboard app in `me01_rig/static/`.

- [ ] **Step 1: Write failing asset/smoke checks in `tests/test_ui_assets.py`**
  - Verify `index.html`, `styles.css`, `app.js` exist under `me01_rig/static/` and `GET /` serves `index.html` (`200`, `text/html`).
  - Run `node --check me01_rig/static/app.js` (if `node` available) and verify all expected UI control hooks (`Earlier`, `Later`, `Save to Slot`, `Refresh RAM`, `Revert`, `Undo`, `Tap Tempo`, `Backup`) and endpoint paths match `server.py`.

- [ ] **Step 2: Implement `me01_rig/static/index.html`, `styles.css`, and `app.js`**
  - **Top bar:** Brand `ME-01 RIG` + connection badge (`ME-01_016` / `Demo Mode` + Port selector + Connect/Reconnect), active slot badge (`P72`), Patch Volume slider (`0–100`), `Refresh RAM`, `Undo`, `Revert to Slot`, `Backup / Restore`, and `Save to Slot`.
  - **Left Preset Sidebar:** `P01–P40 Factory` (with lock badge + `Unlock Factory Slots` checkbox) and `P41–P80 User`, click to load preset (`Load Preset`), showing summary icons/amp badge per slot and unsaved-changes (`Modified`) indicator when live RAM differs from the active slot.
  - **Main Pedalboard (`IN → [6 Stomp Cards] → OUT`):**
    - Color-coded UltraRig-style stomp pedals (`FX`, `AMP`, `MOD`, `DLY`, `REV`, `CAB`) showing active model name, mini knob dots, footswitch LED + click-to-bypass button, and selected highlight.
    - Action bar below chain (mirroring the screenshot layout): `< Earlier`, `Later >`, drag-and-drop card reordering, and clear notice that ME-01 hardware runs 6 serial blocks (`+ parallel` unsupported by stock firmware).
  - **Selected Block Inspector:** Model dropdown (populated with live 20 AMP/CAB names from pedal; `AI Gate MS` marked `(V17+)`), smooth range sliders + direct numeric input + physical unit display (`Hz`, `kHz`, `ms` / `BPM` + `Tap Tempo` button on `DLY`, clear note on `CAB High Cut` raw `0–100` vs `5.0–18.0 kHz` display), coalesced 50 ms throttled writes during rapid slider drags, and `1200 ms` local-edit poll suppression.
  - **Backup / Restore & Save Modals:** Confirmation dialog for `Save to Slot` (pre-selecting active slot if `P41–P80`, or prompting User slot if `P01–P40` is locked), JSON file export download + file picker restore supporting both single-preset **Audition in RAM** and **Batch Flash Restore** with per-slot progress.

- [ ] **Step 3: Run full test suite & headless Edge UI smoke check**
  - Run `python -m unittest discover -s tests -v`.
  - Run `node --check me01_rig/static/app.js`.
  - Start server briefly in live connected mode (read-only UI verification) or Demo mode, fetch `/`, `/styles.css`, `/app.js`, `/api/state`, `/api/presets` and verify zero errors.

---

## Self-Review Checklist
- Spec coverage: Every requirement in `docs/specs/2026-11-17-me01-desktop-tool-design.md` (§1–§5) maps cleanly to Tasks 1–5 (WinMM `CALLBACK_EVENT`, Base-128 `00 59`, all 6 block/model/knob definitions including 5-knob REV Room/Hall, `1200 ms` suppression, factory soft-lock, single-read-back flash safety, Backup Audition + Batch Restore, Demo mode, Edge/Chrome `--app` launcher).
- No placeholders, no `pytest` mismatch (uses built-in `unittest`), exact method signatures shared across Tasks 1–5.

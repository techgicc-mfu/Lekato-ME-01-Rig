# Design: ME-01 Rig — Windows Desktop Editor for LEKATO ME-01

**Date:** 2026-11-17  
**Target Hardware:** LEKATO ME-01 (verified live as `ME-01_016` over `USB\VID_4C4A&PID_C755&MI_03`, WinMM `USB-Midi`)  
**Status:** Ready for user approval

---

## 1. Intent & Why

The official M-EFCS desktop app is closed-source, and UltraRig's custom firmware (`m571_v1_app.bin`) cannot run on the LEKATO ME-01. However, live probing of the connected `ME-01_016` pedal confirmed that its factory firmware exposes the full 92-byte Sinco/Blackbox USB-MIDI SysEx protocol — including **reorderable 6-block signal chains**, live block toggles, model selection across all 6 modules, real-time parameter control, 20 AMP/20 CAB slot names read from flash, and 80 preset slots (`P01–P80`).

**ME-01 Rig** gives you a fast, transparent, UltraRig-inspired dark Windows desktop pedalboard editor built directly around everything the ME-01 firmware actually supports, with safe automatic preset backups before any permanent write.

---

## 2. Goals, Non-Goals, and Anti-Goals

### Goals
- **UltraRig-inspired visual pedalboard on Windows:** Dark studio palette (`#0d0e10` / `#15171a` / `#1b1e22`, cyan/gold accents), color-coded stomp cards for `FX`, `AMP`, `MOD`, `DLY`, `REV`, and `CAB`, `< Earlier` / `Later >` and drag-and-drop chain reordering, click-to-toggle bypass, and clean parameter knobs/sliders with real physical unit readouts (Hz, kHz, ms, BPM).
- **Zero-install runtime:** Run natively with the PC's installed Python (`3.15.1`) standard library (`ctypes` + `winmm.dll` + `http.server`) and Microsoft Edge or Google Chrome in standalone `--app` window mode (no browser tabs or address bar, no `pip install`, no `npm install`).
- **Full preset & hardware sync:**
  - Read device identity (`0x11`), 20 AMP names (`0x90000000`), 20 CAB names (`0x80000000`), active preset ID (`0x20000000`), live RAM (`0x10000000`), and all 80 flash presets (`0x00000000 + idx * 92`).
  - Poll active preset + RAM safely on a timer (e.g., 1.5–2.5 s) so front-panel hardware edits sync back into the UI without clobbering sliders currently being dragged.
- **Safety-first writes & backups:**
  - Automatically capture a checksummed JSON backup of all 80 flash presets on first connection (baseline already captured at `backups/me01-initial-backup.json`).
  - Support live RAM edits (chain order, block bypass, model selection, knobs, patch volume, preset switching).
  - Soft-lock Factory slots `P01–P40` (`0..39`) by default so saves target User slots `P41–P80` (`40..79`), with an explicit **"Unlock Factory Slots"** toggle if you deliberately want to overwrite `P01–P40` *(builder call)*.
  - Gate permanent flash writes (`Save to Slot`) behind an explicit confirmation dialog and verify every flash write via immediate 92-byte read-back.
  - Enforce a strict backend allowlist so arbitrary memory addresses, erase (`0x21`), and firmware/OTA commands can never be transmitted.
- **Backup, Restore & Demo mode:**
  - Single-preset load from backup JSON into live RAM (non-permanent audition), plus optional batch restore of User slots (or unlocked slots) to flash with per-slot read-back verification *(builder call)*.
  - Demo/Inspector mode when no ME-01 is plugged in, seeded from the captured `ME-01_016` snapshot.

### Non-Goals (v1)
- **No parallel routing (`+ parallel`) or >6 simultaneous blocks:** The ME-01 hardware firmware runs a 6-slot serial chain (`FX`, `AMP`, `MOD`, `DLY`, `REV`, `CAB`).
- **No NAM/AM3/AM4 neural capture conversion or `.wav` IR flashing in v1:** Kept out of v1 to stay focused and minimize flash-write risk (can be added as a separate phase later if desired).
- **No firmware flashing / OTA updates.**
- **No BLE GATT transport in v1:** Uses USB-MIDI (`winmm.dll`) only.

### Anti-Goals
- Never overwrite flash preset slots silently or automatically on knob movement.
- Never allow raw unvalidated SysEx frames from the web UI to reach `winmm.dll`.
- Never confuse display inversion with wire values (specifically CAB High Cut: raw `0–100` on wire, `0 = 5.0 kHz` to `100 = 18.0 kHz`).

---

## 3. Approaches Considered

1. **Chosen — Python (`winmm.dll` via `ctypes`) backend + Edge/Chrome `--app` dark HTML/JS UI**
   - *How:* Local Python `ThreadingHTTPServer` bound to `127.0.0.1` handles serialized WinMM MIDI I/O and serves static HTML/CSS/JS; launcher opens `msedge.exe --app=...` (falling back to `chrome.exe --app=...`) with a dedicated `--user-data-dir` so it runs as a standalone desktop window and exits cleanly when closed.
   - *Trade-offs:* Zero third-party installs, <0.2s WinMM 80-preset read speed verified on this machine, UltraRig-grade SVG/CSS pedalboard polish, easy to extend into a pure WebMIDI build later. Requires Edge or Chrome (both are present on this PC).
2. **Pure Python + `tkinter` native GUI**
   - *Trade-offs:* No browser window needed and easy to freeze into an `.exe`, but `tkinter` widgets look dated compared to UltraRig's pedalboard layout and drag-and-drop chain cards.
3. **Node.js / Electron desktop app**
   - *Trade-offs:* Heavy `node_modules` footprint (~200 MB+) and extra native MIDI setup for no practical benefit over Python + `winmm.dll`.

---

## 4. Constraints & Verified Hardware Protocol

All `0x11` identity, `0x23` read, and reversible `0x22` RAM + Flash write behaviors below were **verified live** against the connected **`ME-01_016`** pedal over Windows `USB-Midi` (`USB\VID_4C4A&PID_C755&MI_03`):

### 4.1 WinMM Transport (`winmm.dll`)
- Enumerate input/output ports via `midiInGetNumDevs`/`midiInGetDevCapsW` and `midiOutGetNumDevs`/`midiOutGetDevCapsW`; auto-select matching `USB-Midi` ports (with manual port selector in UI if multiple exist).
- Use **`CALLBACK_EVENT` (`0x50000`)** with multiple `MIDIHDR` input buffers (e.g., 8 × 8192 bytes) and **immediately re-queue each buffer with `midiInAddBuffer` after reading `MHDR_DONE`**. (Without re-queuing, WinMM stops receiving after the initial buffer pool fills; with re-queuing, all 80 presets read in `0.12s`.)
- Serialize all outbound SysEx request/response transactions behind a single mutex/lock so polling never interleaves with UI commands or handshake reads.

### 4.2 Wire Framing & Base-128 Codec
- **USB SysEx wrapping:** `F0 <encode7(frame)> F7` (no MIDI manufacturer ID), continuous LSB-first 8→7 bit stream.
  - **Outbound (`encode7`):** Emit final partial byte only when `bits > 0` (e.g., 7 raw bytes for `0x11` encode to 8 payload bytes inside `F0..F7`; verified live on `ME-01_016`).
  - **Inbound (`decode7`):** Unpack 7-bit stream cleanly whether or not the pedal appends a trailing zero flush byte (`n + n // 7 + 1` bytes).
- **Raw frame layout:**
  - `0..1`: `0x00, 0x59` (Sinco magic header)
  - `2`: `cmd` (`0x11` identity query, `0x23` memory read, `0x22` memory write, `0x00` ACK reply)
  - `3..5`: 24-bit little-endian `body_len`
  - `6 .. 6+body_len-1`: `body`
  - `6+body_len`: checksum `(~sum(body)) & 0xFF` (covers `body` only, NOT the 6-byte header)
- **Memory-access payload (`0x22` / `0x23`):**
  - `space` (1 byte): `0x04` = preset/RAM/control, `0x05` = AMP/CAB name strings
  - `address` (4 bytes LE)
  - `size` (3 bytes LE)
  - `data` (`size` bytes on read replies and writes; empty on read requests)
  - Total header before `data` = **14 bytes** (`6 + 1 + 4 + 3`).

### 4.3 Verified Memory Map, Commands, & ACK Behavior
- **Read (`0x23`) + Identity (`0x11`) — verified live on `ME-01_016`:**
  - `0x11` (empty body): returns `ME-01_016` (27 bytes ASCII + NUL padding).
  - `space=0x04, addr=0x20000000, size=4`: active preset ID (`0..79`) in `data[0]`.
  - `space=0x04, addr=0x10000000, size=92`: live RAM 92-byte preset image.
  - `space=0x04, addr=index*92, size=92`: flash preset slot `0..79` (`P01..P80`). Indices `>= 80` return out-of-bounds data and are rejected by client validation.
  - `space=0x05, addr=0x90000000, size=280`: 20 × 14-byte NUL-padded AMP names.
  - `space=0x05, addr=0x80000000, size=280`: 20 × 14-byte NUL-padded CAB names.
- **Write (`0x22`, `space=0x04`) — allowlisted commands only (verified live on `ME-01_016`):**
  - Both RAM writes and Flash writes **emit an identical 8-byte decoded (12-byte USB) ACK `00 59 00 01 00 00 00 ff`** and **Flash writes work directly without `0x21` erase** (`0x21` remains strictly forbidden on the allowlist). Every `0x22` call waits for and consumes its single ACK under the transport lock before releasing the mutex.
  - **Load Preset:** `addr = 0xE0000000 + preset_id` (`0..79`), `size = 1`, `data = [0x01]` -> wait for ACK, then immediately re-read live RAM (`0x10000000`) *(builder call)*.
  - **Toggle Block:** `addr = 0x10000000 + 0x08 + block_id` (`0..5`), `size = 1`, `data = [0 or 1]` -> wait for ACK.
  - **Change Model:** `addr = 0x10000000 + 0x0E + block_id` (`0..5`), `size = 1`, `data = [model_id]` -> wait for ACK, then immediately re-read live RAM (`0x10000000`) so UI mirrors whether firmware preserves or resets knob bytes *(builder call)*.
  - **Change Knob:** `addr = 0x10000000 + addr` (`0x00` for Patch Vol, or `0x14..0x5A` even offsets), `size = 2`, `data = [val, 0x00]` (`val` clamped `0..100`) -> wait for ACK.
  - **Change Routing:** `addr = 0x10000002`, `size = 6`, `data = [b0..b5]` (must be a strict permutation of `0..5`) -> wait for ACK.
  - **Save Preset to Flash:** `addr = preset_id * 92` (`0..79`, Factory `0..39` rejected unless `allow_factory=True`), `size = 92`, `data = 92-byte preset image`.
    - **Safe Flash-Save & Recovery State Machine *(builder call)*:**
      1. Read current 92 bytes of target slot `preset_id * 92` and save to an in-memory pre-write snapshot + `backups/` pre-write file.
      2. Send `0x22` flash write and wait up to `3000 ms` for the 8-byte ACK (`len == 8 and frame[3] == 0x01 and frame[7] == 0xFF`).
      3. Immediately read back `preset_id * 92` (`92` bytes) and compare byte-for-byte against the intended image.
      4. If read-back succeeds with mismatched bytes, attempt one clean restore write of the pre-write snapshot and re-verify; if transport fails/times out or restore also fails, do not retry in a loop — surface the failure and the pre-write backup file path clearly to the user.

### 4.4 92-Byte Preset Layout & Model Dictionary
- `0x00..0x01`: Patch Volume (`u16 LE`, `0..100`)
- `0x02..0x07`: Signal chain order (6 `u8` block IDs, permutation of `0..5`)
- `0x08..0x0D`: Block states (`u8`, `0=OFF, 1=ON`, indexed by block ID `0..5`)
- `0x0E..0x13`: Model IDs (`u8`, indexed by block ID `0..5`)
- `0x14..0x5B`: 6 blocks × 6 knob slots × `u16 LE` (`0..100`), base addresses `FX=0x14`, `AMP=0x20`, `MOD=0x2C`, `DLY=0x38`, `REV=0x44`, `CAB=0x50`. Unused slots are Ghost slots (`00 00`, hidden in UI).
- **Block & Model tables:**
  - `0` **FX:** `0: Noise Gate++` (`Gate`), `1: Boost` (`Gate, Gain`), `2: Compress` (`Gate, Sustain, Attack, Level`), plus `3: AI Gate MS` (`Gate, Bias`) labeled `(V17+)` (`ME-01_016` factory/user presets use `0..2`).
  - `1` **AMP:** `0..19` (names loaded live from `0x90000000`), knobs: `Gain, Level, Bass, Mid, Treble`.
  - `2` **MOD:** `0: Chorus` (`Speed, Depth, Mix`), `1: Phaser` (`Speed, Midcut, Reso, Feedback`), `2: Tremolo` (`Speed, Depth, Level`), `3: Flanger` (`Speed, Depth, Feedback, Mix`), `4: Vibrato` (`Speed, Depth`), `5: Univibe` (`Speed, Depth, Mix`), `6: Autofilter` (`Speed, Min, Max, Mix, Feedback`).
  - `3` **DLY:** `0: Analog` (`Time, Feedback, Mix, Phaser, Pitch`), `1: Duck` (`Time, Feedback, Mix, Unpack, Speed, Depth`), `2: Dtape` (`Time, Feedback, Mix, Grit, Speed, Depth`), `3: Dual` (`Time, Feedback, Mix, T-Mode, Speed, Depth`), `4: Lofi` (`Time, Feedback, Mix, Grit, Speed, Depth`). Time scale: `50–500 ms` on Dual, `100–1000 ms` on others, plus a UI **Tap Tempo** button computing BPM → ms → `0–100`.
  - `4` **REV:** *(5 active knobs `0..4`, slot 5 at `0x4E` is Ghost — verified against live `ME-01_016` presets)*
    - `0: Room` (`Decay, Mix, High Pass, Low Pass, Depth`)
    - `1: Hall` (`Decay, Mix, High Pass, Low Pass, Depth`)
    - `2: Swell` (`Decay, Mix, High Pass, Low Pass, Rise-T`)
    - `3: Spring` (`Decay, Mix, High Pass, Low Pass, Combs`)
    - `4: Shimmer` (`Decay, Mix, Tone, Pitch, Amount`)
    - `5: Cloud` (`Decay, Mix, High Pass, Low Pass, Diffusion`)
  - `5` **CAB:** `0..19` (names loaded live from `0x80000000`), knobs: `Level`, `Low Cut` (`20 + raw*2.8` Hz), `High Cut` (`5.0 + raw*0.13` kHz; UI displays kHz and raw `0..100` clearly without altering wire semantics).

---

## 5. UI Controls, Sync & Architecture

### 5.1 Clear Separation of Refresh / Revert / Undo *(builder call)*
- **Refresh RAM:** Immediately re-reads `0x10000000` (non-destructive; mirrors current pedal RAM).
- **Revert to Slot:** Prompts confirmation, sends `Load Preset` (`0xE0000000 + active_id`), and re-reads RAM to discard unsaved edits back to the saved flash preset.
- **Undo (Local):** Maintains an in-memory history of recent 92-byte RAM snapshots and replays the target snapshot back to RAM via `0x22` writes (routing + states + models + changed knobs + volume).

### 5.2 Backup & Restore Flows *(builder call)*
- **Export Backup JSON:** Captures `identity`, `active_preset`, `amps`, `cabs`, `ram_hex`, and all 80 `presets_hex` (baseline already captured at `C:\Users\IT Tech\Documents\Lekato\ME01-Rig\backups\me01-initial-backup.json`).
- **Restore from Backup JSON:**
  - *Single Preset Audition:* Pick any slot (`P01–P80`) from a backup JSON and apply its 92 bytes into live RAM only (safe, non-permanent).
  - *Batch Flash Restore:* Restore User slots `P41–P80` (or `P01–P80` only if Factory Unlock is explicitly enabled) slot-by-slot with progress reporting, stopping on first verification mismatch, using the same read-back verification state machine.

### 5.3 File Layout
Location: `c:\Users\IT Tech\Documents\Lekato\ME01-Rig\`

- `me01_rig/protocol.py` — Pure logic: Base-128 `encode7`/`decode7`, Sinco frame builder/parser & checksum validation, `PresetImage` 92-byte parser/serializer, model & knob dictionary, unit formatters, and write-command allowlist/validators.
- `me01_rig/winmm_midi.py` — Windows `winmm.dll` (`ctypes`) device discovery and `CALLBACK_EVENT` SysEx transport with continuous buffer re-queueing and thread-safe request/reply serialization.
- `me01_rig/device_service.py` — Stateful coordinator: connect/handshake (`0x11`, AMP names, CAB names, initial auto-backup of all 80 slots), active preset + RAM polling with edit-suppression window (`1200 ms`), debounced knob writes, flash save with read-back verification, and JSON backup/restore helpers.
- `me01_rig/server.py` — `ThreadingHTTPServer` on `127.0.0.1` exposing REST JSON endpoints (`/api/status`, `/api/connect`, `/api/state`, `/api/presets`, `/api/preset/load`, `/api/ram/refresh`, `/api/ram/revert`, `/api/ram/toggle`, `/api/ram/model`, `/api/ram/knob`, `/api/ram/order`, `/api/ram/apply`, `/api/flash/save`, `/api/backup/export`, `/api/backup/audition`, `/api/backup/restore`, `/api/shutdown`) and serving static assets.
- `me01_rig/static/` (`index.html`, `styles.css`, `app.js`) — UltraRig-inspired dark single-page pedalboard UI (top bar, interactive 6-block pedal chain with drag + `< Earlier` / `Later >`, parameter knobs/sliders with physical unit readouts + Tap Tempo, 80-slot Factory/User bank sidebar, Refresh / Revert / Undo, and Backup/Restore modal).
- `launch.py` & `ME01-Rig.bat` — Starts local server on an ephemeral port, launches Edge/Chrome `--app` with an isolated profile directory under `%LOCALAPPDATA%\ME01-Rig\browser-profile`, and shuts down cleanly when the browser process exits (plus clean Ctrl+C / `/api/shutdown`).
- `tests/test_protocol.py` & `tests/test_device_service.py` — Unit tests using captured `ME-01_016` byte vectors (`tests/fixtures/me01_captured_vectors.json`, extracted from `backups/me01-initial-backup.json`) covering Base-128 round-trip, checksums, 92-byte encode/decode, permutation/allowlist safety checks, and mocked transport flash-save verification/rollback behavior.

---

## 6. Left to the Builder

- Exact CSS visual styling, knob/slider interaction details (wheel/drag/double-click reset), and toast/status bar ergonomics.
- Exact throttling/debounce timing on rapid knob drags (e.g., 40–60 ms coalescing per parameter address so USB-MIDI isn't flooded while dragging).
- Port selection fallback UI if a user connects a second MIDI device alongside `USB-Midi`.

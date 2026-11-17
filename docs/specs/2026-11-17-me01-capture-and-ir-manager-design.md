# Design Spec: LEKATO ME-01 Capture & IR Manager

**Date:** 2026-11-17  
**Author:** Antigravity  
**Target Hardware:** LEKATO ME-01 (`ME-01_016`) USB-MIDI  
**Workspace:** `C:\Users\IT Tech\Documents\Lekato\ME01-Rig`  

---

## 1. Executive Summary & Problem Statement

The connected physical **LEKATO ME-01** multi-effects pedal features a 6-block serial DSP engine where **Block 1 (AMP)** hosts Neural Overdrive and Amplifier model captures, and **Block 5 (CAB)** hosts Cabinet Impulse Responses (IRs). 

Reverse engineering and hardware verification of the live unit have confirmed:
1. The ME-01 pedal features **20 AMP slots** (Block 1) and **20 CAB slots** (Block 5).
2. Live slot inspection revealed that Overdrive captures already run inside Block 1 (e.g. Slot 05: `6 marshalldri`, Slot 14: `4OD-MarVicto`). Because blocks can be freely placed in any order in the serial chain (e.g. `AMP -> FX -> MOD -> DLY -> REV -> CAB`), Block 1 can serve as a dedicated Overdrive pedal at the very beginning of the rig.
3. The names of all 20 AMP slots and 20 CAB slots are stored in device flash memory in `SPACE_NAMES` (`0x05`) at addresses `ADDR_AMP_NAMES` (`0x90000000`) and `ADDR_CAB_NAMES` (`0x80000000`), formatted as 20 records of 14 bytes each (total 280 bytes).
4. Writing 14-byte name records to `SPACE_NAMES` via SysEx command `0x22` succeeds and is acknowledged immediately with `ACK_FRAME` (`00 59 00 01 00 00 00 ff`).
5. Official binary archives (`tankMini_am4_ampCab.bin`) contain verified 8 KiB `AM4` GRU neural network captures (Tube Screamer `3VAVE_TS`, RAT `4RAT_OD`, Marshall Guv'nor `7MS_GV2`, DS-1 `6VAVE_DS`, JC-120, JCM900, Mesa, Friedman) and 4 KiB `CAB` IRs.

This specification outlines the architecture for a **Capture & IR Manager** integrated into ME-01 Rig:
- Visual 20-slot manager for AMP captures and CAB IRs.
- Instant 1-click slot auditioning in live RAM.
- Safe slot renaming with read-back verification directly to hardware flash.
- Curated community library of Overdrive and Amp captures extracted from native models.
- Support for parsing and validating `.am3`, `.am4`, `.bin`, and `.wav` IR files.
- Skeuomorphic UltraRig modal interface (`#modal-capture-manager`).

---

## 2. Technical Architecture

### 2.1 Protocol Layer (`protocol.py`)
- **Name Record Encoding**:
  ```python
  def encode_name_record(name: str) -> bytes:
      clean = name.strip().encode("ascii", errors="replace")[:13]
      return clean.ljust(14, b"\x00")
  ```
- **Slot Renaming Frame**:
  ```python
  def build_rename_slot(category: str, slot: int, name: str) -> bytes:
      # category in ("amp", "cab"), slot in 0..19
      base_addr = ADDR_AMP_NAMES if category == "amp" else ADDR_CAB_NAMES
      addr = base_addr + slot * 14
      data = encode_name_record(name)
      body = bytes([SPACE_NAMES]) + addr.to_bytes(4, "little") + len(data).to_bytes(3, "little") + data
      return build_frame(CMD_WRITE, body)
  ```
- **Capture File Validation**:
  - `parse_am4_header(data: bytes) -> dict`: verifies `AM4\0` or `AM3\0` or `AM2\0` magic, extracts name (14 bytes), model parameters, and tensor size.
  - `parse_wav_ir_header(data: bytes) -> dict`: verifies `RIFF...WAVEfmt ` header, extracts sample rate (44.1k/48k), bit depth (16/24/32 float), channels (mono/stereo), and sample count.

### 2.2 Device Service (`device_service.py`)
- **`rename_slot(category: str, slot: int, new_name: str) -> dict`**:
  - Validates `category` (`amp` or `cab`), `slot` (`0..19`), and `new_name`.
  - In demo mode: updates in-memory `_amps` or `_cabs`.
  - In connected hardware mode: wraps in lock, sends SysEx write frame to `SPACE_NAMES`, asserts `is_ack_frame`, re-reads the 280-byte name table from hardware, updates `_amps`/`_cabs`, updates `_edit_seq`, and emits updated state.
- **`get_curated_library() -> dict`**:
  - Returns categorized metadata for bundled captures:
    - Overdrives / Distortions: Tube Screamer (`3VAVE_TS`), RAT (`4RAT_OD`), Guv'nor (`7MS_GV2`), Distortion (`6VAVE_DS`), Marshall Drive (`6 marshalldri`).
    - Clean Amps: Roland JC-120 (`1J120_CL`), JCM900 Clean (`2J900_CL`), Fender Twin (`1UWE-Twins`), Vox AC30 (`2UK-C30Normal`).
    - Crunch & Rock: Marshall JCM800 (`Marshall 800`), Victory Mars (`4Victor Mars`), Engl Savage (`7ENGL SAVAGE`).
    - High Gain: Diezel VH4 (`15CT-Gas V4H`), EVH 5150 (`9EVH 5150`), Fortin Cali (`10Fortin Cali`), Soldano (`NDSP Soldano`), Friedman Pink (`Friedman Pink`).
    - Bass Amps: Aguilar DB750 (`16AgDb750_BS`), Ampeg SVT (`17ApSVT_BS`), Darkglass (`19DgXu_BS`), Markbass (`20MarkLm_BS`).
    - Cabinets: Marshall 1960A, Mesa 4x12, Celestion V30, Vox AC30, Orange 2x12.
- **`audition_slot(category: str, slot: int) -> dict`**:
  - Sets active RAM Block 1 (`AMP`) or Block 5 (`CAB`) model to `slot` and enables the block so sound is immediately heard.

### 2.3 Server API (`server.py`)
- `POST /api/models/rename`:
  - Request: `{"category": "amp" | "cab", "slot": 0..19, "name": "New Name"}`
  - Response: `{"ok": true, "category": ..., "slot": ..., "name": ..., "state": ...}`
- `GET /api/models/library`:
  - Response: `{"library": { "overdrive": [...], "clean": [...], "crunch": [...], "highgain": [...], "bass": [...], "cabinets": [...] }}`
- `POST /api/models/audition`:
  - Request: `{"category": "amp" | "cab", "slot": 0..19}`
  - Response: `{"ok": true, "active_slot": slot, "state": ...}`
- `POST /api/models/validate_import`:
  - Request: `{"filename": "...", "content_base64": "..."}`
  - Response: `{"valid": true, "kind": "am4"|"cab", "name": "...", "details": {...}}`

### 2.4 Web UI (`index.html`, `styles.css`, `app.js`)
- **Top Bar Integration**:
  - New button: `[Capturas & IRs]` with chip/badge icon in `.top-actions`.
  - Also accessible from right-side Effects Library Drawer (`Biblioteca de efectos`).
- **Modal `#modal-capture-manager`**:
  - Tabs: `[Preamps & Overdrives (20 Slots)]` and `[Cabinet IRs (20 Slots)]`.
  - 20 Slot Cards grid:
    - Slot index (`01` through `20`), glowing indicator if currently active in RAM.
    - Editable slot name with single-click edit field and Save/Cancel button.
    - "Audition" button to instantly test tone.
    - "Select from Library" button to replace slot name from curated library.
  - Curated Library Picker drawer:
    - Quick-filter chips: `[All]`, `[Overdrives]`, `[Clean]`, `[Crunch]`, `[High Gain]`, `[Bass]`.
  - Import / Upload dropzone:
    - Drop `.am3`, `.am4`, `.bin`, or `.wav` file to inspect metadata and assign to selected slot.
- **Strict Security & Offline Constraints**:
  - 100% offline, 0 CDN scripts or fonts.
  - Zero `.innerHTML` or `insertAdjacentHTML` usage in `app.js`.
  - Proper modal trap and `Escape` key support.

---

## 3. Verification & Acceptance Criteria
1. `test_protocol_rename_and_capture_validation`: Verifies `encode_name_record`, `build_rename_slot`, and header parsing for AM4/WAV.
2. `test_device_service_rename_and_audition`: Verifies hardware SysEx write, ACK validation, in-memory sync, and audition RAM update.
3. `test_server_capture_manager_endpoints`: Verifies all REST endpoints (`/api/models/rename`, `/library`, `/audition`, `/validate_import`).
4. `test_ui_capture_manager_integration`: Verifies DOM elements, styling, event bindings, and offline XSS compliance.
5. Live verification with physical ME-01 pedal connected over USB-MIDI.

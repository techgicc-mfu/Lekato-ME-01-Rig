# ME-01 Rig

> **Photorealistic Desktop Editor & Rig Manager for the LEKATO ME-01 & M-VAVE Tank-G Multi-Effects Pedal**

ME-01 Rig is a lightweight, zero-dependency desktop application for tweaking presets, managing neural amp models and IRs, and auditioning tones in real time on the **LEKATO ME-01** and **M-VAVE Tank-G** guitar pedals.

---

## Key Features

### 🎛️ Dual-View Studio Experience
* **Studio View (AnnLab-Style)**: Photorealistic vintage amp head with warm glowing vacuum tubes, textured speaker cabinet, stompbox pedals with dedicated right-side parameter bays, and a center glossy LCD preset capsule.
* **Pedalboard View (UltraRig-Style)**: Skeuomorphic rack view complete with dynamic SVG patch cables, chicken-head rotary knobs, active LED indicators, reorderable signal chain, and a zoomed parameter inspector.
* **Seamless View Toggling**: Switch between Studio View and Pedalboard View anytime using the top navigation bar or `<LARGE>` mode.

### ⚡ Real-Time Bidirectional Parameter Sync
* **Zero-Latency USB-MIDI**: Direct hardware communication via Windows Multimedia (WinMM) SysEx protocol.
* **Live RAM Auditioning**: Tweak parameters on your computer and hear changes instantly on your pedal without wearing out flash memory.
* **Safety & Peace of Mind**:
  * **Automatic Connect Backup**: Automatically backs up all 80 slots to disk on first connect.
  * **Factory Preset Protection**: Slots P01–P40 are locked by default to prevent accidental overwrite (with an explicit unlock toggle).
  * **Multi-level Undo & Revert**: Instantly undo parameter changes or revert back to the saved slot state.

### 💾 80-Preset Bank & Preset Manager
* Full management for all 80 preset slots (P01–P40 Factory, P41–P80 User).
* Quick preset filtering by slot number, amp model, or cab name.
* Single-slot save, batch backup, and full restoration with checksum validation.

### 📦 Neural Capture & Impulse Response (IR) Manager
* **20 Amp Model Slots**: Audition, rename, and load Artificial Neural Network (ANN / NAM) amp models.
* **20 Cab IR Slots**: WAV file header validation (sample rate, bit depth, channel count) and custom cabinet loading.
* Import and export capture packages directly to/from the hardware.

### 🚀 100% Offline & Ultra-Lightweight
* **Zero External Dependencies**: Built entirely with Python's standard library (`http.server`, `ctypes`, `threading`, `json`, `wave`) and vanilla HTML5 / CSS3 / ES6.
* **No Node.js, Electron, or heavy web frameworks required.**
* **Demo Mode**: Built-in mock hardware simulation allows full UI exploration, tone tweaking, and preset testing even without a pedal connected.

---

## Getting Started

### Prerequisites
* **Python 3.10 or higher** installed on Windows, macOS, or Linux.
* USB cable connecting your LEKATO ME-01 or M-VAVE Tank-G to your computer.

### Installation & Launch

1. **Clone the repository**:
   ```bash
   git clone https://github.com/techgicc-mfu/Lekato-ME-01-Rig.git
   cd Lekato-ME-01-Rig
   ```

2. **Run ME-01 Rig**:
   * **Windows Quick Launch**: Double-click `ME01-Rig.bat`
   * **Command Line (Auto-connect to hardware)**:
     ```powershell
     python launch.py
     ```
   * **Demo Mode (No hardware required)**:
     ```powershell
     python launch.py --demo
     ```

The app will start a local server and automatically launch your default browser to `http://127.0.0.1:59400/`.

---

## Signal Chain & Effects Architecture

ME-01 Rig controls all 6 serial effect blocks supported by the ME-01 firmware:

```
[ IN ] ➔ [ FX / COMP ] ➔ [ AMP ] ➔ [ MOD ] ➔ [ DLY ] ➔ [ REV ] ➔ [ CAB ] ➔ [ OUT ]
```

| Block | Effect Types & Models | Controllable Parameters |
|---|---|---|
| **FX** | Boost, Compressor | Gain, Gate, Sustain, Level, Attack |
| **AMP** | 20 Neural Capture Models (Clean, Crunch, High Gain, Lead) | Gain, Bass, Middle, Treble, Volume |
| **MOD** | Chorus, Flanger, Phaser | Speed, Depth, Mix |
| **DLY** | Analog Delay, Tape Echo, Dual Delay | Time, Feedback, Mix |
| **REV** | Room, Hall, Plate, Spring Reverb | Decay, Tone, Mix |
| **CAB** | 20 Speaker IRs (Marshall 1960A, EVH 5150, Fender, etc.) | Level, Bypass |

---

## Project Structure

```
Lekato-ME-01-Rig/
├── launch.py               # Launcher script with browser detection & lifecycle manager
├── ME01-Rig.bat            # One-click Windows batch launcher
├── me01_rig/
│   ├── winmm_transport.py  # Low-level ctypes WinMM MIDI SysEx transport
│   ├── protocol.py         # SysEx encoder/decoder, 7-bit packing & checksums
│   ├── device_service.py   # State machine, RAM polling, backup/restore & undo stack
│   ├── server.py           # Local lightweight REST API server
│   └── static/             # 100% offline Web UI
│       ├── index.html      # Responsive dual-view UI structure
│       ├── styles.css      # Skeuomorphic styling, glowing tubes & dark theme
│       ├── app.js          # Reactive UI controller, drag & drop, knob bindings
│       └── annlab/         # High-resolution photorealistic gear graphics
├── docs/                   # Architectural specifications and protocol documentation
└── tests/                  # Automated test suite (49 unit and integration tests)
```

---

## Running Tests

ME-01 Rig includes a test suite covering SysEx protocol parsing, WinMM drivers, REST endpoints, and UI offline asset validation.

To run all tests:

```powershell
$env:PYTHONPATH="."
python -m unittest discover -s tests -v
```

All 49 unit and integration tests run offline without requiring physical hardware.

---

## Compatible Hardware

* **LEKATO ME-01** Multi-Effects Pedal
* **M-VAVE Tank-G** Guitar Multi-Effects Pedal
* Other compatible M-VAVE ANN/IR pedalboard hardware

---

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.

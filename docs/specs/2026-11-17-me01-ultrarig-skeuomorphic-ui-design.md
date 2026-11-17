# ME-01 Rig: UltraRig Skeuomorphic Visual Overhaul Design Spec

**Date:** 2026-11-17  
**Status:** Draft (Awaiting User Approval)  
**Location:** `docs/specs/2026-11-17-me01-ultrarig-skeuomorphic-ui-design.md`  
**Target Platform:** Windows 10/11 standalone desktop app window (Chrome / Edge `--app`), offline, zero external dependencies.

---

## 1. Intent and Context

The user is running **ME-01 Rig** with a connected **LEKATO ME-01** (`ME-01_016`) multi-effects pedal.
While the v1 implementation successfully established the communication protocol, safety rules, background polling, and basic web UI, the user requested an overhaul of the visual experience to match the aesthetics of **UltraRig Alpha 11 / ultrarig.app** (as depicted in their uploaded screenshots):

1. **Photorealistic Skeuomorphic Stompboxes:** Tactile pedal enclosures with powder-coated colors (Boss blue, MXR orange, brushed aluminum, Electro-Harmonix metallic green), realistic knurled metal knobs, chrome 3PDT footswitches, and glowing jewel LEDs.
2. **Realistic 1/4" Patch Cables:** Curving black instrument cables with silver right-angle phone jacks plugged into pedal jacks.
3. **Photorealistic Amplifier Head (`[Amp]` view):** A dedicated vintage amp head with textured black tolex, white piping, metal faceplate, chicken-head knobs, illuminated pilot jewel light, and power/standby toggles.
4. **Section Navigation Tabs:** Quick access tabs (`[Pedales]`, `[Amp]`, `[Post-amp]`, plus a unified `[Pedalera]` full board view).
5. **Right-Hand Effects Library Drawer ("Biblioteca de efectos"):** A slide-out panel categorized by effect type (Dynamics, Mod, Delay, Reverb, Amp, Cab) with visual pedal cards and search for instant model swapping.
6. **Top Signal Flow Minimap:** Compact breadcrumb chain showing `IN -> ... -> OUT` with bypass status.

---

## 2. Goals, Non-Goals, and Anti-Goals

### Goals
- **Skeuomorphic Pedalboard Experience:** Transform the 6 ME-01 signal blocks (`FX`, `AMP`, `MOD`, `DLY`, `REV`, `CAB`) into detailed, tangible guitar pedals connected with realistic patch cables.
- **Dedicated Amp Head & Cab Stage:** When the user selects `[Amp]`, display a photorealistic guitar amplifier head with tolex grain, jewel pilot lamp, brand faceplate, and chicken-head tone controls for Gain, Level, Bass, Middle, and Treble, plus Patch Volume.
- **Section View Switching:** Provide 4 view tabs matching UltraRig:
  - `[Pedalera]` (Full Chain): Shows all 6 blocks side-by-side with inter-pedal patch cables.
  - `[Pedales]` (Pre-amp): Focuses on the pedals positioned before the amplifier (e.g. `FX` Noise Gate / Boost / Compressor).
  - `[Amp]`: Focuses on the amplifier head and speaker cabinet.
  - `[Post-amp]`: Focuses on modulation (`MOD`), delay (`DLY`), and reverb (`REV`).
- **Effects Library Drawer:** Collapsible right-hand panel categorized by Dynamics, Modulation, Delay, Reverb, Amp, and Cab, enabling users to browse all 43 built-in ME-01 models by visual stompbox icons and click to swap models.
- **Patch Cables with Auto-Routing:** Dynamic SVG bezier curves (`<path d="M... C...">`) connecting 1/4" metal jacks between neighboring pedals; cables automatically update when blocks are reordered via drag-and-drop or `< Earlier` / `Later >`.
- **Top Signal Flow Breadcrumb:** A sleek minimap strip at the top showing the signal flow from `IN` to `OUT`, allowing quick block selection and bypass toggling.
- **100% Offline & Zero Dependencies:** All visual graphics rendered procedurally via vector SVG and CSS3 (gradients, drop shadows, metallic highlights). Zero external web fonts, zero CDN requests, zero image file assets required.
- **Seamless ME-01 Integration:** Full two-way synchronization with the existing `me01_rig` backend (`/api/state`, `/api/ram/*`, `/api/presets`, `/api/flash/save`). Retains the 50 ms knob coalescing, 1200 ms edit suppression, undo stack, and factory-slot safety guards.

### Non-Goals (This Phase)
- **AM3 / AM4 Binary Capture Flashing:** Deferred to Phase 2 as decided in Approach 1.
- **In-Browser Audio DSP:** Audio processing remains 100% on the physical ME-01 pedal; the UI remains a hardware controller.
- **Parallel Routing (`+ parallel`):** Kept disabled to match the ME-01's hardware 6-block serial architecture.

### Anti-Goals
- **No Heavy 3D WebGL / Three.js Runtimes:** Avoid heavy 3D engines that cause high CPU/GPU usage or introduce npm dependencies; pure DOM + SVG provides 60 FPS slider response and instant startup.
- **No Disruption of Existing Safety Mechanisms:** Factory slot lock (`P01..P40`), pre-save backups, and single-restore verified writes must remain fully active and accessible.

---

## 3. Approaches Considered & Selected

- **Approach 1: UltraRig Skeuomorphic Visual Overhaul First, then Capture Loader (SELECTED)**
  - *Description:* Overhaul the visual UI to deliver the complete UltraRig skeuomorphic pedalboard, patch cables, amp head, section tabs, and effects library drawer using the existing 43 hardware DSP models and 80 presets. Follow with the AM3/AM4 capture loader in Phase 2.
  - *Trade-off:* Delivers an immediate visual upgrade without risking firmware/flash reverse engineering issues.
- **Approach 2: Capture Loader First, then Visual Upgrade (REJECTED)**
  - *Trade-off:* Delays the visual overhaul that the user specifically requested from their uploaded screenshots.
- **Approach 3: All-in-One Delivery (REJECTED)**
  - *Trade-off:* Couples UI frontend design with low-level binary capture reverse-engineering into an oversized, high-risk release.

---

## 4. Architectural & Visual Design

### 4.1 UI Layout Structure
```
+---------------------------------------------------------------------------------------------------+
| Topbar: [ME-01 RIG] [Conn Status: Connected (ME-01_016)] [Slot: P72 Modified] [Save] [Undo] ...  |
+---------------------------------------------------------------------------------------------------+
| Presets Bar: [< Presets Bank Drawer]  [Active: P72 - Lead Drive]  [Revert] [Export] [Import]       |
+---------------------------------------------------------------------------------------------------+
| Signal Flow Minimap: [IN] -> [FX: Gate] -> [AMP: Hiwatt] -> [MOD: Phase] -> [DLY] -> [REV] -> [OUT] |
| Navigation Tabs:   [ (•) Pedalera ]   [ Pedales ]   [ Amp ]   [ Post-amp ]                        |
+---------------------------------------------------+-----------------------------------------------+
|                                                   |  Effects Library Drawer (Collapsible Right)   |
|  Main Stage View:                                 |  [ Search effects... ]                        |
|                                                   |  > Dinámica (Noise Gate++, Boost, Compress)  |
|  [Stompbox 1] ==(Patch Cable)==> [Stompbox 2]     |  v Drive / Preamp (20 Amp Models)             |
|   - Metal enclosure                               |     [ Hiwatt Head ]  [ Marshall 800 ]         |
|   - Interactive rotary knobs (drag & tooltip)     |     [ EVH 5150 ]     [ Fender Twin ]          |
|   - 3PDT chrome switch + glowing LED              |  > Modulación (Chorus, Phaser, Flanger...)    |
|   - Input/Output 1/4" metal jacks                 |  > Delay (Analog, Duck, Dtape, Dual, Lofi)    |
|                                                   |  > Reverb (Room, Hall, Spring, Shimmer...)    |
|  OR: [Photorealistic Amp Head + Speaker Cab]      |  > Cabs (20 Speaker IRs)                      |
|                                                   |                                               |
+---------------------------------------------------+-----------------------------------------------+
| Bottom Bar: Tempo: 120.0 BPM [TAP]  |  Master Vol: 78%  |  [Backup Manager]  |  [Factory Lock]    |
+---------------------------------------------------------------------------------------------------+
```

### 4.2 Resolved Design Decisions & Hardware Fidelity
1. **Collapsible Presets Bank Drawer (Left) instead of Tank-G Scenes:**
   - UltraRig shows "Scenes 1-4" which are specific to Tank-G custom firmware. The LEKATO ME-01 physical hardware uses an 80-preset memory bank (`P01..P80`) with no concept of scenes.
   - To give the skeuomorphic pedalboard maximum horizontal stage space without sacrificing preset access, presets are housed in a collapsible left slide-out "Presets Bank" drawer (toggled via button or keyboard shortcut `P`), with quick preset selector dropdown on the top bar.
2. **Hardware-Accurate Controls (No Ghost Controls):**
   - UltraRig displays `Mono/Stereo`, Amp `Standby`, and Amp `Presence`.
   - The ME-01 DSP running firmware `ME-01_016` has a mono serial engine; its AMP block exposes exactly 5 hardware parameters: `Gain`, `Level`, `Bass`, `Mid`, `Treble` (knob 6 is ghost/ignored by firmware).
   - The UI strictly renders the 5 real knobs on the Amp head, plus global `Patch Volume`, avoiding confusing inert controls.
3. **Dual Control Architecture: On-Pedal Direct Knobs + Precision Bottom Bar:**
   - Rotary knobs are rendered directly on the pedal and amp graphics. Knobs support vertical mouse-drag, mouse-wheel, and display glowing value tooltips (`120.0 BPM`, `381 ms`, `12.5 kHz`).
   - A compact bottom status/inspector strip provides fine numeric entry, DLY Tap Tempo / BPM calculator, and Patch Volume.
4. **Dynamic Section Navigation Tabs:**
   - `[Pedalera]` (Full Chain): Shows all 6 blocks side-by-side with inter-pedal patch cables.
   - `[Pedales]` (Pre-amp): Dynamically queries the current routing order and displays whichever blocks are positioned *before* `AMP` (e.g. `FX`).
   - `[Amp]`: Displays the photorealistic Amp head stacked on top of a textured speaker cabinet (`CAB` block with Level, Low Cut, High Cut).
   - `[Post-amp]`: Dynamically displays whichever blocks are positioned *after* `AMP` in the chain (e.g. `MOD`, `DLY`, `REV`).
5. **Effects Library Drawer Integration:**
   - The right-hand drawer displays visual pedal cards for all 43 ME-01 DSP models.
   - Clicking an effect automatically updates its corresponding hardware block (`FX`, `AMP`, `MOD`, `DLY`, `REV`, or `CAB`) via `/api/ram/model`, immediately updating the stage stompbox.
6. **Cabinet (`CAB`) Visual Stacking:**
   - In `[Pedalera]` view, `CAB` appears as an enclosure card at the end of the chain.
   - In `[Amp]` view, `CAB` is rendered as a photorealistic speaker cabinet (black basketweave grille cloth, white piping, chrome corners) stacked underneath or beside the amp head.

### 4.3 Skeuomorphic Stompbox Graphics Specification
Each pedal model is generated via an SVG generator with custom themes:
1. **Noise Gate ("Smart Signal"):** Forest green enclosure, cream silkscreen borders, threshold/release knobs, red high-brightness LED, chrome 3PDT stomp switch.
2. **Compressor ("Silver Squeeze"):** Brushed natural aluminum enclosure, black pointer knobs, red indicator LED.
3. **Boost ("Blues Racer / Clean Drive"):** Royal blue powder-coat with racing stripes, knurled silver knobs.
4. **Phaser ("Phase 91"):** High-visibility orange enamel finish with radial typography, large center speed knob, script logo.
5. **Chorus ("Double Vision"):** Deep metallic purple with dual-tone gradient faceplate, low-cut and mix mini-dials.
6. **Flanger ("Lightning Mistress"):** Polished chrome chassis with neon green & black hazard silkscreen.
7. **Delay ("Digital Echo 220 / Analog"):** Dark slate enclosure with red illuminated 7-segment digital time readout (`ms` / `BPM`), feedback, mix, and time knobs.
8. **Reverb ("Cloud & Shimmer"):** Deep twilight blue/cyan enclosure with ambient diffusion controls.

### 4.4 Photorealistic Amp Head & Speaker Cabinet View
In the `[Amp]` tab:
- **Head Enclosure:** Textured black vinyl tolex with corner chrome braces and white edge piping.
- **Grille & Faceplate:** Gold anodized aluminum or brushed stainless faceplate with vintage typography and model badge.
- **Tone Controls:** Chicken-head knobs with realistic rotation angle calculation (`-135deg` to `+135deg`) for the 5 physical hardware parameters: `Gain`, `Level`, `Bass`, `Mid`, and `Treble`.
- **Pilot Lamp:** Multi-faceted red jewel lamp that glows when the Amp block is active and dims when bypassed.
- **Switches:** Heavy metal toggle switch for Power/Bypass.
- **Speaker Cabinet (`CAB` block):** Stacked cabinet enclosure with basketweave grille cloth, chrome corner protectors, and tone controls for Cab Level, Low Cut, and High Cut.

### 4.5 Realistic Patch Cable Engine
- Cables are drawn in an overlay SVG canvas connecting neighboring stompbox output and input jacks.
- Calculated using cubic Bezier curves: `M x1 y1 C x1+dx y1+dy, x2-dx y2+dy, x2 y2`.
- Rendered with double-stroke effect: outer black rubber cable casing (6px) with an inner glossy specular highlight (2px), ending in metallic 1/4" barrel jacks.
- Bypassed pedals dim the cable segment; dragged pedals dynamically stretch the cable curve in real time.

### 4.6 Effects Library Drawer
- Slides in from the right edge of the stage (or can be pinned open on wide desktop displays).
- Contains searchable, collapsible accordions for all 6 block categories.
- Each effect tile displays a miniature rendered pedal icon with model title and subtitle.
- Clicking an effect in the drawer instantly assigns that model to the active slot via `/api/ram/model`.

---

## 5. Verification and Builder Boundaries

### What is Left to the Builder
- Precise SVG path coordinates for stompbox hardware (footswitch bezels, screws, jack barrels).
- CSS animation keyframes for footswitch press (`transform: translateY(2px) scale(0.98)`).
- Cable slack calculations based on distance between adjacent pedals.
- Responsive breakpoints for drawer collapse on smaller screen resolutions (`< 1200px`).

### Verification Plan
1. `python -W error -m unittest discover -v`: All 32 existing unit tests must continue to pass without regression.
2. `node --check me01_rig/static/app.js`: JavaScript syntax check must pass with zero errors.
3. `tests/test_ui_assets.py`: Update asset tests to verify new UI controls, tabs, and drawer components.
4. Live browser smoke check: Launch `launch.py --demo` and verify DOM elements (`.pedal-card-skeuo`, `.patch-cable`, `.amp-head-stage`, `.effects-drawer`) render in headless Edge with zero console errors.

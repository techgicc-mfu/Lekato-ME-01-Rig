# UltraRig Skeuomorphic Visual Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Overhaul ME-01 Rig's web UI to deliver a photorealistic skeuomorphic pedalboard experience inspired by UltraRig Alpha 11, featuring tangible stompboxes, rotary knobs with floating tooltips, curving SVG patch cables, a vintage Amp Head & stacked Cabinet stage, 4-way section tabs, and an Effects Library drawer, while controlling the physical LEKATO ME-01 pedal 100% offline.

**Architecture:** Pure procedural HTML5/CSS3/SVG frontend without third-party frameworks or CDN dependencies; communicates with the existing Python 3.15 `me01_rig` backend via REST APIs (`/api/state`, `/api/ram/*`, `/api/presets`). Stompboxes, chicken-head knobs, patch cables, and tolex textures are rendered procedurally using standard CSS gradients and SVG paths with strict XSS safety (DOM API only, zero `.innerHTML`).

**Tech Stack:** Python 3.15 standard library (`unittest`, `http.server`, `json`), vanilla JavaScript (ES2022 DOM APIs, SVG, `ResizeObserver`), CSS3 (custom properties, flexbox/grid, linear/radial gradients, box shadows), Windows 10/11 standalone desktop app window (`msedge --app`).

**Spec:** `docs/specs/2026-11-17-me01-ultrarig-skeuomorphic-ui-design.md`

## Global Constraints

- **Language & Runtime:** Pure Python 3.15 stdlib backend; pure vanilla HTML5/CSS3/ES2022 frontend.
- **Offline Guarantee:** 100% offline operation. Zero external CDN dependencies, zero remote font imports, zero network asset downloads (enforced by `test_static_files_exist_and_are_100_percent_offline`).
- **DOM & XSS Security:** Zero usage of `.innerHTML` or `insertAdjacentHTML` in `app.js`; all elements, SVGs, and text nodes must be constructed via standard DOM APIs (`document.createElement`, `document.createElementNS`, `textContent`, `setAttribute`).
- **Hardware Protocol Integrity:** Never alter the verified 92-byte SysEx structure, parameter address maps, 50ms knob coalescing, 1200ms edit suppression, or factory preset locks (`P01..P40`).
- **Hardware-Fidelity Controls:** Omit ghost/inert hardware controls (`Mono/Stereo`, Amp `Standby`, Amp `Presence`). The Amp block exposes exactly 5 hardware parameters (`Gain`, `Level`, `Bass`, `Mid`, `Treble`) plus `Patch Volume`.
- **Quality Standard:** All tests must pass with `python -W error -m unittest discover -v` and JavaScript syntax must validate cleanly with `node --check me01_rig/static/app.js`.

## Review Focus

1. **Dynamic tab switching with non-standard routing orders:** When user reorders blocks so multiple modules precede or follow `AMP`, `[Pedales]` must display all pre-amp blocks, `[Post-amp]` must display all post-amp blocks, and `[Amp]` must consistently show the Amp head and Cab without throwing layout exceptions.
2. **Rotary knob pointer capture & value clamping:** Dragging a rotary knob past screen edges or releasing off-window must release pointer capture cleanly, clamp values strictly to `0..100` (or model-specific max), and deliver coalesced updates through `queueKnobChange`.
3. **Patch cable dynamic recalculation on DOM layout changes:** Resizing the window, dragging pedals to reorder, or toggling section tabs must cleanly clear and redraw SVG Bezier paths between output and input jacks without leaving disconnected visual artifacts or leaking DOM nodes.
4. **Effects library drawer model assignment targeting:** Clicking an effect card in the drawer must correctly target that model's designated hardware block (`FX`, `AMP`, `MOD`, `DLY`, `REV`, or `CAB`), select the block, send `/api/ram/model`, and update both the drawer active state and the stage graphic.
5. **Collapsible Presets Bank drawer state retention:** Opening or collapsing the slide-out Presets Bank drawer must preserve active preset selection, search filter text, and ongoing knob edits without resetting the stage scroll or focus.

---

### Task 1: Skeuomorphic Stompbox SVG Templates & Theme Engine

**Files:**
- Modify: `me01_rig/static/index.html:200-245`
- Modify: `me01_rig/static/styles.css:80-260`
- Modify: `me01_rig/static/app.js:1390-1460`
- Modify: `tests/test_ui_assets.py:168-210`

**Interfaces:**
- Consumes: `BLOCK_CATALOG` in `app.js`, block state from `/api/state` (`block_id`, `model_name`, `enabled`, `knobs`).
- Produces: `buildPedalSvg(block)` returning an SVG node with photorealistic metallic chassis, corner screws, 3PDT stomp switch, glowing LED halo, and 1/4" metal jack sockets. CSS classes `.pedal-skeuo-chassis`, `.pedal-theme-gate`, `.pedal-theme-compressor`, `.pedal-theme-drive`, `.pedal-theme-mod`, `.pedal-theme-delay`, `.pedal-theme-reverb`.

- [ ] **Step 1: Write the failing test in `tests/test_ui_assets.py`**

Add test method `test_skeuomorphic_pedal_templates_and_themes` asserting:
1. `tpl-pedal-skeuo` template exists in `index.html`.
2. Required SVG elements exist in the template: `.svg-chassis-bevel`, `.svg-chassis-screw`, `.svg-jack-left`, `.svg-jack-right`, `.svg-switch-ring`, `.svg-switch-plunger`, `.svg-led-jewel`.
3. CSS theme classes exist in `styles.css`: `pedal-theme-smart-signal`, `pedal-theme-silver-squeeze`, `pedal-theme-blues-racer`, `pedal-theme-phase-91`, `pedal-theme-double-vision`, `pedal-theme-lightning-mistress`, `pedal-theme-digital-echo`.
4. `app.js` references `tpl-pedal-skeuo` and builds chassis themes via DOM APIs without `.innerHTML`.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -W error -m unittest tests/test_ui_assets.py -k test_skeuomorphic_pedal_templates_and_themes -v`
Expected: FAIL with missing template / tokens.

- [ ] **Step 3: Implement SVG templates, CSS themes, and JS pedal renderer**

1. In `index.html`: Define `<template id="tpl-pedal-skeuo">` with SVG viewBox `0 0 130 190` featuring:
   - Outer shadow & bevel: `<rect class="svg-chassis-shadow">`, `<rect class="svg-chassis-bevel">`, `<rect class="svg-chassis-body">`.
   - Corner chassis hex screws: `<circle class="svg-chassis-screw">` at 4 corners.
   - Chrome 1/4" phone jack sockets on left and right edges: `<rect class="svg-jack-left">`, `<rect class="svg-jack-right">`.
   - Recessed faceplate with silkscreen border: `<rect class="svg-faceplate">`, `<text class="svg-pedal-title">`.
   - Knobs mounting bay: `<g class="svg-knobs-layer">`.
   - Glowing jewel LED: `<circle class="svg-led-halo">`, `<circle class="svg-led-jewel">`.
   - Heavy 3PDT footswitch: `<circle class="svg-switch-ring">`, `<circle class="svg-switch-nut">`, `<circle class="svg-switch-plunger">`.
2. In `styles.css`: Add styles for skeuomorphic pedal enclosures:
   - Gradients and powder-coat textures for distinct pedal models (Smart Signal forest green, Silver Squeeze brushed aluminum, Blues Racer royal blue, Phase 91 warm orange, Double Vision deep purple, Lightning Mistress chrome/black, Digital Echo dark slate).
   - Chrome metallic gradients for footswitches, screws, and jacks.
   - High-brightness LED glow filters and transitions when toggling bypass.
3. In `app.js`: Update `buildPedalSvg(block)` to clone `tpl-pedal-skeuo`, apply the appropriate theme class based on block type and model index, and populate labels using `textContent`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -W error -m unittest tests/test_ui_assets.py -k test_skeuomorphic_pedal_templates_and_themes -v`
Expected: PASS.
Run: `node --check me01_rig/static/app.js`
Expected: Returncode 0.

- [ ] **Step 5: Commit**

```bash
git add me01_rig/static/index.html me01_rig/static/styles.css me01_rig/static/app.js tests/test_ui_assets.py
git commit -m "feat(ui): add skeuomorphic stompbox SVG templates and theme engine"
```

---

### Task 2: Interactive Rotary Knobs & Value Tooltip Engine

**Files:**
- Modify: `me01_rig/static/styles.css:260-400`
- Modify: `me01_rig/static/app.js:1400-1490`
- Modify: `tests/test_ui_assets.py:168-230`

**Interfaces:**
- Consumes: Block parameters (`knobs` array with `slot`, `addr`, `name`, `raw`, `unit`), `queueKnobChange(addr, raw)` in `app.js`.
- Produces: `appendInteractiveKnobSvg(parent, ns, cx, cy, radius, knob, block)` creating a draggable SVG rotary knob with pointer notch and indicator dot; floating tooltip `#knob-floating-tooltip` displaying parameter name and formatted value during drag/hover.

- [ ] **Step 1: Write the failing test in `tests/test_ui_assets.py`**

Add test method `test_interactive_rotary_knobs_and_tooltip` asserting:
1. Floating tooltip `#knob-floating-tooltip` element exists in `index.html`.
2. Rotary knob CSS classes exist in `styles.css`: `.rotary-knob-group`, `.rotary-dial`, `.rotary-notch`, `.rotary-dot`, `.knob-tooltip`.
3. `app.js` implements pointer drag listeners (`pointerdown`, `pointermove`, `pointerup`, `pointercancel`) and wheel listener (`wheel`) with `setPointerCapture`.
4. Values are clamped between minimum and maximum bounds (0 to 100, or parameter ceiling) and dispatched via `queueKnobChange`.
5. Pointer release outside element properly cleans up listeners and hides the tooltip (Review Focus 2).

- [ ] **Step 2: Run test to verify it fails**

Run: `python -W error -m unittest tests/test_ui_assets.py -k test_interactive_rotary_knobs_and_tooltip -v`
Expected: FAIL.

- [ ] **Step 3: Implement rotary knob SVG components, pointer drag logic, and floating tooltip**

1. In `index.html`: Add `<div id="knob-floating-tooltip" class="knob-floating-tooltip" hidden></div>`.
2. In `styles.css`: Style rotary knobs and tooltips:
   - Knob dial with knurled side grooves, radial metallic gradient, chrome center cap.
   - High-contrast pointer notch and LED indicator dot rotated by `--knob-angle` (`-135deg` to `+135deg`).
   - Floating dark glass tooltip with cyan glowing value readout, positioned directly above the active knob.
3. In `app.js`: Implement `appendInteractiveKnobSvg`:
   - Construct knob SVG `<g class="rotary-knob-group">` with dial circle, notch line, center cap, and label text.
   - Attach `pointerdown` listener: records start Y and initial raw value, calls `ev.target.setPointerCapture(ev.pointerId)`.
   - Attach `pointermove` listener: calculates vertical delta (sensitivity 1.0 unit per 2 pixels dragged), updates rotation angle `angle = -135 + (val / maxVal) * 270`, updates tooltip text and position, invokes `queueKnobChange(knob.addr, val)`.
   - Attach `wheel` listener: allows precise incremental turning with mouse wheel (preventing page scroll).
   - Attach `pointerup`, `pointercancel`: releases pointer capture, hides tooltip.
   - Cleanly clamps value to `0..maxVal` (Review Focus 2).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -W error -m unittest tests/test_ui_assets.py -k test_interactive_rotary_knobs_and_tooltip -v`
Expected: PASS.
Run: `node --check me01_rig/static/app.js`
Expected: Returncode 0.

- [ ] **Step 5: Commit**

```bash
git add me01_rig/static/index.html me01_rig/static/styles.css me01_rig/static/app.js tests/test_ui_assets.py
git commit -m "feat(ui): implement interactive rotary knobs and floating value tooltip"
```

---

### Task 3: Dynamic Curved SVG Patch Cable Routing Engine

**Files:**
- Modify: `me01_rig/static/index.html:105-130`
- Modify: `me01_rig/static/styles.css:400-520`
- Modify: `me01_rig/static/app.js:1460-1550`
- Modify: `tests/test_ui_assets.py:168-240`

**Interfaces:**
- Consumes: Rendered `.pedal-card` elements on the pedalboard stage, block bypass states (`block.enabled`).
- Produces: `<svg id="patch-cables-svg" class="patch-cables-layer">` overlay, `renderPatchCables()` function dynamically drawing cubic Bezier cables between neighboring pedal jack positions.

- [ ] **Step 1: Write the failing test in `tests/test_ui_assets.py`**

Add test method `test_dynamic_patch_cable_routing` asserting:
1. `#patch-cables-svg` overlay element exists in `index.html`.
2. CSS classes exist in `styles.css`: `.patch-cables-layer`, `.patch-cable-outer`, `.patch-cable-inner`, `.patch-cable-jack`, `.patch-cable-dimmed`.
3. `app.js` defines `renderPatchCables()` that computes bounding rectangles of consecutive output/input jacks and appends SVG `<path>` elements with cubic Bezier commands (`M ... C ...`).
4. Cable path elements receive `.patch-cable-dimmed` when either connected pedal is bypassed.
5. Window resize and DOM changes trigger cable re-rendering via `ResizeObserver` without leaving disconnected paths (Review Focus 3).

- [ ] **Step 2: Run test to verify it fails**

Run: `python -W error -m unittest tests/test_ui_assets.py -k test_dynamic_patch_cable_routing -v`
Expected: FAIL.

- [ ] **Step 3: Implement dynamic patch cable engine in CSS and JS**

1. In `index.html`: Insert `<svg id="patch-cables-svg" class="patch-cables-layer" aria-hidden="true"></svg>` inside `#pedalboard-chain`.
2. In `styles.css`: Add styling for patch cables:
   - Outer rubber cable jacket: stroke width 7px, `#141618`, subtle drop shadow.
   - Inner specular highlight: stroke width 2px, `#383e48`, semi-transparent gloss.
   - Right-angle 1/4" metal plug end: metallic gradient barrel with knurled strain relief sleeve.
   - Dimmed cable transition: `opacity: 0.35` when a connected block is bypassed.
3. In `app.js`: Implement `renderPatchCables()`:
   - Clear existing paths in `#patch-cables-svg`.
   - Query all visible `.pedal-card` elements in chain order.
   - For each adjacent pair `(pedal[i], pedal[i+1])`:
     - Measure coordinates of right jack on `pedal[i]` and left jack on `pedal[i+1]` relative to `#patch-cables-svg`.
     - Calculate Bezier control points: `cx1 = x1 + dx * 0.45`, `cy1 = y1 + slack`, `cx2 = x2 - dx * 0.45`, `cy2 = y2 + slack` (where slack varies smoothly with distance).
     - Render outer casing `<path>` and inner gloss `<path>`.
     - If `!pedal[i].enabled || !pedal[i+1].enabled`, add `.patch-cable-dimmed`.
   - Connect input node jack to first pedal, and last pedal to output node jack.
   - Register a `ResizeObserver` on `#pedalboard-stage` to trigger `requestAnimationFrame(renderPatchCables)` on layout shifts (Review Focus 3).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -W error -m unittest tests/test_ui_assets.py -k test_dynamic_patch_cable_routing -v`
Expected: PASS.
Run: `node --check me01_rig/static/app.js`
Expected: Returncode 0.

- [ ] **Step 5: Commit**

```bash
git add me01_rig/static/index.html me01_rig/static/styles.css me01_rig/static/app.js tests/test_ui_assets.py
git commit -m "feat(ui): implement dynamic curved SVG patch cable routing engine"
```

---

### Task 4: Photorealistic Amp Head & Stacked Speaker Cabinet (`[Amp]` Stage)

**Files:**
- Modify: `me01_rig/static/index.html:130-170`
- Modify: `me01_rig/static/styles.css:520-720`
- Modify: `me01_rig/static/app.js:1550-1660`
- Modify: `tests/test_ui_assets.py:220-270`

**Interfaces:**
- Consumes: AMP block (`block_id: 1`, knobs: `Gain`, `Level`, `Bass`, `Mid`, `Treble`) and CAB block (`block_id: 5`, knobs: `Level`, `Low Cut`, `High Cut`) from RAM state.
- Produces: `renderAmpStage()` displaying the photorealistic vintage Amp head and stacked Speaker Cabinet with chicken-head knobs, glowing red jewel pilot lamp, power toggle, and tolex textures.

- [ ] **Step 1: Write the failing test in `tests/test_ui_assets.py`**

Add test method `test_photorealistic_amp_head_and_cab_stage` asserting:
1. `#amp-stage-view` container exists in `index.html`.
2. Required Amp Head elements exist: `.amp-head-enclosure`, `.amp-tolex`, `.amp-faceplate`, `.amp-model-badge`, `.amp-jewel-lamp`, `.amp-chicken-knobs`, `.amp-power-toggle`.
3. Required Cabinet elements exist: `.cab-enclosure`, `.cab-grille-cloth`, `.cab-piping`, `.cab-corners`, `.cab-knobs`.
4. The 5 physical AMP hardware knobs (`Gain`, `Level`, `Bass`, `Mid`, `Treble`) and CAB knobs (`Level`, `Low Cut`, `High Cut`) are rendered and wire to `queueKnobChange`.
5. Inert ghost controls (`Mono/Stereo`, `Standby`, `Presence`) are NOT present on the Amp head.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -W error -m unittest tests/test_ui_assets.py -k test_photorealistic_amp_head_and_cab_stage -v`
Expected: FAIL.

- [ ] **Step 3: Implement Amp Head and Cabinet stage markup, styling, and rendering**

1. In `index.html`: Inside `.main-stage`, add `<div id="amp-stage-view" class="amp-stage-view" hidden>` containing:
   - `.amp-head-enclosure`: Textured black vinyl tolex with white edge piping and corner chrome braces.
   - `.amp-faceplate`: Gold/silver anodized faceplate with dynamic model badge (`#amp-badge-text`), 5 chicken-head rotary knobs (`Gain`, `Level`, `Bass`, `Mid`, `Treble`), red glowing pilot jewel lamp (`#amp-jewel-lamp`), and heavy metal toggle switch (`#amp-power-toggle`).
   - `.cab-enclosure`: Stacked 4x12/2x12 speaker cabinet with dark basketweave cloth grille, chrome corner protectors, model badge, and rotary controls for `Level`, `Low Cut`, `High Cut`.
2. In `styles.css`: Add styles for vintage tolex texture (procedural CSS radial/repeating linear gradients), chicken-head knob shapes (`clip-path` polygon with pointer nose), faceted glass jewel pilot lamp with multi-layer box-shadow glow, and woven grille cloth.
3. In `app.js`: Implement `renderAmpStage()`:
   - Populates `#amp-badge-text` from `ampBlock.model_name`.
   - Generates interactive chicken-head rotary knobs for the 5 real AMP parameters and 3 CAB parameters.
   - Synchronizes jewel lamp glow and power toggle state with `ampBlock.enabled`.
   - Toggling the power switch calls `handleToggleBlock(1, !ampBlock.enabled)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -W error -m unittest tests/test_ui_assets.py -k test_photorealistic_amp_head_and_cab_stage -v`
Expected: PASS.
Run: `node --check me01_rig/static/app.js`
Expected: Returncode 0.

- [ ] **Step 5: Commit**

```bash
git add me01_rig/static/index.html me01_rig/static/styles.css me01_rig/static/app.js tests/test_ui_assets.py
git commit -m "feat(ui): implement photorealistic amp head and stacked speaker cabinet stage"
```

---

### Task 5: Section Navigation Tabs & Top Signal Flow Minimap

**Files:**
- Modify: `me01_rig/static/index.html:95-120`
- Modify: `me01_rig/static/styles.css:720-840`
- Modify: `me01_rig/static/app.js:1660-1740`
- Modify: `tests/test_ui_assets.py:250-290`

**Interfaces:**
- Consumes: Active RAM chain order (`ram.order`), block bypass states (`ram.blocks`).
- Produces: Section tabs (`#section-tabs` with `pedalera`, `pedales`, `amp`, `post-amp`), Signal Flow minimap (`#signal-flow-minimap`), and `setSectionTab(tabId)` function that dynamically filters visible blocks.

- [ ] **Step 1: Write the failing test in `tests/test_ui_assets.py`**

Add test method `test_section_tabs_and_signal_flow_minimap` asserting:
1. `#section-tabs` exists in `index.html` with buttons: `tab-pedalera`, `tab-pedales`, `tab-amp`, `tab-post-amp`.
2. `#signal-flow-minimap` exists in `index.html` with breadcrumb nodes from `IN` through all 6 blocks to `OUT`.
3. Minimap nodes display block tags, model names, and active/bypassed LED indicators.
4. Clicking a minimap node selects that block.
5. In `[Pedales]` view, blocks preceding `AMP` in the routing order are displayed.
6. In `[Post-amp]` view, blocks following `AMP` in the routing order are displayed.
7. In `[Amp]` view, the Amp Head + Cab stage is displayed (Review Focus 1).

- [ ] **Step 2: Run test to verify it fails**

Run: `python -W error -m unittest tests/test_ui_assets.py -k test_section_tabs_and_signal_flow_minimap -v`
Expected: FAIL.

- [ ] **Step 3: Implement section tabs, minimap breadcrumb, and dynamic chain filtering**

1. In `index.html`:
   - Add `#signal-flow-minimap` strip above the stage.
   - Add `#section-tabs` navigation bar with tabs: `[ (•) Pedalera ]`, `[ Pedales ]`, `[ Amp ]`, `[ Post-amp ]`.
2. In `styles.css`: Add styling for:
   - Capsule section tabs with active glow outline, smooth hover states, and keyboard focus rings.
   - Signal Flow minimap: sleek horizontal ribbon with illuminated circuit tracks, miniature stompbox chips, and status LEDs.
3. In `app.js`: Implement `setSectionTab(tabId)`:
   - Track `app.currentTab` (`"pedalera" | "pedales" | "amp" | "post-amp"`).
   - If `"amp"`, hide pedalboard stage, show `#amp-stage-view`, render Amp head & Cab.
   - If `"pedalera"`, show all 6 blocks on the pedalboard stage and draw patch cables.
   - If `"pedales"`, query `ampIdx = ram.order.indexOf(1)`; filter visible cards to blocks with `chainIdx < ampIdx` (Review Focus 1).
   - If `"post-amp"`, filter visible cards to blocks with `chainIdx > ampIdx` (Review Focus 1).
   - Render `#signal-flow-minimap` on every state change, reflecting current block order and bypass states. Clicking a chip selects the block and, if appropriate, switches to its section tab.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -W error -m unittest tests/test_ui_assets.py -k test_section_tabs_and_signal_flow_minimap -v`
Expected: PASS.
Run: `node --check me01_rig/static/app.js`
Expected: Returncode 0.

- [ ] **Step 5: Commit**

```bash
git add me01_rig/static/index.html me01_rig/static/styles.css me01_rig/static/app.js tests/test_ui_assets.py
git commit -m "feat(ui): implement section navigation tabs and signal flow minimap"
```

---

### Task 6: Effects Library Drawer & Collapsible Presets Bank Drawer

**Files:**
- Modify: `me01_rig/static/index.html:60-95, 170-205`
- Modify: `me01_rig/static/styles.css:840-1050`
- Modify: `me01_rig/static/app.js:1740-1840`
- Modify: `tests/test_ui_assets.py:270-320`

**Interfaces:**
- Consumes: All 43 ME-01 models across the 6 blocks (`BLOCK_CATALOG`, `AMPS_CATALOG`, `CABS_CATALOG`), active preset state (`presets_summary`), `/api/ram/model`.
- Produces: Slide-out Effects Library Drawer (`#effects-drawer`) with categories and search; Collapsible Presets Bank Drawer (`#presets-drawer`) with toggle button (`#btn-toggle-presets`); hotkeys `P` (presets) and `E` (effects).

- [ ] **Step 1: Write the failing test in `tests/test_ui_assets.py`**

Add test method `test_effects_library_and_presets_drawer` asserting:
1. `#effects-drawer` exists in `index.html` with search input `#effects-search` and accordion sections for: `dinamica`, `drive-amp`, `modulacion`, `delay`, `reverb`, `cab`.
2. Toggle buttons exist: `#btn-toggle-presets` and `#btn-toggle-effects`.
3. Keyboard shortcuts `P` and `E` toggle their respective drawers.
4. Clicking an effect tile dispatches `/api/ram/model` for the corresponding block type and updates the UI (Review Focus 4).
5. Opening/closing drawers preserves active preset selection and search query (Review Focus 5).

- [ ] **Step 2: Run test to verify it fails**

Run: `python -W error -m unittest tests/test_ui_assets.py -k test_effects_library_and_presets_drawer -v`
Expected: FAIL.

- [ ] **Step 3: Implement Effects Library Drawer, collapsible Presets Drawer, and hotkeys**

1. In `index.html`:
   - Refactor the left presets sidebar into a collapsible slide-out drawer `#presets-drawer` with open/close state.
   - Add `#btn-toggle-presets` button in the topbar.
   - Add `#effects-drawer` on the right side of `.workspace` with search bar `#effects-search`, category accordions, and close button.
   - Add `#btn-toggle-effects` button in the topbar.
2. In `styles.css`: Add styles for:
   - Slide-out drawers with smooth CSS transitions (`transform: translateX(...)`), dark blur backdrop, and scrollable content.
   - Effects library card tiles: miniature stompbox icons with model title, category tag, and firmware badge.
   - Active highlight on the model currently loaded in live RAM.
3. In `app.js`: Implement drawer logic:
   - Render categorized effect cards from `BLOCK_CATALOG`, `AMPS_CATALOG`, and `CABS_CATALOG`.
   - Implement real-time search filtering in `#effects-search`.
   - On clicking an effect card: identify target block (e.g. Phaser -> block 2 `MOD`, JCM800 -> block 1 `AMP`), select that block, call `apiSetRamModel(targetBlockId, modelIndex)`, and re-render (Review Focus 4).
   - Wire hotkeys: `P` toggles Presets drawer, `E` toggles Effects drawer, `Escape` closes any open drawer without disrupting active state (Review Focus 5).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -W error -m unittest tests/test_ui_assets.py -k test_effects_library_and_presets_drawer -v`
Expected: PASS.
Run: `node --check me01_rig/static/app.js`
Expected: Returncode 0.

- [ ] **Step 5: Commit**

```bash
git add me01_rig/static/index.html me01_rig/static/styles.css me01_rig/static/app.js tests/test_ui_assets.py
git commit -m "feat(ui): implement effects library drawer and collapsible presets drawer"
```

---

### Task 7: Full System Integration, Verification & Visual Polish

**Files:**
- Modify: `me01_rig/static/styles.css:1050-1200` (responsive adjustments, focus outlines, transitions)
- Modify: `tests/test_ui_assets.py` (comprehensive regression suite)
- Modify: `tests/test_e2e_mock.py` (end-to-end integration flow)

**Interfaces:**
- Consumes: Complete integrated UI (`index.html`, `styles.css`, `app.js`), `DeviceService`, `server.py`.
- Produces: Fully passing test suite (`32/32` existing + new asset and integration tests), clean syntax check, verified offline operation.

- [ ] **Step 1: Write comprehensive end-to-end integration test in `tests/test_ui_assets.py`**

Assert complete integration:
1. All static files exist, pass offline URL checks, and contain no `.innerHTML` / `insertAdjacentHTML`.
2. All 4 tabs (`pedalera`, `pedales`, `amp`, `post-amp`) render without runtime exceptions.
3. Patch cables draw correctly on demo data.
4. Amp head and Cab controls reflect live RAM parameters.
5. Effects drawer opens, lists 43 models, and maps clicks to `/api/ram/model`.
6. Full test run with `-W error` succeeds.

- [ ] **Step 2: Run test suite to verify full integration**

Run: `python -W error -m unittest discover -v`
Expected: All tests pass with zero warnings or errors.
Run: `node --check me01_rig/static/app.js`
Expected: Returncode 0.

- [ ] **Step 3: Perform live browser smoke test**

Start demo server and verify with PowerShell HTTP request that all assets serve with 200 OK, correct Content-Type headers, and expected skeuomorphic DOM elements.

- [ ] **Step 4: Commit**

```bash
git add me01_rig/static/styles.css tests/test_ui_assets.py tests/test_e2e_mock.py
git commit -m "feat(ui): complete skeuomorphic visual overhaul integration and verification"
```

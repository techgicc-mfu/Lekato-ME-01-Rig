(() => {
  "use strict";

  const POLL_INTERVAL_MS = 1600;
  const POLL_SUPPRESS_MS = 1200;
  const KNOB_THROTTLE_MS = 50;
  const TAP_RESET_MS = 2500;
  const FACTORY_SLOT_COUNT = 40;
  const TOTAL_SLOTS = 80;

  const BLOCK_CATALOG = {
    0: {
      blockId: 0,
      name: "FX",
      baseAddr: 0x14,
      colorVar: "var(--block-fx)",
      models: {
        0: { id: 0, name: "Noise Gate++", knobs: ["Gate"], minFw: null },
        1: { id: 1, name: "Boost", knobs: ["Gate", "Gain"], minFw: null },
        2: { id: 2, name: "Compress", knobs: ["Gate", "Sustain", "Attack", "Level"], minFw: null },
        3: { id: 3, name: "AI Gate MS", knobs: ["Gate", "Bias"], minFw: 17 },
      },
    },
    1: {
      blockId: 1,
      name: "AMP",
      baseAddr: 0x20,
      colorVar: "var(--block-amp)",
      knobs: ["Gain", "Level", "Bass", "Mid", "Treble"],
    },
    2: {
      blockId: 2,
      name: "MOD",
      baseAddr: 0x2c,
      colorVar: "var(--block-mod)",
      models: {
        0: { id: 0, name: "Chorus", knobs: ["Speed", "Depth", "Mix"], minFw: null },
        1: { id: 1, name: "Phaser", knobs: ["Speed", "Midcut", "Reso", "Feedback"], minFw: null },
        2: { id: 2, name: "Tremolo", knobs: ["Speed", "Depth", "Level"], minFw: null },
        3: { id: 3, name: "Flanger", knobs: ["Speed", "Depth", "Feedback", "Mix"], minFw: null },
        4: { id: 4, name: "Vibrato", knobs: ["Speed", "Depth"], minFw: null },
        5: { id: 5, name: "Univibe", knobs: ["Speed", "Depth", "Mix"], minFw: null },
        6: { id: 6, name: "Autofilter", knobs: ["Speed", "Min", "Max", "Mix", "Feedback"], minFw: null },
      },
    },
    3: {
      blockId: 3,
      name: "DLY",
      baseAddr: 0x38,
      colorVar: "var(--block-dly)",
      models: {
        0: { id: 0, name: "Analog", knobs: ["Time", "Feedback", "Mix", "Phaser", "Pitch"], minFw: null },
        1: { id: 1, name: "Duck", knobs: ["Time", "Feedback", "Mix", "Unpack", "Speed", "Depth"], minFw: null },
        2: { id: 2, name: "Dtape", knobs: ["Time", "Feedback", "Mix", "Grit", "Speed", "Depth"], minFw: null },
        3: { id: 3, name: "Dual", knobs: ["Time", "Feedback", "Mix", "T-Mode", "Speed", "Depth"], minFw: null },
        4: { id: 4, name: "Lofi", knobs: ["Time", "Feedback", "Mix", "Grit", "Speed", "Depth"], minFw: null },
      },
    },
    4: {
      blockId: 4,
      name: "REV",
      baseAddr: 0x44,
      colorVar: "var(--block-rev)",
      models: {
        0: { id: 0, name: "Room", knobs: ["Decay", "Mix", "High Pass", "Low Pass", "Depth"], minFw: null },
        1: { id: 1, name: "Hall", knobs: ["Decay", "Mix", "High Pass", "Low Pass", "Depth"], minFw: null },
        2: { id: 2, name: "Swell", knobs: ["Decay", "Mix", "High Pass", "Low Pass", "Rise-T"], minFw: null },
        3: { id: 3, name: "Spring", knobs: ["Decay", "Mix", "High Pass", "Low Pass", "Combs"], minFw: null },
        4: { id: 4, name: "Shimmer", knobs: ["Decay", "Mix", "Tone", "Pitch", "Amount"], minFw: null },
        5: { id: 5, name: "Cloud", knobs: ["Decay", "Mix", "High Pass", "Low Pass", "Diffusion"], minFw: null },
      },
    },
    5: {
      blockId: 5,
      name: "CAB",
      baseAddr: 0x50,
      colorVar: "var(--block-cab)",
      knobs: ["Level", "Low Cut", "High Cut"],
    },
  };

  const app = {
    state: null,
    ports: [],
    presetsCache: [],
    selectedBlockId: 0,
    currentTab: "pedalera",
    bankFilter: "all",
    searchTerm: "",
    factoryUnlocked: false,
    activeDragAddr: null,
    lastLocalEditMs: 0,
    draggedBlockId: null,
    knobQueue: new Map(),
    tapTimestamps: [],
    loadedBackup: null,
    backupDecodedSlots: [],
    backupSelectedSlots: new Set(),
    backupSlotStatus: new Map(),
    restoreRunning: false,
    restoreSummaryText: null,
    pollTimerId: null,
    pollInFlight: false,
    renderedInspectorKey: null,
    renderedInspectorBlockId: null,
    renderedInspectorNamesSig: null,
    knobInputsByAddr: new Map(),
    captureCategory: "amp",
    captureFilter: "all",
    captureSearch: "",
    captureRenamingSlot: null,
    curatedLibrary: null,
  };

  const els = {};

  function cacheElements() {
    const ids = [
      "conn-pill",
      "conn-label",
      "port-select",
      "btn-refresh-ports",
      "btn-connect",
      "btn-demo",
      "btn-disconnect",
      "active-slot-badge",
      "modified-pill",
      "patch-vol-slider",
      "patch-vol-number",
      "btn-refresh-ram",
      "btn-undo",
      "undo-depth-badge",
      "btn-revert",
      "btn-backup",
      "btn-save-slot",
      "error-banner",
      "error-banner-text",
      "btn-dismiss-error",
      "presets-drawer",
      "effects-drawer",
      "btn-toggle-presets",
      "btn-toggle-effects",
      "btn-close-effects",
      "effects-search",
      "effects-categories-list",
      "preset-count-badge",
      "preset-search",
      "chk-unlock-factory",
      "factory-unlock-warning",
      "preset-list",
      "chain-order-summary",
      "last-backup-note",
      "pedalboard-stage",
      "pedalboard-empty",
      "pedalboard-chain",
      "patch-cables-svg",
      "knob-floating-tooltip",
      "pedal-cards-row",
      "signal-flow-minimap",
      "section-tabs",
      "tab-pedalera",
      "tab-pedales",
      "tab-amp",
      "tab-post-amp",
      "amp-stage-view",
      "amp-model-badge",
      "amp-badge-text",
      "amp-chicken-knobs",
      "amp-jewel-lamp",
      "amp-power-toggle",
      "cab-badge-text",
      "cab-knobs",
      "btn-move-earlier",
      "btn-move-later",
      "btn-parallel-unsupported",
      "chain-position-bars",
      "inspector-empty",
      "inspector-content",
      "inspector-block-badge",
      "inspector-model-heading",
      "inspector-fw-badge",
      "inspector-block-subtitle",
      "btn-inspector-bypass",
      "inspector-model-select",
      "delay-tempo-strip",
      "dly-ms-readout",
      "dly-bpm-readout",
      "dly-bpm-input",
      "btn-dly-apply-bpm",
      "btn-tap-tempo",
      "tap-tempo-status",
      "cab-scale-note",
      "inspector-knobs",
      "tpl-pedal-stomp",
      "tpl-pedal-amp",
      "tpl-pedal-cab",
      "modal-save",
      "save-slot-select",
      "save-slot-notice",
      "save-factory-confirm-wrap",
      "chk-save-factory-confirm",
      "btn-confirm-save",
      "modal-revert",
      "revert-modal-desc",
      "btn-confirm-revert",
      "modal-backup",
      "btn-export-backup",
      "export-status-text",
      "backup-file-input",
      "backup-meta-summary",
      "backup-restore-controls",
      "btn-select-user-slots",
      "btn-select-changed-slots",
      "btn-select-all-slots",
      "btn-clear-slot-selection",
      "restore-progress-text",
      "restore-progress-bar",
      "backup-slots-list",
      "restore-factory-warning",
      "restore-factory-confirm-wrap",
      "chk-restore-factory-confirm",
      "btn-batch-restore",
      "btn-close-backup",
      "btn-open-capture-mgr",
      "btn-drawer-open-capture-mgr",
      "modal-capture-manager",
      "tab-cap-amps",
      "tab-cap-cabs",
      "capture-slot-search",
      "capture-slots-grid",
      "capture-library-panel",
      "capture-library-list",
      "capture-lib-count",
      "capture-file-dropzone",
      "capture-file-input",
      "capture-import-status",
      "toast-region",
    ];
    for (const id of ids) {
      els[id] = document.getElementById(id);
    }
  }

  function clampInt(val, min = 0, max = 100) {
    const num = Number(val);
    if (!Number.isFinite(num)) return min;
    return Math.max(min, Math.min(max, Math.round(num)));
  }

  function formatSlotLabel(slotId) {
    return `P${String(slotId + 1).padStart(2, "0")}`;
  }

  function delayRawToMs(raw, modelId) {
    return modelId === 3 ? Math.round(50 + raw * 4.5) : Math.round(100 + raw * 9.0);
  }

  function bpmToDelayRaw(bpm, modelId) {
    const ms = 60000.0 / bpm;
    const raw = modelId === 3 ? Math.round((ms - 50.0) / 4.5) : Math.round((ms - 100.0) / 9.0);
    return clampInt(raw, 0, 100);
  }

  function formatKnobDisplay(blockId, modelId, slot, raw) {
    const v = clampInt(raw, 0, 100);
    if (blockId === 5) {
      if (slot === 1) return `${Math.trunc(20 + v * 2.8)} Hz`;
      if (slot === 2) return `${(5.0 + v * 0.13).toFixed(1)} kHz`;
    }
    if (blockId === 3 && slot === 0) {
      return `${delayRawToMs(v, modelId)} ms`;
    }
    return String(v);
  }

  function getModelListForBlock(blockId, state) {
    const spec = BLOCK_CATALOG[blockId];
    if (!spec) return [];
    if (blockId === 1) {
      const names = Array.isArray(state?.amps) && state.amps.length === 20 ? state.amps : [];
      return Array.from({ length: 20 }, (_, i) => ({
        id: i,
        name: names[i] || `AMP ${i + 1}`,
        knobs: spec.knobs,
        minFw: null,
      }));
    }
    if (blockId === 5) {
      const names = Array.isArray(state?.cabs) && state.cabs.length === 20 ? state.cabs : [];
      return Array.from({ length: 20 }, (_, i) => ({
        id: i,
        name: names[i] || `CAB ${i + 1}`,
        knobs: spec.knobs,
        minFw: null,
      }));
    }
    return Object.values(spec.models).sort((a, b) => a.id - b.id);
  }

  function getBlockById(ram, blockId) {
    if (!ram || !Array.isArray(ram.blocks)) return null;
    return ram.blocks.find((b) => b.block_id === blockId) || ram.blocks[blockId] || null;
  }

  function setSliderVisual(slider, value) {
    const clamped = clampInt(value, 0, 100);
    slider.value = String(clamped);
    slider.style.setProperty("--pct", String(clamped));
  }

  function showToast(message, level = "info") {
    const toast = document.createElement("div");
    toast.className = `toast is-${level}`;
    toast.textContent = message;
    els["toast-region"].appendChild(toast);
    setTimeout(() => {
      toast.remove();
    }, 3800);
  }

  function showError(message) {
    if (!message) {
      els["error-banner"].hidden = true;
      els["error-banner-text"].textContent = "";
      return;
    }
    els["error-banner-text"].textContent = String(message);
    els["error-banner"].hidden = false;
  }

  async function apiRequest(method, path, body = undefined) {
    const options = {
      method,
      headers: {},
    };
    if (body !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }
    const resp = await fetch(path, options);
    const text = await resp.text();
    let data = {};
    if (text) {
      try {
        data = JSON.parse(text);
      } catch (_err) {
        throw new Error(`Invalid JSON response from ${path} (${resp.status})`);
      }
    }
    if (!resp.ok) {
      const errMsg = data && typeof data.error === "string" ? data.error : `HTTP ${resp.status}`;
      throw new Error(errMsg);
    }
    return data;
  }

  function hasPendingKnobWrites() {
    for (const entry of app.knobQueue.values()) {
      if (entry.timerId !== null || entry.inFlight || entry.queuedValue !== null) {
        return true;
      }
    }
    return false;
  }

  function isPollSuppressed() {
    if (app.activeDragAddr !== null) return true;
    if (hasPendingKnobWrites()) return true;
    return Date.now() - app.lastLocalEditMs < POLL_SUPPRESS_MS;
  }

  function markLocalEdit() {
    app.lastLocalEditMs = Date.now();
  }

  function clearKnobQueue() {
    for (const entry of app.knobQueue.values()) {
      if (entry.timerId !== null) {
        clearTimeout(entry.timerId);
      }
    }
    app.knobQueue.clear();
    app.activeDragAddr = null;
  }

  function applyServerState(nextState, { fromPoll = false, preserveLocalKnobs = false } = {}) {
    if (!nextState) return;
    if (fromPoll && isPollSuppressed()) return;

    if (preserveLocalKnobs && app.state?.ram && nextState.ram) {
      for (const [addr, entry] of app.knobQueue.entries()) {
        if (entry.timerId !== null || entry.queuedValue !== null || app.activeDragAddr === addr) {
          applyLocalKnobToState(nextState, addr, entry.value);
        }
      }
    }

    app.state = nextState;
    if (nextState.last_error) {
      showError(nextState.last_error);
    } else if (!fromPoll) {
      showError("");
    }
    renderAll();
  }

  function applyLocalKnobToState(targetState, addr, rawValue) {
    if (!targetState || !targetState.ram) return;
    const val = clampInt(rawValue, 0, 100);
    if (addr === 0) {
      targetState.ram.volume = val;
    } else {
      for (const block of targetState.ram.blocks) {
        const spec = BLOCK_CATALOG[block.block_id];
        if (!spec) continue;
        const slot = (addr - spec.baseAddr) / 2;
        if (Number.isInteger(slot) && slot >= 0 && slot < 6) {
          if (Array.isArray(targetState.ram.knobs?.[block.block_id])) {
            targetState.ram.knobs[block.block_id][slot] = val;
          }
          const knobObj = block.knobs.find((k) => k.addr === addr);
          if (knobObj) {
            knobObj.raw = val;
            knobObj.display = formatKnobDisplay(block.block_id, block.model_id, knobObj.slot, val);
          }
          break;
        }
      }
    }
  }

  function updateKnobVisualsInPlace(addr, rawValue, { fromLocal = false } = {}) {
    const val = clampInt(rawValue, 0, 100);
    if (addr === 0) {
      if (fromLocal || (app.activeDragAddr !== 0 && !app.knobQueue.has(0))) {
        setSliderVisual(els["patch-vol-slider"], val);
        if (document.activeElement !== els["patch-vol-number"]) {
          els["patch-vol-number"].value = String(val);
        }
      }
      return;
    }

    const refs = app.knobInputsByAddr.get(addr);
    if (refs) {
      if (!fromLocal && (app.activeDragAddr === addr || app.knobQueue.has(addr))) {
        return;
      }
      setSliderVisual(refs.slider, val);
      if (document.activeElement !== refs.numberInput) {
        refs.numberInput.value = String(val);
      }
      refs.unitDisplay.textContent = formatKnobDisplay(refs.blockId, refs.modelId, refs.slot, val);
      refs.rawBadge.textContent = `0x${addr.toString(16).padStart(2, "0")} · raw ${val}`;

      // Update mini SVG knob indicator on pedal card
      const deg = -135 + (val / 100) * 270;
      const pointer = els["pedal-cards-row"].querySelector(
        `.pedal-card[data-block-id="${refs.blockId}"] [data-knob-slot="${refs.slot}"]`
      );
      if (pointer) {
        const cx = pointer.getAttribute("data-cx");
        const cy = pointer.getAttribute("data-cy");
        const target = pointer.querySelector(".rotary-pointer-group") || pointer;
        target.setAttribute("transform", `rotate(${deg.toFixed(1)} ${cx} ${cy})`);
      }

      if (refs.blockId === 3 && refs.slot === 0) {
        updateDelayTempoReadout(val, refs.modelId);
      }
    }
  }

  function scheduleKnobWrite(addr, rawValue, immediate = false) {
    const val = clampInt(rawValue, 0, 100);
    markLocalEdit();

    if (app.state?.ram) {
      applyLocalKnobToState(app.state, addr, val);
      updateKnobVisualsInPlace(addr, val, { fromLocal: true });
    }

    let entry = app.knobQueue.get(addr);
    if (!entry) {
      entry = { value: val, timerId: null, inFlight: false, queuedValue: null };
      app.knobQueue.set(addr, entry);
    } else {
      entry.value = val;
    }

    if (entry.inFlight) {
      entry.queuedValue = val;
      return;
    }

    if (immediate) {
      if (entry.timerId !== null) {
        clearTimeout(entry.timerId);
        entry.timerId = null;
      }
      void flushKnobEntry(addr, entry);
      return;
    }

    if (entry.timerId === null) {
      entry.timerId = setTimeout(() => {
        entry.timerId = null;
        void flushKnobEntry(addr, entry);
      }, KNOB_THROTTLE_MS);
    }
  }

  async function flushKnobEntry(addr, entry) {
    if (app.knobQueue.get(addr) !== entry) return;
    const sendVal = entry.value;
    entry.inFlight = true;
    entry.queuedValue = null;
    markLocalEdit();
    try {
      const nextState = await apiRequest("POST", "/api/ram/knob", {
        addr,
        value: sendVal,
      });
      if (app.knobQueue.get(addr) !== entry) return;
      if (entry.queuedValue === null && entry.timerId === null) {
        applyServerState(nextState, { preserveLocalKnobs: true });
      }
    } catch (err) {
      if (app.knobQueue.get(addr) === entry) {
        showError(err.message);
      }
    } finally {
      entry.inFlight = false;
      if (app.knobQueue.get(addr) !== entry) return;
      if (entry.queuedValue !== null) {
        const nextVal = entry.queuedValue;
        entry.queuedValue = null;
        entry.value = nextVal;
        await flushKnobEntry(addr, entry);
      } else if (entry.timerId === null) {
        app.knobQueue.delete(addr);
      }
    }
  }

  function queueKnobChange(addr, rawValue, immediate = false) {
    scheduleKnobWrite(addr, rawValue, immediate);
  }

  async function refreshPorts() {
    try {
      const data = await apiRequest("GET", "/api/ports");
      app.ports = Array.isArray(data.ports) ? data.ports : [];
      renderPorts();
    } catch (err) {
      showError(err.message);
    }
  }

  async function refreshPresetsCatalog() {
    try {
      const data = await apiRequest("GET", "/api/presets");
      app.presetsCache = Array.isArray(data.presets) ? data.presets : [];
    } catch (_err) {
      app.presetsCache = [];
    }
  }

  async function refreshState({ silent = false, fromPoll = false } = {}) {
    if (fromPoll && (app.pollInFlight || isPollSuppressed() || app.restoreRunning)) {
      return;
    }
    if (fromPoll) {
      app.pollInFlight = true;
    }
    try {
      const nextState = await apiRequest("GET", "/api/state");
      applyServerState(nextState, { fromPoll, preserveLocalKnobs: true });
    } catch (err) {
      if (!silent && !fromPoll) {
        showError(err.message);
      }
    } finally {
      if (fromPoll) {
        app.pollInFlight = false;
      }
    }
  }

  async function handleConnect() {
    const selected = els["port-select"].value;
    const payload = { auto_backup: true };
    if (selected) {
      const [inStr, outStr] = selected.split(":");
      payload.in_id = Number(inStr);
      payload.out_id = Number(outStr);
    }
    setBusyButton(els["btn-connect"], true, "Connecting...");
    try {
      clearKnobQueue();
      const nextState = await apiRequest("POST", "/api/connect", payload);
      await refreshPresetsCatalog();
      applyServerState(nextState);
      showToast(`Connected to ${nextState.identity || "ME-01"}`, "success");
    } catch (err) {
      showError(err.message);
      showToast(err.message, "error");
    } finally {
      setBusyButton(els["btn-connect"], false, app.state?.connected ? "Reconnect" : "Connect");
    }
  }

  async function handleDisconnect() {
    try {
      clearKnobQueue();
      const nextState = await apiRequest("POST", "/api/disconnect", {});
      app.presetsCache = [];
      applyServerState(nextState);
      showToast("Disconnected from ME-01", "info");
    } catch (err) {
      showError(err.message);
    }
  }

  async function handleEnterDemo() {
    setBusyButton(els["btn-demo"], true, "Loading...");
    try {
      clearKnobQueue();
      const nextState = await apiRequest("POST", "/api/demo", {});
      await refreshPresetsCatalog();
      applyServerState(nextState);
      showToast("Demo Mode active (offline ME-01_016 snapshot)", "info");
    } catch (err) {
      showError(err.message);
    } finally {
      setBusyButton(els["btn-demo"], false, "Demo");
    }
  }

  async function handleLoadPreset(presetId) {
    try {
      clearKnobQueue();
      markLocalEdit();
      const nextState = await apiRequest("POST", "/api/preset/load", { preset_id: presetId });
      applyServerState(nextState);
    } catch (err) {
      showError(err.message);
      showToast(err.message, "error");
    }
  }

  async function handleRefreshRam() {
    try {
      clearKnobQueue();
      const nextState = await apiRequest("POST", "/api/ram/refresh", {});
      applyServerState(nextState);
      showToast("RAM synced from pedal", "success");
    } catch (err) {
      showError(err.message);
    }
  }

  async function handleUndo() {
    try {
      clearKnobQueue();
      markLocalEdit();
      const nextState = await apiRequest("POST", "/api/ram/undo", {});
      applyServerState(nextState);
    } catch (err) {
      showError(err.message);
    }
  }

  async function handleConfirmRevert() {
    closeModal("modal-revert");
    try {
      clearKnobQueue();
      markLocalEdit();
      const nextState = await apiRequest("POST", "/api/ram/revert", {});
      applyServerState(nextState);
      showToast(`Reverted RAM to ${formatSlotLabel(nextState.active_preset)}`, "info");
    } catch (err) {
      showError(err.message);
    }
  }

  async function handleToggleBlock(blockId, enabled) {
    try {
      markLocalEdit();
      const nextState = await apiRequest("POST", "/api/ram/toggle", {
        block_id: blockId,
        enabled: Boolean(enabled),
      });
      applyServerState(nextState, { preserveLocalKnobs: true });
    } catch (err) {
      showError(err.message);
    }
  }

  async function handleChangeModel(blockId, modelId) {
    try {
      markLocalEdit();
      const nextState = await apiRequest("POST", "/api/ram/model", {
        block_id: blockId,
        model_id: modelId,
      });
      applyServerState(nextState);
    } catch (err) {
      showError(err.message);
    }
  }

  async function handleReorder(newOrder) {
    if (!app.state?.ram) return;
    markLocalEdit();
    // Optimistically update local order for immediate visual feedback
    const prevOrder = [...app.state.ram.order];
    app.state.ram.order = [...newOrder];
    renderPedalboard();
    renderInspectorSubtitle();
    try {
      const nextState = await apiRequest("POST", "/api/ram/order", { order: newOrder });
      applyServerState(nextState, { preserveLocalKnobs: true });
    } catch (err) {
      app.state.ram.order = prevOrder;
      renderPedalboard();
      showError(err.message);
    }
  }

  function shiftSelectedBlock(delta) {
    const order = app.state?.ram?.order;
    if (!Array.isArray(order)) return;
    const idx = order.indexOf(app.selectedBlockId);
    if (idx < 0) return;
    const targetIdx = idx + delta;
    if (targetIdx < 0 || targetIdx >= order.length) return;
    const nextOrder = [...order];
    const [moved] = nextOrder.splice(idx, 1);
    nextOrder.splice(targetIdx, 0, moved);
    void handleReorder(nextOrder);
  }

  function handleTapTempo() {
    const ram = app.state?.ram;
    if (!ram) return;
    const dlyBlock = getBlockById(ram, 3);
    if (!dlyBlock) return;

    const now = Date.now();
    if (
      app.tapTimestamps.length > 0 &&
      now - app.tapTimestamps[app.tapTimestamps.length - 1] > TAP_RESET_MS
    ) {
      app.tapTimestamps = [];
    }
    app.tapTimestamps.push(now);
    if (app.tapTimestamps.length > 7) {
      app.tapTimestamps.shift();
    }

    if (app.tapTimestamps.length < 2) {
      els["tap-tempo-status"].textContent = "Tap 1 recorded — tap again to calculate BPM";
      return;
    }

    let intervalSum = 0;
    for (let i = 1; i < app.tapTimestamps.length; i += 1) {
      intervalSum += app.tapTimestamps[i] - app.tapTimestamps[i - 1];
    }
    const avgMs = intervalSum / (app.tapTimestamps.length - 1);
    const bpm = Math.max(20, Math.min(1200, 60000.0 / avgMs));
    const raw = bpmToDelayRaw(bpm, dlyBlock.model_id);
    const snappedMs = delayRawToMs(raw, dlyBlock.model_id);
    const snappedBpm = 60000.0 / snappedMs;

    els["dly-bpm-input"].value = snappedBpm.toFixed(1);
    els["tap-tempo-status"].textContent = `${snappedBpm.toFixed(1)} BPM (${app.tapTimestamps.length} taps -> raw ${raw})`;
    scheduleKnobWrite(BLOCK_CATALOG[3].baseAddr, raw, true);
  }

  function handleApplyBpm() {
    const ram = app.state?.ram;
    if (!ram) return;
    const dlyBlock = getBlockById(ram, 3);
    if (!dlyBlock) return;
    const bpm = Number(els["dly-bpm-input"].value);
    if (!Number.isFinite(bpm) || bpm <= 0) {
      showToast("Enter a positive BPM value", "warn");
      return;
    }
    const raw = bpmToDelayRaw(bpm, dlyBlock.model_id);
    scheduleKnobWrite(BLOCK_CATALOG[3].baseAddr, raw, true);
  }

  function updateDelayTempoReadout(raw, modelId) {
    const ms = delayRawToMs(clampInt(raw, 0, 100), modelId);
    const bpm = 60000.0 / ms;
    els["dly-ms-readout"].textContent = `${ms} ms`;
    els["dly-bpm-readout"].textContent = `${bpm.toFixed(1)} BPM`;
    if (document.activeElement !== els["dly-bpm-input"]) {
      els["dly-bpm-input"].value = bpm.toFixed(1);
    }
  }

  function openSaveModal() {
    const st = app.state;
    if (!st || !st.ram) return;

    const select = els["save-slot-select"];
    select.replaceChildren();
    const summaries = Array.isArray(st.presets_summary) ? st.presets_summary : [];
    for (let i = 0; i < TOTAL_SLOTS; i += 1) {
      const opt = document.createElement("option");
      const summary = summaries[i];
      const isFactory = i < FACTORY_SLOT_COUNT;
      const ampLabel = summary?.amp_name ? ` · ${summary.amp_name}` : "";
      const lockSuffix = isFactory && !app.factoryUnlocked ? " [Factory Locked]" : isFactory ? " [Factory Unlocked]" : " [User]";
      opt.value = String(i);
      opt.textContent = `${formatSlotLabel(i)}${ampLabel}${lockSuffix}`;
      select.appendChild(opt);
    }

    const active = typeof st.active_preset === "number" ? st.active_preset : FACTORY_SLOT_COUNT;
    if (active < FACTORY_SLOT_COUNT && !app.factoryUnlocked) {
      select.value = String(FACTORY_SLOT_COUNT);
    } else {
      select.value = String(active);
    }
    els["chk-save-factory-confirm"].checked = false;
    updateSaveModalGuidance();
    openModal("modal-save");
  }

  function updateSaveModalGuidance() {
    const slotId = Number(els["save-slot-select"].value);
    const active = app.state?.active_preset;
    const isFactory = slotId < FACTORY_SLOT_COUNT;
    const notice = els["save-slot-notice"];
    const confirmWrap = els["save-factory-confirm-wrap"];
    const confirmChk = els["chk-save-factory-confirm"];
    const confirmBtn = els["btn-confirm-save"];

    notice.className = "modal-notice";
    if (isFactory && !app.factoryUnlocked) {
      notice.textContent = `${formatSlotLabel(slotId)} is a locked Factory slot. Enable "Unlock Factory Slots" in the sidebar or select a User slot (P41–P80).`;
      notice.classList.add("is-warning");
      notice.hidden = false;
      confirmWrap.hidden = true;
      confirmBtn.disabled = true;
      return;
    }

    if (isFactory && app.factoryUnlocked) {
      notice.textContent = `Factory overwrite enabled for ${formatSlotLabel(slotId)} (allow_factory: true). A pre-save backup will be created before writing flash.`;
      notice.classList.add("is-warning");
      notice.hidden = false;
      confirmWrap.hidden = false;
      confirmBtn.disabled = !confirmChk.checked;
      return;
    }

    confirmWrap.hidden = true;
    confirmBtn.disabled = false;
    if (typeof active === "number" && active < FACTORY_SLOT_COUNT && !app.factoryUnlocked) {
      notice.textContent = `Active slot ${formatSlotLabel(active)} is a protected Factory slot. Pre-selecting User slot ${formatSlotLabel(slotId)} instead.`;
      notice.hidden = false;
    } else {
      notice.hidden = true;
    }
  }

  async function handleConfirmSave() {
    const slotId = Number(els["save-slot-select"].value);
    const allowFactory = slotId < FACTORY_SLOT_COUNT && app.factoryUnlocked;
    setBusyButton(els["btn-confirm-save"], true, "Saving & Verifying...");
    try {
      const saved = await apiRequest("POST", "/api/flash/save", {
        preset_id: slotId,
        allow_factory: allowFactory,
      });
      closeModal("modal-save");
      applyServerState(saved);
      showToast(`Saved & verified ${saved.label || formatSlotLabel(slotId)}`, "success");
    } catch (err) {
      showError(err.message);
      showToast(err.message, "error");
    } finally {
      setBusyButton(els["btn-confirm-save"], false, "Confirm Save to Flash");
      updateSaveModalGuidance();
    }
  }

  function openRevertModal() {
    const active = app.state?.active_preset;
    const label = typeof active === "number" ? formatSlotLabel(active) : "active slot";
    els["revert-modal-desc"].textContent = `Reload ${label} from flash into live RAM? All unsaved edits in live RAM will be discarded.`;
    openModal("modal-revert");
  }

  function openBackupModal() {
    if (app.state?.last_backup_path) {
      els["export-status-text"].textContent = `Latest safety backup on disk: ${app.state.last_backup_path}`;
    } else {
      els["export-status-text"].textContent = "";
    }
    els["chk-restore-factory-confirm"].checked = false;
    renderBackupModalList();
    openModal("modal-backup");
  }

  async function handleExportBackup() {
    if (app.restoreRunning) return;
    setBusyButton(els["btn-export-backup"], true, "Exporting...");
    try {
      const data = await apiRequest("GET", "/api/backup/export");
      const stamp = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
      const downloadName = `me01-backup-${stamp}.json`;
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = downloadName;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);

      if (data.path) {
        if (app.state) {
          app.state.last_backup_path = data.path;
          renderTopBar();
          renderBackupNote();
        }
        els["export-status-text"].textContent = `Exported to ${downloadName} (saved on disk at ${data.path})`;
      } else {
        els["export-status-text"].textContent = `Exported ${downloadName}`;
      }
      showToast(`Backup exported (${downloadName})`, "success");
    } catch (err) {
      showError(err.message);
    } finally {
      setBusyButton(els["btn-export-backup"], false, "Export Backup JSON");
    }
  }

  function decodePresetHex(hexStr, ampsList, cabsList) {
    if (typeof hexStr !== "string" || hexStr.length !== 184 || !/^[0-9a-fA-F]+$/.test(hexStr)) {
      throw new Error("Invalid 92-byte preset hex string");
    }
    const bytes = new Uint8Array(92);
    for (let i = 0; i < 92; i += 1) {
      bytes[i] = parseInt(hexStr.slice(i * 2, i * 2 + 2), 16);
    }
    const volume = bytes[0] | (bytes[1] << 8);
    const states = Array.from(bytes.slice(8, 14));
    const models = Array.from(bytes.slice(14, 20));
    const ampName = ampsList?.[models[1]] || `AMP ${models[1] + 1}`;
    const cabName = cabsList?.[models[5]] || `CAB ${models[5] + 1}`;
    return {
      rawHex: hexStr.toLowerCase(),
      volume,
      states,
      models,
      ampName,
      cabName,
    };
  }

  function handleBackupFileSelected(event) {
    if (app.restoreRunning) {
      event.target.value = "";
      return;
    }
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const parsed = JSON.parse(String(reader.result || ""));
        if (!parsed || !Array.isArray(parsed.presets_hex) || parsed.presets_hex.length !== TOTAL_SLOTS) {
          throw new Error(`Backup JSON must contain a presets_hex array of ${TOTAL_SLOTS} slots.`);
        }
        const amps = Array.isArray(parsed.amps) && parsed.amps.length === 20 ? parsed.amps : app.state?.amps || [];
        const cabs = Array.isArray(parsed.cabs) && parsed.cabs.length === 20 ? parsed.cabs : app.state?.cabs || [];
        const decoded = parsed.presets_hex.map((hex) => decodePresetHex(hex, amps, cabs));

        app.loadedBackup = parsed;
        app.backupDecodedSlots = decoded;
        app.backupSelectedSlots = new Set();
        app.backupSlotStatus = new Map();
        app.restoreSummaryText = null;
        els["chk-restore-factory-confirm"].checked = false;
        els["restore-progress-bar"].style.width = "0%";
        els["restore-progress-text"].textContent = "0 selected";
        renderBackupModalList();
      } catch (err) {
        showToast(`Failed to parse backup: ${err.message}`, "error");
      }
    };
    reader.readAsText(file);
  }

  async function handleAuditionBackupSlot(slotId) {
    if (!app.loadedBackup) return;
    try {
      clearKnobQueue();
      markLocalEdit();
      const nextState = await apiRequest("POST", "/api/backup/audition", {
        backup: app.loadedBackup,
        preset_id: slotId,
      });
      applyServerState(nextState);
      showToast(`Auditioning backup ${formatSlotLabel(slotId)} in live RAM (flash untouched)`, "info");
    } catch (err) {
      showError(err.message);
      showToast(err.message, "error");
    }
  }

  async function handleBatchRestore() {
    if (!app.loadedBackup || app.restoreRunning) return;
    const slotIds = Array.from(app.backupSelectedSlots).sort((a, b) => a - b);
    if (slotIds.length === 0) return;

    const includesFactory = slotIds.some((id) => id < FACTORY_SLOT_COUNT);
    if (includesFactory && !app.factoryUnlocked) {
      showToast("Factory slots P01–P40 are locked. Unlock them or deselect factory slots.", "warn");
      return;
    }
    if (includesFactory && !els["chk-restore-factory-confirm"].checked) {
      showToast("Confirm overwriting unlocked Factory slots before running Batch Flash Restore.", "warn");
      return;
    }

    app.restoreRunning = true;
    app.restoreSummaryText = null;
    app.backupSlotStatus.clear();
    for (const id of slotIds) {
      app.backupSlotStatus.set(id, { state: "pending", text: "Pending" });
    }
    renderBackupModalList();

    let completed = 0;
    const total = slotIds.length;
    els["restore-progress-bar"].style.width = "0%";

    try {
      for (const slotId of slotIds) {
        app.backupSlotStatus.set(slotId, { state: "writing", text: "Writing..." });
        els["restore-progress-text"].textContent = `Restoring ${formatSlotLabel(slotId)} (${completed + 1}/${total})...`;
        renderBackupModalList();

        try {
          const result = await apiRequest("POST", "/api/backup/restore", {
            backup: app.loadedBackup,
            slot_ids: [slotId],
            allow_factory: slotId < FACTORY_SLOT_COUNT && app.factoryUnlocked,
          });
          completed += 1;
          app.backupSlotStatus.set(slotId, { state: "verified", text: "Verified" });
          app.restoreSummaryText = `${completed}/${total} verified`;
          els["restore-progress-bar"].style.width = `${Math.round((completed / total) * 100)}%`;
          els["restore-progress-text"].textContent = app.restoreSummaryText;
          applyServerState(result);
        } catch (err) {
          app.backupSlotStatus.set(slotId, { state: "failed", text: "Failed" });
          app.restoreSummaryText = `Stopped at ${formatSlotLabel(slotId)} (${completed}/${total} verified)`;
          els["restore-progress-text"].textContent = app.restoreSummaryText;
          showError(err.message);
          showToast(`Restore halted on ${formatSlotLabel(slotId)}: ${err.message}`, "error");
          break;
        }
      }

      if (completed === total) {
        app.restoreSummaryText = `${completed}/${total} verified`;
        showToast(`Batch Flash Restore verified ${total} slot(s).`, "success");
      }
    } finally {
      app.restoreRunning = false;
      renderBackupModalList();
    }
  }

  function renderBackupModalList() {
    const hasBackup = Boolean(app.loadedBackup && app.backupDecodedSlots.length === TOTAL_SLOTS);
    els["backup-meta-summary"].hidden = !hasBackup;
    els["backup-restore-controls"].hidden = !hasBackup;

    if (!hasBackup) {
      els["btn-batch-restore"].disabled = true;
      return;
    }

    const identity = app.loadedBackup.identity || "Unknown device";
    const createdAt = app.loadedBackup.created_at || "Unknown timestamp";
    const activeSlot =
      typeof app.loadedBackup.active_preset === "number"
        ? formatSlotLabel(app.loadedBackup.active_preset)
        : "--";
    els["backup-meta-summary"].textContent = `Identity: ${identity} | Created: ${createdAt} | Active at capture: ${activeSlot}`;

    const listEl = els["backup-slots-list"];
    listEl.replaceChildren();

    const currentSummaries = app.state?.presets_summary || [];
    for (let idx = 0; idx < app.backupDecodedSlots.length; idx += 1) {
      const slot = app.backupDecodedSlots[idx];
      const isFactory = idx < FACTORY_SLOT_COUNT;
      const isSelected = app.backupSelectedSlots.has(idx);
      const currentHex = currentSummaries[idx]?.raw_hex;
      const differs = Boolean(currentHex && currentHex.toLowerCase() !== slot.rawHex);

      const row = document.createElement("div");
      row.className = "backup-slot-row";

      const left = document.createElement("div");
      left.className = "backup-slot-left";

      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = isSelected;
      checkbox.disabled = app.restoreRunning;
      checkbox.setAttribute("aria-label", `Select ${formatSlotLabel(idx)} for restore`);
      checkbox.addEventListener("change", () => {
        app.restoreSummaryText = null;
        if (checkbox.checked) {
          app.backupSelectedSlots.add(idx);
        } else {
          app.backupSelectedSlots.delete(idx);
        }
        updateBackupRestoreButtons();
      });

      const info = document.createElement("div");
      info.className = "backup-slot-info";

      const title = document.createElement("div");
      title.className = "backup-slot-title";

      const code = document.createElement("span");
      code.className = "preset-slot-code";
      code.textContent = formatSlotLabel(idx);
      title.appendChild(code);

      const bankTag = document.createElement("span");
      bankTag.className = `bank-pill ${isFactory ? "is-factory" : "is-user"}`;
      bankTag.textContent = isFactory ? "Factory" : "User";
      title.appendChild(bankTag);

      if (isFactory && !app.factoryUnlocked) {
        const lock = document.createElement("span");
        lock.className = "lock-tag";
        lock.textContent = "Locked";
        title.appendChild(lock);
      }

      if (differs) {
        const diffTag = document.createElement("span");
        diffTag.className = "modified-pill";
        diffTag.textContent = "Differs";
        title.appendChild(diffTag);
      }

      const sub = document.createElement("div");
      sub.className = "backup-slot-sub";
      sub.textContent = `${slot.ampName} / ${slot.cabName} · Vol ${slot.volume}`;

      info.append(title, sub);
      left.append(checkbox, info);

      const actions = document.createElement("div");
      actions.className = "backup-slot-actions";

      const status = app.backupSlotStatus.get(idx);
      if (status) {
        const pill = document.createElement("span");
        pill.className = `restore-status-pill is-${status.state}`;
        pill.textContent = status.text;
        actions.appendChild(pill);
      }

      const auditionBtn = document.createElement("button");
      auditionBtn.type = "button";
      auditionBtn.className = "btn btn-ghost btn-sm";
      auditionBtn.textContent = "Audition in RAM";
      auditionBtn.disabled = app.restoreRunning || (!app.state?.connected && !app.state?.demo);
      auditionBtn.addEventListener("click", () => {
        void handleAuditionBackupSlot(idx);
      });
      actions.appendChild(auditionBtn);

      row.append(left, actions);
      listEl.appendChild(row);
    }

    updateBackupRestoreButtons();
  }

  function updateBackupRestoreButtons() {
    const selected = Array.from(app.backupSelectedSlots);
    const hasFactory = selected.some((id) => id < FACTORY_SLOT_COUNT);
    const warning = els["restore-factory-warning"];

    if (!app.restoreRunning) {
      els["restore-progress-text"].textContent =
        app.restoreSummaryText || `${selected.length} selected`;
    }

    const confirmWrap = els["restore-factory-confirm-wrap"];
    const confirmChk = els["chk-restore-factory-confirm"];

    if (hasFactory && !app.factoryUnlocked) {
      warning.textContent =
        'Selection includes locked Factory slots (P01–P40). Enable "Unlock Factory Slots" in the sidebar or deselect factory slots.';
      warning.hidden = false;
      confirmWrap.hidden = true;
    } else if (hasFactory && app.factoryUnlocked) {
      warning.textContent =
        "Factory slots P01–P40 unlocked: Batch Flash Restore will write selected factory slots with pre-restore backup and read-back verify.";
      warning.hidden = false;
      confirmWrap.hidden = false;
    } else {
      warning.hidden = true;
      confirmWrap.hidden = true;
      confirmChk.checked = false;
    }

    const sessionActive = Boolean(app.state?.connected || app.state?.demo);
    const factoryNeedsConfirm = hasFactory && (!app.factoryUnlocked || !confirmChk.checked);
    els["btn-batch-restore"].disabled =
      app.restoreRunning || !sessionActive || selected.length === 0 || factoryNeedsConfirm;
    els["btn-close-backup"].disabled = app.restoreRunning;
    els["btn-export-backup"].disabled = app.restoreRunning;
    els["backup-file-input"].disabled = app.restoreRunning;
    const fileLabel = els["backup-file-input"].closest("label");
    if (fileLabel) {
      fileLabel.style.opacity = app.restoreRunning ? "0.42" : "";
      fileLabel.style.pointerEvents = app.restoreRunning ? "none" : "";
    }
    els["btn-select-user-slots"].disabled = app.restoreRunning;
    els["btn-select-changed-slots"].disabled = app.restoreRunning;
    els["btn-select-all-slots"].disabled = app.restoreRunning;
    els["btn-clear-slot-selection"].disabled = app.restoreRunning;
  }

  function openModal(id) {
    const el = els[id];
    if (el) el.hidden = false;
  }

  function closeModal(id) {
    if (id === "modal-backup" && app.restoreRunning) return;
    const el = els[id];
    if (el) el.hidden = true;
  }

  function setBusyButton(btn, busy, label) {
    if (!btn) return;
    btn.disabled = busy;
    btn.textContent = label;
  }

  function openCaptureManager(category = "amp") {
    app.captureCategory = category;
    app.captureRenamingSlot = null;
    updateCaptureTabs();
    openModal("modal-capture-manager");
    renderCaptureManagerSlots();
    if (!app.curatedLibrary) {
      void fetchCuratedLibrary();
    } else {
      renderCaptureLibrary();
    }
  }

  function closeCaptureManager() {
    app.captureRenamingSlot = null;
    closeModal("modal-capture-manager");
  }

  function updateCaptureTabs() {
    const isAmp = app.captureCategory === "amp";
    if (els["tab-cap-amps"]) {
      els["tab-cap-amps"].classList.toggle("is-active", isAmp);
      els["tab-cap-amps"].setAttribute("aria-selected", String(isAmp));
    }
    if (els["tab-cap-cabs"]) {
      els["tab-cap-cabs"].classList.toggle("is-active", !isAmp);
      els["tab-cap-cabs"].setAttribute("aria-selected", String(!isAmp));
    }
  }

  async function fetchCuratedLibrary() {
    try {
      const data = await apiRequest("GET", "/api/models/library");
      app.curatedLibrary = data.library || null;
      renderCaptureLibrary();
    } catch (err) {
      console.warn("Failed to fetch curated library:", err);
    }
  }

  function renderCaptureManagerSlots() {
    const grid = els["capture-slots-grid"];
    if (!grid) return;
    grid.replaceChildren();

    const isAmp = app.captureCategory === "amp";
    const slots = isAmp ? (app.state?.amps || []) : (app.state?.cabs || []);
    const activeBlockId = isAmp ? 1 : 5;
    const activeBlock = getBlockById(app.state?.ram, activeBlockId);
    const activeModelId = activeBlock ? activeBlock.model_id : -1;

    const searchTerm = (app.captureSearch || "").trim().toLowerCase();
    const filter = app.captureFilter || "all";

    for (let slotIndex = 0; slotIndex < 20; slotIndex++) {
      const rawName = slots[slotIndex] || `Slot ${slotIndex + 1}`;
      const displayName = rawName.trim();
      const isActive = slotIndex === activeModelId;

      if (searchTerm && !displayName.toLowerCase().includes(searchTerm)) {
        continue;
      }
      if (filter !== "all") {
        const lowerName = displayName.toLowerCase();
        let matchesFilter = false;
        if (filter === "Overdrive" && (lowerName.includes("ts") || lowerName.includes("od") || lowerName.includes("rat") || lowerName.includes("ds") || lowerName.includes("dri") || lowerName.includes("dist") || lowerName.includes("gv2"))) {
          matchesFilter = true;
        } else if (filter === "Clean" && (lowerName.includes("clean") || lowerName.includes("twin") || lowerName.includes("delux") || lowerName.includes("ac30") || lowerName.includes("jc") || lowerName.includes("fend"))) {
          matchesFilter = true;
        } else if (filter === "Crunch" && (lowerName.includes("crunch") || lowerName.includes("plexi") || lowerName.includes("800") || lowerName.includes("brit") || lowerName.includes("jcm"))) {
          matchesFilter = true;
        } else if (filter === "High Gain" && (lowerName.includes("rect") || lowerName.includes("5150") || lowerName.includes("diez") || lowerName.includes("fire") || lowerName.includes("lead") || lowerName.includes("savage") || lowerName.includes("hiwatt"))) {
          matchesFilter = true;
        } else if (filter === "Bass" && (lowerName.includes("bass") || lowerName.includes("ampeg") || lowerName.includes("svt") || lowerName.includes("b15"))) {
          matchesFilter = true;
        }
        if (!matchesFilter && isAmp) continue;
      }

      const card = document.createElement("div");
      card.className = "capture-slot-card" + (isActive ? " is-active" : "");

      const header = document.createElement("div");
      header.className = "capture-slot-header";

      const badgeLed = document.createElement("div");
      badgeLed.className = "capture-slot-badge-led";

      const badge = document.createElement("span");
      badge.className = "capture-slot-badge";
      badge.textContent = String(slotIndex + 1).padStart(2, "0");

      const led = document.createElement("span");
      led.className = "capture-slot-led" + (isActive ? " is-lit" : "");

      badgeLed.appendChild(badge);
      badgeLed.appendChild(led);
      header.appendChild(badgeLed);

      const actions = document.createElement("div");
      actions.className = "capture-slot-actions";

      const auditionBtn = document.createElement("button");
      auditionBtn.type = "button";
      auditionBtn.className = "capture-audition-btn";
      auditionBtn.title = "Audicionar en vivo (RAM)";
      auditionBtn.textContent = "🔊 Audition";
      auditionBtn.addEventListener("click", (ev) => {
        ev.stopPropagation();
        void auditionCaptureSlot(app.captureCategory, slotIndex);
      });

      const renameBtn = document.createElement("button");
      renameBtn.type = "button";
      renameBtn.className = "capture-rename-btn";
      renameBtn.title = "Renombrar slot";
      renameBtn.textContent = "✏️ Rename";
      renameBtn.addEventListener("click", (ev) => {
        ev.stopPropagation();
        app.captureRenamingSlot = slotIndex;
        renderCaptureManagerSlots();
      });

      actions.appendChild(auditionBtn);
      actions.appendChild(renameBtn);
      header.appendChild(actions);
      card.appendChild(header);

      const body = document.createElement("div");
      body.className = "capture-slot-body";

      if (app.captureRenamingSlot === slotIndex) {
        const input = document.createElement("input");
        input.type = "text";
        input.className = "capture-rename-input";
        input.value = displayName;
        input.maxLength = 13;
        input.addEventListener("keydown", (ev) => {
          if (ev.key === "Enter") {
            ev.preventDefault();
            const val = input.value.trim();
            if (val) {
              void renameCaptureSlot(app.captureCategory, slotIndex, val);
            }
          } else if (ev.key === "Escape") {
            ev.preventDefault();
            app.captureRenamingSlot = null;
            renderCaptureManagerSlots();
          }
        });
        input.addEventListener("blur", () => {
          if (app.captureRenamingSlot === slotIndex) {
            app.captureRenamingSlot = null;
            renderCaptureManagerSlots();
          }
        });
        body.appendChild(input);
        window.requestAnimationFrame(() => input.focus());
      } else {
        const nameEl = document.createElement("div");
        nameEl.className = "capture-slot-name";
        nameEl.textContent = displayName;
        nameEl.title = "Doble clic para renombrar";
        nameEl.addEventListener("dblclick", () => {
          app.captureRenamingSlot = slotIndex;
          renderCaptureManagerSlots();
        });
        body.appendChild(nameEl);

        const meta = document.createElement("div");
        meta.className = "capture-slot-meta";

        const tag = document.createElement("span");
        tag.className = "capture-slot-tag";
        tag.textContent = isAmp ? "Preamp / Capture" : "Cabinet IR";

        const statusNote = document.createElement("span");
        statusNote.textContent = isActive ? "ACTIVO EN RAM" : "";
        if (isActive) statusNote.style.color = "var(--accent-cyan)";

        meta.appendChild(tag);
        meta.appendChild(statusNote);
        body.appendChild(meta);
      }

      card.appendChild(body);
      grid.appendChild(card);
    }
  }

  async function auditionCaptureSlot(category, slotIndex) {
    try {
      const res = await apiRequest("POST", "/api/models/audition", {
        category,
        slot: slotIndex,
      });
      if (res && res.state) {
        app.state = res.state;
        renderAll();
        showToast(`Audicionando Slot ${slotIndex + 1} en RAM`, "success");
      }
    } catch (err) {
      showToast(`Error al audicionar slot: ${err.message}`, "error");
    }
  }

  async function renameCaptureSlot(category, slotIndex, newName) {
    try {
      const res = await apiRequest("POST", "/api/models/rename", {
        category,
        slot: slotIndex,
        name: newName,
      });
      if (res && res.state) {
        app.state = res.state;
        app.captureRenamingSlot = null;
        renderAll();
        showToast(`Slot ${slotIndex + 1} renombrado a "${res.name}"`, "success");
      }
    } catch (err) {
      showToast(`Error al renombrar slot: ${err.message}`, "error");
    }
  }

  function renderCaptureLibrary() {
    const container = els["capture-library-list"];
    const countBadge = els["capture-lib-count"];
    if (!container || !app.curatedLibrary) return;
    container.replaceChildren();

    const isAmp = app.captureCategory === "amp";
    const categories = app.curatedLibrary.categories || [];
    let totalModels = 0;

    categories.forEach((cat) => {
      const catKind = cat.kind;
      if ((isAmp && catKind !== "amp") || (!isAmp && catKind !== "cab")) {
        return;
      }

      const groupTitle = document.createElement("div");
      groupTitle.className = "capture-lib-group-title";
      groupTitle.textContent = `${cat.name} (${cat.models.length})`;
      container.appendChild(groupTitle);

      cat.models.forEach((model) => {
        totalModels++;
        const item = document.createElement("div");
        item.className = "capture-lib-item";

        const info = document.createElement("div");
        info.className = "capture-lib-item-info";

        const name = document.createElement("div");
        name.className = "capture-lib-item-name";
        name.textContent = model.display_name ? `${model.display_name} (${model.name})` : model.name;

        const desc = document.createElement("div");
        desc.className = "capture-lib-item-desc";
        desc.textContent = model.desc || model.description || "";

        info.appendChild(name);
        info.appendChild(desc);
        item.appendChild(info);

        const activeBlockId = isAmp ? 1 : 5;
        const activeBlock = getBlockById(app.state?.ram, activeBlockId);
        const activeSlot = activeBlock ? activeBlock.model_id : 0;
        const slotLabel = `Slot ${String(activeSlot + 1).padStart(2, "0")}`;

        const assignBtn = document.createElement("button");
        assignBtn.type = "button";
        assignBtn.className = "capture-lib-assign-btn";
        assignBtn.textContent = `Asignar a ${slotLabel}`;
        assignBtn.title = `Asignar nombre "${model.name}" al ${slotLabel} activo en hardware`;
        assignBtn.addEventListener("click", () => {
          void renameCaptureSlot(app.captureCategory, activeSlot, model.name);
        });

        item.appendChild(assignBtn);
        container.appendChild(item);
      });
    });

    if (countBadge) {
      countBadge.textContent = String(totalModels);
    }
  }

  async function validateAndImportCapture(file) {
    const statusEl = els["capture-import-status"];
    if (!statusEl) return;
    statusEl.hidden = false;
    statusEl.textContent = `Validando ${file.name}...`;

    try {
      const b64 = await readFileAsBase64(file);
      const res = await apiRequest("POST", "/api/models/validate_import", {
        filename: file.name,
        content_base64: b64,
      });

      statusEl.replaceChildren();
      const pSuccess = document.createElement("div");
      pSuccess.style.color = "var(--success)";
      pSuccess.textContent = `✅ Archivo válido: ${file.name}`;
      statusEl.appendChild(pSuccess);

      const pDetails = document.createElement("div");
      const sampleCount = res.details.samples ?? res.details.total_samples ?? 0;
      const byteSize = res.details.size ?? res.details.payload_size ?? 0;
      if (res.kind === "cab" && res.details.sample_rate) {
        pDetails.textContent = `IR WAV: ${res.details.sample_rate} Hz, ${res.details.bits_per_sample}-bit, ${res.details.channels} ch, ${sampleCount} samples (${byteSize} bytes)`;
      } else {
        pDetails.textContent = `Captura AM4: Modelo "${res.details.name}", tamaño ${byteSize} bytes`;
      }
      statusEl.appendChild(pDetails);

      const isAmp = res.kind === "amp";
      const activeBlockId = isAmp ? 1 : 5;
      const activeBlock = getBlockById(app.state?.ram, activeBlockId);
      const activeSlot = activeBlock ? activeBlock.model_id : 0;
      const slotLabel = `Slot ${String(activeSlot + 1).padStart(2, "0")}`;

      const assignBtn = document.createElement("button");
      assignBtn.type = "button";
      assignBtn.className = "btn btn-primary btn-sm";
      assignBtn.style.marginTop = "6px";
      const detectedName = res.details.name || file.name.replace(/\.[^/.]+$/, "");
      assignBtn.textContent = `Asignar "${detectedName}" a ${slotLabel}`;
      assignBtn.addEventListener("click", () => {
        void renameCaptureSlot(res.kind, activeSlot, detectedName);
      });
      statusEl.appendChild(assignBtn);
      showToast(`Archivo validado: ${detectedName}`, "success");
    } catch (err) {
      statusEl.replaceChildren();
      const pError = document.createElement("div");
      pError.style.color = "var(--danger)";
      pError.textContent = `❌ Error de validación: ${err.message}`;
      statusEl.appendChild(pError);
      showToast(`Error al validar archivo: ${err.message}`, "error");
    }
  }

  function readFileAsBase64(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        const result = reader.result;
        if (typeof result === "string") {
          const commaIdx = result.indexOf(",");
          resolve(commaIdx >= 0 ? result.slice(commaIdx + 1) : result);
        } else {
          reject(new Error("Formato de lectura inesperado"));
        }
      };
      reader.onerror = () => reject(reader.error || new Error("Error leyendo archivo"));
      reader.readAsDataURL(file);
    });
  }

  function renderPorts() {
    const select = els["port-select"];
    const previous = select.value;
    select.replaceChildren();

    if (app.ports.length === 0) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "Auto-detect USB-MIDI";
      select.appendChild(opt);
      return;
    }

    for (const pair of app.ports) {
      const opt = document.createElement("option");
      opt.value = `${pair.in_id}:${pair.out_id}`;
      opt.textContent = `${pair.in_name} (${pair.in_id} / ${pair.out_id})`;
      select.appendChild(opt);
    }

    const activePorts = app.state?.ports;
    if (activePorts && typeof activePorts.in_id === "number" && typeof activePorts.out_id === "number") {
      const targetVal = `${activePorts.in_id}:${activePorts.out_id}`;
      if (Array.from(select.options).some((o) => o.value === targetVal)) {
        select.value = targetVal;
        return;
      }
    }
    if (previous && Array.from(select.options).some((o) => o.value === previous)) {
      select.value = previous;
    }
  }

  function renderTopBar() {
    const st = app.state;
    const connected = Boolean(st?.connected);
    const demo = Boolean(st?.demo);
    const sessionActive = connected || demo;

    const pill = els["conn-pill"];
    pill.classList.remove("is-connected", "is-demo", "is-disconnected");
    if (connected) {
      pill.classList.add("is-connected");
      els["conn-label"].textContent = `Connected: ${st.identity || "ME-01"}`;
    } else if (demo) {
      pill.classList.add("is-demo");
      els["conn-label"].textContent = `Demo Mode (${st.identity || "ME-01_016"})`;
    } else {
      pill.classList.add("is-disconnected");
      els["conn-label"].textContent = "Disconnected";
    }

    els["btn-connect"].textContent = connected ? "Reconnect" : "Connect";
    els["btn-disconnect"].hidden = !sessionActive;

    const activeSlot = st?.active_preset;
    els["active-slot-badge"].textContent =
      typeof activeSlot === "number" ? formatSlotLabel(activeSlot) : "--";
    els["modified-pill"].hidden = !st?.dirty_from_slot;

    const volume = st?.ram ? st.ram.volume : 0;
    els["patch-vol-slider"].disabled = !sessionActive || !st?.ram;
    els["patch-vol-number"].disabled = !sessionActive || !st?.ram;
    if (app.activeDragAddr !== 0 && !app.knobQueue.has(0)) {
      setSliderVisual(els["patch-vol-slider"], volume);
      if (document.activeElement !== els["patch-vol-number"]) {
        els["patch-vol-number"].value = String(volume);
      }
    }

    const undoDepth = Number(st?.undo_depth || 0);
    els["undo-depth-badge"].textContent = String(undoDepth);
    els["btn-refresh-ram"].disabled = !sessionActive;
    els["btn-undo"].disabled = !sessionActive || undoDepth === 0;
    els["btn-revert"].disabled = !sessionActive || typeof activeSlot !== "number";
    els["btn-backup"].disabled = !sessionActive;
    els["btn-save-slot"].disabled = !sessionActive || !st?.ram;
  }

  function renderBackupNote() {
    const path = app.state?.last_backup_path;
    els["last-backup-note"].textContent = path ? `Safety backup: ${path}` : "";
    els["last-backup-note"].title = path || "";
  }

  function renderSidebar() {
    const summaries = Array.isArray(app.state?.presets_summary) ? app.state.presets_summary : [];
    const query = app.searchTerm.trim().toLowerCase();
    const listEl = els["preset-list"];
    listEl.replaceChildren();

    const filtered = summaries.filter((item) => {
      if (app.bankFilter === "factory" && item.bank !== "factory") return false;
      if (app.bankFilter === "user" && item.bank !== "user") return false;
      if (!query) return true;
      const hay = `${item.label} ${item.amp_name} ${item.cab_name}`.toLowerCase();
      return hay.includes(query);
    });

    els["preset-count-badge"].textContent = String(filtered.length);
    els["factory-unlock-warning"].hidden = !app.factoryUnlocked;

    if (summaries.length === 0) {
      const empty = document.createElement("p");
      empty.className = "panel-subtitle";
      empty.textContent = "Connect to ME-01 or enter Demo Mode to load P01–P80 presets.";
      listEl.appendChild(empty);
      return;
    }

    for (const item of filtered) {
      const isActive = item.preset_id === app.state?.active_preset;
      const row = document.createElement("button");
      row.type = "button";
      row.className = `preset-row${isActive ? " is-active" : ""}`;
      row.setAttribute("role", "option");
      row.setAttribute("aria-selected", String(isActive));

      const top = document.createElement("div");
      top.className = "preset-row-top";

      const code = document.createElement("span");
      code.className = "preset-slot-code";
      code.textContent = item.label;
      top.appendChild(code);

      const badges = document.createElement("div");
      badges.className = "preset-badges";

      if (isActive && app.state?.dirty_from_slot) {
        const mod = document.createElement("span");
        mod.className = "modified-pill";
        mod.textContent = "Modified";
        badges.appendChild(mod);
      }

      if (item.bank === "factory" && !app.factoryUnlocked) {
        const lock = document.createElement("span");
        lock.className = "lock-tag";
        lock.textContent = "Locked";
        badges.appendChild(lock);
      }

      const bankPill = document.createElement("span");
      bankPill.className = `bank-pill ${item.bank === "factory" ? "is-factory" : "is-user"}`;
      bankPill.textContent = item.bank === "factory" ? "Factory" : "User";
      badges.appendChild(bankPill);
      top.appendChild(badges);

      const names = document.createElement("div");
      names.className = "preset-row-names";
      names.textContent = `${item.amp_name} · ${item.cab_name}`;

      const dots = document.createElement("div");
      dots.className = "preset-row-blocks";
      for (const blkId of item.order) {
        const spec = BLOCK_CATALOG[blkId];
        if (!spec) continue;
        const dot = document.createElement("span");
        const isOn = Boolean(item.states?.[blkId]);
        dot.className = `mini-block-dot${isOn ? " is-on" : ""}`;
        dot.style.setProperty("--dot-color", spec.colorVar);
        dot.textContent = spec.name;
        dots.appendChild(dot);
      }

      row.append(top, names, dots);
      row.addEventListener("click", () => {
        void handleLoadPreset(item.preset_id);
      });
      listEl.appendChild(row);
    }
  }

  function getPedalThemeClass(block) {
    const name = (block.model_name || "").toLowerCase();
    const bId = block.block_id;
    if (bId === 0) {
      if (name.includes("compress")) return "pedal-theme-silver-squeeze";
      if (name.includes("boost") || name.includes("drive")) return "pedal-theme-blues-racer";
      return "pedal-theme-smart-signal";
    }
    if (bId === 2) {
      if (name.includes("phase")) return "pedal-theme-phase-91";
      if (name.includes("flang")) return "pedal-theme-lightning-mistress";
      return "pedal-theme-double-vision";
    }
    if (bId === 3) return "pedal-theme-digital-echo";
    if (bId === 4) return "pedal-theme-reverb";
    return "";
  }

  function buildPedalSvg(block) {
    const spec = BLOCK_CATALOG[block.block_id];
    const tplId =
      block.block_id === 1
        ? "tpl-pedal-amp"
        : block.block_id === 5
          ? "tpl-pedal-cab"
          : els["tpl-pedal-skeuo"]
            ? "tpl-pedal-skeuo"
            : "tpl-pedal-stomp";
    const tpl = els[tplId];
    const svg = tpl.content.firstElementChild.cloneNode(true);
    const ns = svg.namespaceURI;
    const knobsLayer = svg.querySelector(".svg-knobs-layer");

    const themeClass = getPedalThemeClass(block);
    if (themeClass) {
      svg.classList.add(themeClass);
    }

    const titleEl = svg.querySelector(".svg-pedal-title");
    if (titleEl) {
      titleEl.textContent = block.model_name || spec?.name || "";
    }

    if (knobsLayer && block.block_id !== 5) {
      const knobs = block.knobs || [];
      if (block.block_id === 1) {
        knobs.forEach((knob, idx) => {
          const cx = 22 + idx * 19;
          const cy = 29;
          appendMiniKnobSvg(knobsLayer, ns, cx, cy, 6.2, knob.slot, knob.raw);
        });
      } else if (tplId === "tpl-pedal-skeuo") {
        const count = knobs.length;
        if (count === 1) {
          appendInteractiveKnobSvg(knobsLayer, ns, 65, 72, 13, knobs[0], block);
        } else if (count === 2) {
          appendInteractiveKnobSvg(knobsLayer, ns, 44, 72, 11, knobs[0], block);
          appendInteractiveKnobSvg(knobsLayer, ns, 86, 72, 11, knobs[1], block);
        } else if (count === 3) {
          appendInteractiveKnobSvg(knobsLayer, ns, 34, 72, 9.5, knobs[0], block);
          appendInteractiveKnobSvg(knobsLayer, ns, 65, 72, 9.5, knobs[1], block);
          appendInteractiveKnobSvg(knobsLayer, ns, 96, 72, 9.5, knobs[2], block);
        } else {
          const topCount = count <= 4 ? 2 : 3;
          knobs.forEach((knob, idx) => {
            const isSecondRow = idx >= topCount;
            const rowIndex = isSecondRow ? idx - topCount : idx;
            const rowTotal = isSecondRow ? count - topCount : topCount;
            const spacing = rowTotal === 1 ? 0 : rowTotal === 2 ? 40 : 31;
            const startX = 65 - ((rowTotal - 1) * spacing) / 2;
            const cx = startX + rowIndex * spacing;
            const cy = isSecondRow ? 91 : 57;
            appendInteractiveKnobSvg(knobsLayer, ns, cx, cy, 8.2, knob, block);
          });
        }
      } else {
        const count = knobs.length;
        const topCount = count <= 3 ? count : Math.ceil(count / 2);
        knobs.forEach((knob, idx) => {
          const isSecondRow = idx >= topCount;
          const rowIndex = isSecondRow ? idx - topCount : idx;
          const rowTotal = isSecondRow ? count - topCount : topCount;
          const spacing = rowTotal === 1 ? 0 : rowTotal === 2 ? 32 : 24;
          const startX = 54 - ((rowTotal - 1) * spacing) / 2;
          const cx = startX + rowIndex * spacing;
          const cy = count <= 3 ? 35 : isSecondRow ? 46 : 25;
          appendMiniKnobSvg(knobsLayer, ns, cx, cy, count <= 3 ? 8 : 6.8, knob.slot, knob.raw);
        });
      }
    }

    if (spec) {
      svg.style.setProperty("--block-color", spec.colorVar);
    }
    return svg;
  }

  function formatKnobValue(knob, raw) {
    const val = clampInt(raw, 0, knob.max ?? 100);
    if (!knob) return String(val);
    if (knob.unit === "ms") return `${val * 10} ms`;
    if (knob.unit === "Hz") return `${val * 2} Hz`;
    if (knob.unit === "kHz") return `${(5.0 + (val / 100) * 13.0).toFixed(1)} kHz`;
    if (knob.unit === "dB") return `${val - 50} dB`;
    return `${val}`;
  }

  let tooltipHideTimer = null;

  function showKnobTooltip(knobEl, label, formattedVal) {
    if (tooltipHideTimer) {
      clearTimeout(tooltipHideTimer);
      tooltipHideTimer = null;
    }
    const tooltip = els["knob-floating-tooltip"];
    if (!tooltip) return;
    const rect = knobEl.getBoundingClientRect();
    tooltip.style.left = `${rect.left + rect.width / 2}px`;
    tooltip.style.top = `${rect.top}px`;
    tooltip.replaceChildren();

    const lblSpan = document.createElement("span");
    lblSpan.className = "knob-tooltip-label";
    lblSpan.textContent = label;

    const valSpan = document.createElement("span");
    valSpan.className = "knob-tooltip-val";
    valSpan.textContent = formattedVal;

    tooltip.append(lblSpan, valSpan);
    tooltip.hidden = false;
  }

  function hideKnobTooltip() {
    if (tooltipHideTimer) clearTimeout(tooltipHideTimer);
    tooltipHideTimer = setTimeout(() => {
      const tooltip = els["knob-floating-tooltip"];
      if (tooltip) tooltip.hidden = true;
    }, 120);
  }

  function updateKnobAngle(pointerGroup, cx, cy, raw, maxVal = 100) {
    const deg = -135 + (clampInt(raw, 0, maxVal) / maxVal) * 270;
    pointerGroup.setAttribute("transform", `rotate(${deg.toFixed(1)} ${cx} ${cy})`);
  }

  function appendInteractiveKnobSvg(layer, ns, cx, cy, radius, knob, block) {
    const group = document.createElementNS(ns, "g");
    group.setAttribute("class", "rotary-knob-group");
    group.setAttribute("data-knob-slot", String(knob.slot));
    group.setAttribute("data-knob-addr", String(knob.addr));
    group.setAttribute("data-cx", String(cx));
    group.setAttribute("data-cy", String(cy));

    const knobLabel = knob.label || knob.name || "";

    const dial = document.createElementNS(ns, "circle");
    dial.setAttribute("cx", String(cx));
    dial.setAttribute("cy", String(cy));
    dial.setAttribute("r", String(radius));
    dial.setAttribute("class", "rotary-dial");

    const pointerGroup = document.createElementNS(ns, "g");
    pointerGroup.setAttribute("class", "rotary-pointer-group");
    const maxVal = knob.max ?? 100;
    updateKnobAngle(pointerGroup, cx, cy, knob.raw, maxVal);

    const notch = document.createElementNS(ns, "line");
    notch.setAttribute("x1", String(cx));
    notch.setAttribute("y1", String(cy));
    notch.setAttribute("x2", String(cx));
    notch.setAttribute("y2", String(cy - radius + 2));
    notch.setAttribute("class", "rotary-notch");

    const dot = document.createElementNS(ns, "circle");
    dot.setAttribute("cx", String(cx));
    dot.setAttribute("cy", String(cy - radius + 3));
    dot.setAttribute("r", String(Math.max(1.0, radius * 0.12)));
    dot.setAttribute("class", "rotary-dot");

    pointerGroup.append(notch, dot);

    const cap = document.createElementNS(ns, "circle");
    cap.setAttribute("cx", String(cx));
    cap.setAttribute("cy", String(cy));
    cap.setAttribute("r", String(radius * 0.42));
    cap.setAttribute("class", "rotary-knob-cap");

    group.append(dial, pointerGroup, cap);

    if (radius >= 8.5 && knobLabel) {
      const lbl = document.createElementNS(ns, "text");
      lbl.setAttribute("x", String(cx));
      lbl.setAttribute("y", String(cy + radius + 7));
      lbl.setAttribute("class", "rotary-knob-label");
      lbl.textContent = knobLabel.slice(0, 5);
      group.append(lbl);
    }

    const getTooltipDisplay = (raw) => {
      if (block && typeof formatKnobDisplay === "function") {
        return formatKnobDisplay(block.block_id, block.model_id, knob.slot, raw);
      }
      return formatKnobValue(knob, raw);
    };

    let isDragging = false;
    let startY = 0;
    let startVal = knob.raw;

    group.addEventListener("pointerdown", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      isDragging = true;
      startY = ev.clientY;
      startVal = knob.raw;
      group.setPointerCapture(ev.pointerId);
      group.classList.add("is-active");
      showKnobTooltip(group, knobLabel, getTooltipDisplay(knob.raw));
    });

    group.addEventListener("pointermove", (ev) => {
      if (!isDragging) return;
      ev.preventDefault();
      ev.stopPropagation();
      const deltaY = startY - ev.clientY;
      const nextVal = clampInt(Math.round(startVal + deltaY * 0.6), 0, maxVal);
      if (nextVal !== knob.raw) {
        knob.raw = nextVal;
        updateKnobAngle(pointerGroup, cx, cy, nextVal, maxVal);
        showKnobTooltip(group, knobLabel, getTooltipDisplay(nextVal));
        queueKnobChange(knob.addr, nextVal);
      }
    });

    const onPointerEnd = (ev) => {
      if (!isDragging) return;
      isDragging = false;
      try {
        group.releasePointerCapture(ev.pointerId);
      } catch (_) {}
      group.classList.remove("is-active");
      hideKnobTooltip();
      if (app.activeDragAddr === knob.addr) {
        app.activeDragAddr = null;
      }
      queueKnobChange(knob.addr, knob.raw, true);
    };

    group.addEventListener("pointerup", onPointerEnd);
    group.addEventListener("pointercancel", onPointerEnd);

    group.addEventListener("wheel", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      const step = ev.deltaY < 0 ? 1 : -1;
      const nextVal = clampInt(knob.raw + step, 0, maxVal);
      if (nextVal !== knob.raw) {
        knob.raw = nextVal;
        updateKnobAngle(pointerGroup, cx, cy, nextVal, maxVal);
        showKnobTooltip(group, knobLabel, getTooltipDisplay(nextVal));
        queueKnobChange(knob.addr, nextVal, true);
        hideKnobTooltip();
      }
    }, { passive: false });

    layer.append(group);
  }

  function appendMiniKnobSvg(layer, ns, cx, cy, radius, slot, raw) {
    const circle = document.createElementNS(ns, "circle");
    circle.setAttribute("cx", String(cx));
    circle.setAttribute("cy", String(cy));
    circle.setAttribute("r", String(radius));
    circle.setAttribute("class", "svg-knob-body");

    const deg = -135 + (clampInt(raw, 0, 100) / 100) * 270;
    const pointer = document.createElementNS(ns, "line");
    pointer.setAttribute("x1", String(cx));
    pointer.setAttribute("y1", String(cy));
    pointer.setAttribute("x2", String(cx));
    pointer.setAttribute("y2", String(cy - radius + 1.5));
    pointer.setAttribute("class", "svg-knob-pointer");
    pointer.setAttribute("data-knob-slot", String(slot));
    pointer.setAttribute("data-cx", String(cx));
    pointer.setAttribute("data-cy", String(cy));
    pointer.setAttribute("transform", `rotate(${deg.toFixed(1)} ${cx} ${cy})`);

    layer.append(circle, pointer);
  }

  function setSectionTab(tabId) {
    app.currentTab = tabId;
    ["pedalera", "pedales", "amp", "post-amp"].forEach((id) => {
      const btn = els[`tab-${id}`];
      if (btn) {
        const active = id === tabId;
        btn.classList.toggle("is-active", active);
        btn.setAttribute("aria-selected", String(active));
      }
    });

    const isAmpView = tabId === "amp";
    const boardPanel = document.querySelector(".pedalboard-panel");
    if (boardPanel) {
      boardPanel.hidden = isAmpView;
    }
    if (els["amp-stage-view"]) {
      els["amp-stage-view"].hidden = !isAmpView;
    }

    if (isAmpView) {
      renderAmpStage();
    } else {
      renderPedalboard();
    }
    renderSignalFlowMinimap();
  }

  function renderSignalFlowMinimap() {
    const minimap = els["signal-flow-minimap"];
    if (!minimap) return;
    minimap.replaceChildren();

    const ram = app.state?.ram;
    if (!ram || !Array.isArray(ram.order)) return;

    const inNode = document.createElement("span");
    inNode.className = "minimap-node";
    inNode.textContent = "IN";
    minimap.appendChild(inNode);

    const arrow1 = document.createElement("span");
    arrow1.className = "minimap-arrow";
    arrow1.textContent = "→";
    minimap.appendChild(arrow1);

    ram.order.forEach((blockId, idx) => {
      const block = getBlockById(ram, blockId);
      const spec = BLOCK_CATALOG[blockId];
      if (!block || !spec) return;

      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = `minimap-chip${blockId === app.selectedBlockId ? " is-selected" : ""}${block.enabled ? "" : " is-bypassed"}`;
      chip.setAttribute("data-block-id", String(blockId));
      chip.setAttribute("aria-label", `${block.name} ${block.model_name}`);

      const led = document.createElement("span");
      led.className = "minimap-led";

      const txt = document.createElement("span");
      txt.textContent = `${block.name}: ${block.model_name}`;

      chip.append(led, txt);

      chip.addEventListener("click", () => {
        app.selectedBlockId = blockId;
        if (app.currentTab === "amp" && blockId !== 1 && blockId !== 5) {
          setSectionTab("pedalera");
        } else if (app.currentTab === "pedales") {
          const ampIdx = ram.order.indexOf(1);
          if (idx >= ampIdx) setSectionTab("pedalera");
        } else if (app.currentTab === "post-amp") {
          const ampIdx = ram.order.indexOf(1);
          if (idx <= ampIdx) setSectionTab("pedalera");
        }
        renderPedalboard();
        renderInspector();
        renderSignalFlowMinimap();
      });

      minimap.appendChild(chip);

      const arrow = document.createElement("span");
      arrow.className = "minimap-arrow";
      arrow.textContent = "→";
      minimap.appendChild(arrow);
    });

    const outNode = document.createElement("span");
    outNode.className = "minimap-node";
    outNode.textContent = "OUT";
    minimap.appendChild(outNode);
  }

  function renderPedalboard() {
    renderSignalFlowMinimap();
    const ram = app.state?.ram;
    const hasRam = Boolean(ram && Array.isArray(ram.order));
    els["pedalboard-empty"].hidden = hasRam;
    els["pedalboard-chain"].hidden = !hasRam;

    if (!hasRam) {
      els["chain-order-summary"].textContent = "IN -> OUT";
      els["btn-move-earlier"].disabled = true;
      els["btn-move-later"].disabled = true;
      els["chain-position-bars"].replaceChildren();
      return;
    }

    const orderNames = ram.order.map((id) => BLOCK_CATALOG[id]?.name || `B${id}`);
    els["chain-order-summary"].textContent = `IN -> ${orderNames.join(" -> ")} -> OUT`;

    const row = els["pedal-cards-row"];
    const activeEl = document.activeElement;
    const focusedBlockAttr =
      activeEl instanceof Element && row.contains(activeEl)
        ? activeEl.closest(".pedal-card")?.getAttribute("data-block-id") || null
        : null;
    const wasFootswitchFocused =
      activeEl instanceof Element && row.contains(activeEl) && activeEl.classList.contains("pedal-footswitch");
    row.replaceChildren();

    const ampIdx = ram.order.indexOf(1);
    ram.order.forEach((blockId, chainIdx) => {
      if (app.currentTab === "pedales" && chainIdx >= ampIdx) return;
      if (app.currentTab === "post-amp" && chainIdx <= ampIdx) return;
      const block = getBlockById(ram, blockId);
      const spec = BLOCK_CATALOG[blockId];
      if (!block || !spec) return;

      const isSelected = blockId === app.selectedBlockId;
      const card = document.createElement("div");
      card.className = `pedal-card${isSelected ? " is-selected" : ""}${block.enabled ? "" : " is-bypassed"}`;
      card.style.setProperty("--block-color", spec.colorVar);
      card.setAttribute("draggable", "true");
      card.setAttribute("data-block-id", String(blockId));
      card.setAttribute("role", "button");
      card.setAttribute("tabindex", "0");
      card.setAttribute(
        "aria-label",
        `${block.name} ${block.model_name}, position ${chainIdx + 1}, ${block.enabled ? "active" : "bypassed"}`
      );

      const head = document.createElement("div");
      head.className = "pedal-card-head";

      const tag = document.createElement("span");
      tag.className = "pedal-block-tag";
      tag.textContent = block.name;

      const posNum = document.createElement("span");
      posNum.className = "pedal-slot-num";
      posNum.textContent = `#${chainIdx + 1}`;
      head.append(tag, posNum);

      const artWrap = document.createElement("div");
      artWrap.className = "pedal-art-wrap";
      artWrap.appendChild(buildPedalSvg(block));

      const modelLabel = document.createElement("div");
      modelLabel.className = "pedal-model-name";
      modelLabel.textContent = block.min_fw ? `${block.model_name} (V${block.min_fw}+)` : block.model_name;
      modelLabel.title = modelLabel.textContent;

      const footswitch = document.createElement("button");
      footswitch.type = "button";
      footswitch.className = `pedal-footswitch${block.enabled ? " is-on" : ""}`;
      footswitch.setAttribute("aria-pressed", String(block.enabled));
      footswitch.setAttribute("aria-label", `Toggle ${block.name} bypass`);

      const led = document.createElement("span");
      led.className = "footswitch-led";
      const switchText = document.createElement("span");
      switchText.textContent = block.enabled ? "ON" : "BYPASS";
      footswitch.append(led, switchText);

      footswitch.addEventListener("click", (ev) => {
        ev.stopPropagation();
        app.selectedBlockId = blockId;
        void handleToggleBlock(blockId, !block.enabled);
      });

      card.addEventListener("click", () => {
        app.selectedBlockId = blockId;
        renderPedalboard();
        renderInspector();
      });

      card.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter" || ev.key === " ") {
          ev.preventDefault();
          app.selectedBlockId = blockId;
          renderPedalboard();
          renderInspector();
        }
      });

      card.addEventListener("dragstart", (ev) => {
        if (ev.target instanceof Element && ev.target.closest(".pedal-footswitch")) {
          ev.preventDefault();
          return;
        }
        app.draggedBlockId = blockId;
        app.selectedBlockId = blockId;
        card.classList.add("is-dragging");
        if (ev.dataTransfer) {
          ev.dataTransfer.effectAllowed = "move";
          ev.dataTransfer.setData("text/plain", String(blockId));
        }
      });

      card.addEventListener("dragend", () => {
        app.draggedBlockId = null;
        card.classList.remove("is-dragging");
        row.querySelectorAll(".pedal-card.is-drop-target").forEach((node) => {
          node.classList.remove("is-drop-target");
        });
      });

      card.addEventListener("dragover", (ev) => {
        if (app.draggedBlockId === null || app.draggedBlockId === blockId) return;
        ev.preventDefault();
        if (ev.dataTransfer) ev.dataTransfer.dropEffect = "move";
        card.classList.add("is-drop-target");
      });

      card.addEventListener("dragleave", () => {
        card.classList.remove("is-drop-target");
      });

      card.addEventListener("drop", (ev) => {
        ev.preventDefault();
        card.classList.remove("is-drop-target");
        const fromBlockId = app.draggedBlockId;
        if (fromBlockId === null || fromBlockId === blockId) return;
        const currentOrder = [...ram.order];
        const fromIdx = currentOrder.indexOf(fromBlockId);
        const toIdx = currentOrder.indexOf(blockId);
        if (fromIdx < 0 || toIdx < 0) return;
        const [moved] = currentOrder.splice(fromIdx, 1);
        currentOrder.splice(toIdx, 0, moved);
        void handleReorder(currentOrder);
      });

      card.append(head, artWrap, modelLabel, footswitch);
      row.appendChild(card);
    });

    const selectedPos = ram.order.indexOf(app.selectedBlockId);
    els["btn-move-earlier"].disabled = selectedPos <= 0;
    els["btn-move-later"].disabled = selectedPos < 0 || selectedPos >= ram.order.length - 1;

    const barsEl = els["chain-position-bars"];
    barsEl.replaceChildren();
    for (let idx = 0; idx < ram.order.length; idx += 1) {
      const tick = document.createElement("span");
      tick.className = `chain-pos-tick${idx === selectedPos ? " is-active" : ""}`;
      barsEl.appendChild(tick);
    }

    if (focusedBlockAttr !== null) {
      const targetSelector = wasFootswitchFocused
        ? `.pedal-card[data-block-id="${focusedBlockAttr}"] .pedal-footswitch`
        : `.pedal-card[data-block-id="${focusedBlockAttr}"]`;
      const focusTarget = row.querySelector(targetSelector);
      if (focusTarget instanceof HTMLElement) {
        focusTarget.focus({ preventScroll: true });
      }
    }

    window.requestAnimationFrame(() => {
      renderPatchCables();
    });
  }

  function renderPatchCables() {
    const svg = els["patch-cables-svg"];
    if (!svg) return;
    svg.replaceChildren();

    const ram = app.state?.ram;
    if (!ram || !Array.isArray(ram.order) || els["pedalboard-chain"].hidden) return;

    const row = els["pedal-cards-row"];
    const cards = Array.from(row.querySelectorAll(".pedal-card"));
    if (cards.length === 0) return;

    const svgRect = svg.getBoundingClientRect();
    if (svgRect.width === 0 || svgRect.height === 0) return;

    const ns = svg.namespaceURI;

    function getRelPoint(clientX, clientY) {
      return {
        x: clientX - svgRect.left,
        y: clientY - svgRect.top,
      };
    }

    for (let i = 0; i < cards.length - 1; i += 1) {
      const cardA = cards[i];
      const cardB = cards[i + 1];
      const rectA = cardA.getBoundingClientRect();
      const rectB = cardB.getBoundingClientRect();

      const blockAId = Number(cardA.getAttribute("data-block-id"));
      const blockBId = Number(cardB.getAttribute("data-block-id"));
      const blockA = getBlockById(ram, blockAId);
      const blockB = getBlockById(ram, blockBId);
      const isDimmed = !(blockA?.enabled && blockB?.enabled);

      const p1 = getRelPoint(rectA.right - 2, rectA.top + rectA.height * 0.54);
      const p2 = getRelPoint(rectB.left + 2, rectB.top + rectB.height * 0.54);

      const dx = p2.x - p1.x;
      const slack = Math.min(36, Math.max(14, dx * 0.35));
      const d = `M ${p1.x.toFixed(1)} ${p1.y.toFixed(1)} C ${(p1.x + dx * 0.45).toFixed(1)} ${(p1.y + slack).toFixed(1)}, ${(p2.x - dx * 0.45).toFixed(1)} ${(p2.y + slack).toFixed(1)}, ${p2.x.toFixed(1)} ${p2.y.toFixed(1)}`;

      const group = document.createElementNS(ns, "g");
      group.setAttribute("class", `patch-cable-group${isDimmed ? " patch-cable-dimmed" : ""}`);

      const outerPath = document.createElementNS(ns, "path");
      outerPath.setAttribute("class", "patch-cable-outer");
      outerPath.setAttribute("d", d);

      const innerPath = document.createElementNS(ns, "path");
      innerPath.setAttribute("class", "patch-cable-inner");
      innerPath.setAttribute("d", d);

      group.append(outerPath, innerPath);
      svg.appendChild(group);
    }
  }

  function renderAmpStage() {
    const stage = els["amp-stage-view"];
    if (!stage) return;

    const ram = app.state?.ram;
    if (!ram || !Array.isArray(ram.blocks)) return;

    const ampBlock = getBlockById(ram, 1);
    const cabBlock = getBlockById(ram, 5);

    if (ampBlock) {
      if (els["amp-badge-text"]) {
        els["amp-badge-text"].textContent = ampBlock.model_name || "VINTAGE TUBE AMP";
      }
      const isAmpOn = Boolean(ampBlock.enabled);
      if (els["amp-jewel-lamp"]) {
        els["amp-jewel-lamp"].classList.toggle("is-on", isAmpOn);
      }
      if (els["amp-power-toggle"]) {
        els["amp-power-toggle"].classList.toggle("is-on", isAmpOn);
        els["amp-power-toggle"].setAttribute("aria-pressed", String(isAmpOn));
      }

      const chickenContainer = els["amp-chicken-knobs"];
      if (chickenContainer) {
        chickenContainer.replaceChildren();
        const svgNs = els["patch-cables-svg"] ? els["patch-cables-svg"].namespaceURI : null;
        const svg = svgNs
          ? document.createElementNS(svgNs, "svg")
          : document.createElement("svg");
        svg.setAttribute("viewBox", "0 0 340 68");
        svg.setAttribute("class", "amp-knobs-svg");
        svg.style.width = "100%";
        svg.style.height = "68px";

        const ns = svg.namespaceURI;
        const knobs = ampBlock.knobs || [];
        knobs.forEach((knob, idx) => {
          const cx = 34 + idx * 68;
          const cy = 34;
          appendInteractiveKnobSvg(svg, ns, cx, cy, 18, knob, ampBlock);
        });
        chickenContainer.appendChild(svg);
      }
    }

    if (cabBlock) {
      if (els["cab-badge-text"]) {
        els["cab-badge-text"].textContent = cabBlock.model_name || "LEKATO 4x12";
      }
      const cabKnobsContainer = els["cab-knobs"];
      if (cabKnobsContainer) {
        cabKnobsContainer.replaceChildren();
        const svgNs = els["patch-cables-svg"] ? els["patch-cables-svg"].namespaceURI : null;
        const cabSvg = svgNs
          ? document.createElementNS(svgNs, "svg")
          : document.createElement("svg");
        cabSvg.setAttribute("viewBox", "0 0 240 68");
        cabSvg.setAttribute("class", "cab-knobs-svg");
        cabSvg.style.width = "100%";
        cabSvg.style.height = "68px";

        const ns = cabSvg.namespaceURI;
        const knobs = cabBlock.knobs || [];
        knobs.forEach((knob, idx) => {
          const cx = 40 + idx * 80;
          const cy = 34;
          appendInteractiveKnobSvg(cabSvg, ns, cx, cy, 16, knob, cabBlock);
        });
        cabKnobsContainer.appendChild(cabSvg);
      }
    }
  }

  function renderInspectorSubtitle() {
    const ram = app.state?.ram;
    const block = getBlockById(ram, app.selectedBlockId);
    if (!ram || !block) return;
    const chainPos = ram.order.indexOf(app.selectedBlockId) + 1;
    els["inspector-block-subtitle"].textContent = `Block ${block.block_id} · Position ${chainPos} of 6 in serial chain`;
  }

  function renderInspector() {
    const ram = app.state?.ram;
    const block = getBlockById(ram, app.selectedBlockId);
    const spec = BLOCK_CATALOG[app.selectedBlockId];

    if (!ram || !block || !spec) {
      els["inspector-empty"].hidden = false;
      els["inspector-content"].hidden = true;
      app.renderedInspectorKey = null;
      app.renderedInspectorBlockId = null;
      app.renderedInspectorNamesSig = null;
      app.knobInputsByAddr.clear();
      return;
    }

    els["inspector-empty"].hidden = true;
    els["inspector-content"].hidden = false;
    els["inspector-content"].style.setProperty("--block-color", spec.colorVar);

    els["inspector-block-badge"].textContent = block.name;
    els["inspector-model-heading"].textContent = block.model_name;
    els["inspector-fw-badge"].hidden = !block.min_fw;
    if (block.min_fw) {
      els["inspector-fw-badge"].textContent = `V${block.min_fw}+`;
    }
    renderInspectorSubtitle();

    const bypassBtn = els["btn-inspector-bypass"];
    bypassBtn.className = `bypass-pill${block.enabled ? " is-on" : ""}`;
    bypassBtn.textContent = block.enabled ? "ACTIVE" : "BYPASSED";
    bypassBtn.setAttribute("aria-pressed", String(block.enabled));

    const modelSelect = els["inspector-model-select"];
    const models = getModelListForBlock(block.block_id, app.state);
    const namesSig = models.map((m) => `${m.id}:${m.name}`).join("|");
    if (
      app.renderedInspectorBlockId !== block.block_id ||
      app.renderedInspectorNamesSig !== namesSig ||
      modelSelect.options.length !== models.length
    ) {
      modelSelect.replaceChildren();
      for (const mdl of models) {
        const opt = document.createElement("option");
        opt.value = String(mdl.id);
        const idxTag = String(mdl.id).padStart(2, "0");
        opt.textContent = mdl.minFw ? `${idxTag}: ${mdl.name} (V${mdl.minFw}+)` : `${idxTag}: ${mdl.name}`;
        modelSelect.appendChild(opt);
      }
      app.renderedInspectorBlockId = block.block_id;
      app.renderedInspectorNamesSig = namesSig;
    }
    if (document.activeElement !== modelSelect) {
      modelSelect.value = String(block.model_id);
    }

    // Special DLY Tempo & CAB High Cut notes
    els["delay-tempo-strip"].hidden = block.block_id !== 3;
    if (block.block_id === 3 && block.knobs[0]) {
      updateDelayTempoReadout(block.knobs[0].raw, block.model_id);
    }
    els["cab-scale-note"].hidden = block.block_id !== 5;

    const inspectorKey = `${block.block_id}:${block.model_id}`;
    const knobsContainer = els["inspector-knobs"];
    const canReuseKnobs =
      app.renderedInspectorKey === inspectorKey &&
      knobsContainer.children.length === block.knobs.length &&
      block.knobs.every((k) => app.knobInputsByAddr.has(k.addr));

    if (canReuseKnobs) {
      for (const knob of block.knobs) {
        updateKnobVisualsInPlace(knob.addr, knob.raw, { fromLocal: false });
      }
      return;
    }

    knobsContainer.replaceChildren();
    app.knobInputsByAddr.clear();
    app.renderedInspectorKey = inspectorKey;

    for (const knob of block.knobs) {
      const card = document.createElement("div");
      card.className = "knob-card";

      const head = document.createElement("div");
      head.className = "knob-card-head";

      const label = document.createElement("label");
      label.className = "knob-label";
      label.textContent = knob.label;
      const inputId = `knob-slider-${knob.addr}`;
      label.setAttribute("for", inputId);

      const unitDisplay = document.createElement("span");
      unitDisplay.className = "knob-unit-readout";
      unitDisplay.textContent = formatKnobDisplay(block.block_id, block.model_id, knob.slot, knob.raw);

      head.append(label, unitDisplay);

      const row = document.createElement("div");
      row.className = "knob-control-row";

      const slider = document.createElement("input");
      slider.id = inputId;
      slider.type = "range";
      slider.min = "0";
      slider.max = "100";
      slider.step = "1";
      slider.className = "studio-slider";
      slider.style.setProperty("--slider-color", spec.colorVar);
      setSliderVisual(slider, knob.raw);

      const numberInput = document.createElement("input");
      numberInput.type = "number";
      numberInput.min = "0";
      numberInput.max = "100";
      numberInput.step = "1";
      numberInput.value = String(knob.raw);
      numberInput.className = "num-input";
      numberInput.setAttribute("aria-label", `${knob.label} raw value (0 to 100)`);

      const foot = document.createElement("div");
      foot.className = "knob-meta-foot";
      const rawBadge = document.createElement("span");
      rawBadge.textContent = `0x${knob.addr.toString(16).padStart(2, "0")} · raw ${knob.raw}`;
      const hintSpan = document.createElement("span");
      if (block.block_id === 5 && knob.slot === 2) {
        hintSpan.textContent = "0=5.0 kHz .. 100=18.0 kHz";
      } else if (block.block_id === 3 && knob.slot === 0) {
        hintSpan.textContent = block.model_id === 3 ? "50–500 ms" : "100–1000 ms";
      } else {
        hintSpan.textContent = "0..100";
      }
      foot.append(rawBadge, hintSpan);

      app.knobInputsByAddr.set(knob.addr, {
        blockId: block.block_id,
        modelId: block.model_id,
        slot: knob.slot,
        slider,
        numberInput,
        unitDisplay,
        rawBadge,
      });

      const startDrag = () => {
        app.activeDragAddr = knob.addr;
        markLocalEdit();
      };
      const endDrag = () => {
        if (app.activeDragAddr === knob.addr) {
          app.activeDragAddr = null;
        }
        markLocalEdit();
      };

      slider.addEventListener("pointerdown", startDrag);
      slider.addEventListener("mousedown", startDrag);
      slider.addEventListener("touchstart", startDrag, { passive: true });
      slider.addEventListener("pointerup", endDrag);
      slider.addEventListener("blur", endDrag);

      slider.addEventListener("input", () => {
        app.activeDragAddr = knob.addr;
        scheduleKnobWrite(knob.addr, slider.value, false);
      });
      slider.addEventListener("change", () => {
        endDrag();
        scheduleKnobWrite(knob.addr, slider.value, true);
      });

      numberInput.addEventListener("input", () => {
        const rawText = numberInput.value.trim();
        if (rawText === "") return;
        scheduleKnobWrite(knob.addr, rawText, false);
      });
      numberInput.addEventListener("change", () => {
        const clamped = clampInt(numberInput.value, 0, 100);
        numberInput.value = String(clamped);
        scheduleKnobWrite(knob.addr, clamped, true);
      });

      row.append(slider, numberInput);
      card.append(head, row, foot);
      knobsContainer.appendChild(card);
    }
  }

  function togglePresetsDrawer(forceState) {
    const drawer = els["presets-drawer"];
    if (!drawer) return;
    const willOpen = typeof forceState === "boolean" ? forceState : !drawer.classList.contains("drawer-open");
    drawer.classList.toggle("drawer-open", willOpen);
    if (els["btn-toggle-presets"]) {
      els["btn-toggle-presets"].classList.toggle("is-active", willOpen);
    }
    window.requestAnimationFrame(() => renderPatchCables());
  }

  function toggleEffectsDrawer(forceState) {
    const drawer = els["effects-drawer"];
    if (!drawer) return;
    const willOpen = typeof forceState === "boolean" ? forceState : drawer.hidden;
    drawer.hidden = !willOpen;
    if (willOpen) {
      renderEffectsLibrary();
    }
    if (els["btn-toggle-effects"]) {
      els["btn-toggle-effects"].classList.toggle("is-active", willOpen);
    }
    window.requestAnimationFrame(() => renderPatchCables());
  }

  function renderEffectsLibrary() {
    const container = els["effects-categories-list"];
    if (!container) return;
    container.replaceChildren();

    const query = (els["effects-search"]?.value || "").trim().toLowerCase();
    const ram = app.state?.ram;

    const categories = [
      {
        id: "dinamica",
        name: "Dinámica & Pre-effects",
        blockId: 0,
        color: "var(--block-fx)",
        models: getModelListForBlock(0, app.state),
      },
      {
        id: "drive-amp",
        name: "Preamps & Amps",
        blockId: 1,
        color: "var(--block-amp)",
        models: getModelListForBlock(1, app.state),
      },
      {
        id: "modulacion",
        name: "Modulación",
        blockId: 2,
        color: "var(--block-mod)",
        models: getModelListForBlock(2, app.state),
      },
      {
        id: "delay",
        name: "Delay",
        blockId: 3,
        color: "var(--block-dly)",
        models: getModelListForBlock(3, app.state),
      },
      {
        id: "reverb",
        name: "Reverb",
        blockId: 4,
        color: "var(--block-rev)",
        models: getModelListForBlock(4, app.state),
      },
      {
        id: "cab",
        name: "Cabinets & IRs",
        blockId: 5,
        color: "var(--block-cab)",
        models: getModelListForBlock(5, app.state),
      },
    ];

    categories.forEach((cat) => {
      const filtered = cat.models.filter((m) => {
        if (!query) return true;
        return m.name.toLowerCase().includes(query) || cat.name.toLowerCase().includes(query);
      });

      if (query && filtered.length === 0) return;

      const catEl = document.createElement("div");
      catEl.className = "effects-category is-open";

      const header = document.createElement("div");
      header.className = "effects-category-header";

      const title = document.createElement("span");
      title.textContent = `${cat.name} (${filtered.length})`;

      const chevron = document.createElement("span");
      chevron.className = "effects-category-chevron";
      chevron.textContent = "▶";

      header.append(title, chevron);
      header.addEventListener("click", () => {
        catEl.classList.toggle("is-open");
      });

      const grid = document.createElement("div");
      grid.className = "effects-grid";

      const currentBlock = ram ? getBlockById(ram, cat.blockId) : null;

      filtered.forEach((model) => {
        const isCurrent = currentBlock?.model_id === model.id;
        const tile = document.createElement("button");
        tile.type = "button";
        tile.className = `effect-card-tile${isCurrent ? " is-active" : ""}`;
        tile.style.setProperty("--tile-color", cat.color);

        const icon = document.createElement("span");
        icon.className = "effect-tile-icon";

        const nameSpan = document.createElement("span");
        nameSpan.className = "effect-tile-name";
        nameSpan.textContent = model.name;

        tile.append(icon, nameSpan);

        if (model.minFw) {
          const badge = document.createElement("span");
          badge.className = "effect-tile-badge";
          badge.textContent = `V${model.minFw}+`;
          tile.appendChild(badge);
        }

        tile.addEventListener("click", () => {
          app.selectedBlockId = cat.blockId;
          void handleChangeModel(cat.blockId, model.id);
          renderEffectsLibrary();
        });

        grid.appendChild(tile);
      });

      catEl.append(header, grid);
      container.appendChild(catEl);
    });
  }

  function renderAll() {
    renderPorts();
    renderTopBar();
    renderBackupNote();
    renderSidebar();
    renderPedalboard();
    renderAmpStage();
    renderInspector();
    if (els["effects-drawer"] && !els["effects-drawer"].hidden) {
      renderEffectsLibrary();
    }
    if (!els["modal-backup"].hidden) {
      updateBackupRestoreButtons();
    }
    if (els["modal-capture-manager"] && !els["modal-capture-manager"].hidden) {
      renderCaptureManagerSlots();
    }
  }

  function bindEvents() {
    ["pedalera", "pedales", "amp", "post-amp"].forEach((tabId) => {
      const btn = els[`tab-${tabId}`];
      if (btn) {
        btn.addEventListener("click", () => {
          setSectionTab(tabId);
        });
      }
    });
    if (els["amp-power-toggle"]) {
      els["amp-power-toggle"].addEventListener("click", () => {
        const ampBlock = getBlockById(app.state?.ram, 1);
        if (ampBlock) {
          void handleToggleBlock(1, !ampBlock.enabled);
        }
      });
    }
    if (els["amp-jewel-lamp"]) {
      els["amp-jewel-lamp"].addEventListener("click", () => {
        const ampBlock = getBlockById(app.state?.ram, 1);
        if (ampBlock) {
          void handleToggleBlock(1, !ampBlock.enabled);
        }
      });
    }

    els["btn-refresh-ports"].addEventListener("click", () => {
      void refreshPorts();
    });
    els["btn-connect"].addEventListener("click", () => {
      void handleConnect();
    });
    els["btn-disconnect"].addEventListener("click", () => {
      void handleDisconnect();
    });
    els["btn-demo"].addEventListener("click", () => {
      void handleEnterDemo();
    });
    els["btn-dismiss-error"].addEventListener("click", () => {
      showError("");
    });

    // Patch Volume (addr 0)
    const volSlider = els["patch-vol-slider"];
    const volNum = els["patch-vol-number"];
    volSlider.addEventListener("pointerdown", () => {
      app.activeDragAddr = 0;
      markLocalEdit();
    });
    volSlider.addEventListener("pointerup", () => {
      if (app.activeDragAddr === 0) app.activeDragAddr = null;
      markLocalEdit();
    });
    volSlider.addEventListener("blur", () => {
      if (app.activeDragAddr === 0) app.activeDragAddr = null;
    });
    volSlider.addEventListener("input", () => {
      app.activeDragAddr = 0;
      scheduleKnobWrite(0, volSlider.value, false);
    });
    volSlider.addEventListener("change", () => {
      if (app.activeDragAddr === 0) app.activeDragAddr = null;
      scheduleKnobWrite(0, volSlider.value, true);
    });
    volNum.addEventListener("input", () => {
      const rawText = volNum.value.trim();
      if (rawText === "") return;
      scheduleKnobWrite(0, rawText, false);
    });
    volNum.addEventListener("change", () => {
      const clamped = clampInt(volNum.value, 0, 100);
      volNum.value = String(clamped);
      scheduleKnobWrite(0, clamped, true);
    });

    els["btn-refresh-ram"].addEventListener("click", () => {
      void handleRefreshRam();
    });
    els["btn-undo"].addEventListener("click", () => {
      void handleUndo();
    });
    els["btn-revert"].addEventListener("click", openRevertModal);
    els["btn-confirm-revert"].addEventListener("click", () => {
      void handleConfirmRevert();
    });
    els["btn-save-slot"].addEventListener("click", openSaveModal);
    els["save-slot-select"].addEventListener("change", updateSaveModalGuidance);
    els["chk-save-factory-confirm"].addEventListener("change", updateSaveModalGuidance);
    els["btn-confirm-save"].addEventListener("click", () => {
      void handleConfirmSave();
    });

    els["btn-backup"].addEventListener("click", openBackupModal);
    els["btn-export-backup"].addEventListener("click", () => {
      void handleExportBackup();
    });
    els["backup-file-input"].addEventListener("change", handleBackupFileSelected);
    els["btn-select-user-slots"].addEventListener("click", () => {
      app.restoreSummaryText = null;
      app.backupSelectedSlots.clear();
      for (let i = FACTORY_SLOT_COUNT; i < TOTAL_SLOTS; i += 1) {
        app.backupSelectedSlots.add(i);
      }
      renderBackupModalList();
    });
    els["btn-select-changed-slots"].addEventListener("click", () => {
      app.restoreSummaryText = null;
      app.backupSelectedSlots.clear();
      const currentSummaries = app.state?.presets_summary || [];
      for (let i = 0; i < app.backupDecodedSlots.length; i += 1) {
        const curHex = currentSummaries[i]?.raw_hex;
        if (curHex && curHex.toLowerCase() !== app.backupDecodedSlots[i].rawHex) {
          if (i >= FACTORY_SLOT_COUNT || app.factoryUnlocked) {
            app.backupSelectedSlots.add(i);
          }
        }
      }
      renderBackupModalList();
    });
    els["btn-select-all-slots"].addEventListener("click", () => {
      app.restoreSummaryText = null;
      app.backupSelectedSlots.clear();
      for (let i = 0; i < TOTAL_SLOTS; i += 1) {
        app.backupSelectedSlots.add(i);
      }
      renderBackupModalList();
    });
    els["btn-clear-slot-selection"].addEventListener("click", () => {
      app.restoreSummaryText = null;
      app.backupSelectedSlots.clear();
      renderBackupModalList();
    });
    els["btn-batch-restore"].addEventListener("click", () => {
      void handleBatchRestore();
    });
    els["chk-restore-factory-confirm"].addEventListener("change", updateBackupRestoreButtons);

    const clearDragState = () => {
      if (app.activeDragAddr !== null) {
        app.activeDragAddr = null;
        markLocalEdit();
      }
    };
    window.addEventListener("pointerup", clearDragState);
    window.addEventListener("touchend", clearDragState, { passive: true });

    if (typeof ResizeObserver !== "undefined" && els["pedalboard-stage"]) {
      const stageObserver = new ResizeObserver(() => {
        window.requestAnimationFrame(() => {
          renderPatchCables();
        });
      });
      stageObserver.observe(els["pedalboard-stage"]);
    }

    // Bank tabs & search & factory lock
    document.querySelectorAll(".bank-tab").forEach((tab) => {
      tab.addEventListener("click", () => {
        app.bankFilter = tab.getAttribute("data-bank") || "all";
        document.querySelectorAll(".bank-tab").forEach((t) => {
          const active = t === tab;
          t.classList.toggle("is-active", active);
          t.setAttribute("aria-selected", String(active));
        });
        renderSidebar();
      });
    });

    els["preset-search"].addEventListener("input", () => {
      app.searchTerm = els["preset-search"].value;
      renderSidebar();
    });

    els["chk-unlock-factory"].addEventListener("change", () => {
      app.factoryUnlocked = els["chk-unlock-factory"].checked;
      renderSidebar();
      if (!els["modal-save"].hidden) updateSaveModalGuidance();
      if (!els["modal-backup"].hidden) renderBackupModalList();
    });

    // Chain reordering controls & keyboard shortcuts
    els["btn-move-earlier"].addEventListener("click", () => {
      shiftSelectedBlock(-1);
    });
    els["btn-move-later"].addEventListener("click", () => {
      shiftSelectedBlock(1);
    });

    els["pedalboard-stage"].addEventListener("keydown", (ev) => {
      if (ev.target instanceof Element && ev.target.closest("input, select, textarea")) {
        return;
      }
      if (ev.key === "ArrowLeft") {
        ev.preventDefault();
        shiftSelectedBlock(-1);
      } else if (ev.key === "ArrowRight") {
        ev.preventDefault();
        shiftSelectedBlock(1);
      }
    });

    // Inspector controls
    els["btn-inspector-bypass"].addEventListener("click", () => {
      const block = getBlockById(app.state?.ram, app.selectedBlockId);
      if (!block) return;
      void handleToggleBlock(block.block_id, !block.enabled);
    });

    els["inspector-model-select"].addEventListener("change", () => {
      const modelId = Number(els["inspector-model-select"].value);
      void handleChangeModel(app.selectedBlockId, modelId);
    });

    els["btn-tap-tempo"].addEventListener("click", handleTapTempo);
    els["btn-dly-apply-bpm"].addEventListener("click", handleApplyBpm);
    els["dly-bpm-input"].addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") {
        ev.preventDefault();
        handleApplyBpm();
      }
    });

    // Modal close handlers
    if (els["btn-toggle-presets"]) {
      els["btn-toggle-presets"].addEventListener("click", () => togglePresetsDrawer());
    }
    if (els["btn-toggle-effects"]) {
      els["btn-toggle-effects"].addEventListener("click", () => toggleEffectsDrawer());
    }
    if (els["btn-close-effects"]) {
      els["btn-close-effects"].addEventListener("click", () => toggleEffectsDrawer(false));
    }
    if (els["effects-search"]) {
      els["effects-search"].addEventListener("input", () => renderEffectsLibrary());
    }

    if (els["btn-open-capture-mgr"]) {
      els["btn-open-capture-mgr"].addEventListener("click", () => openCaptureManager("amp"));
    }
    if (els["btn-drawer-open-capture-mgr"]) {
      els["btn-drawer-open-capture-mgr"].addEventListener("click", () => {
        toggleEffectsDrawer(false);
        openCaptureManager("amp");
      });
    }

    if (els["tab-cap-amps"]) {
      els["tab-cap-amps"].addEventListener("click", () => {
        app.captureCategory = "amp";
        updateCaptureTabs();
        renderCaptureManagerSlots();
        renderCaptureLibrary();
      });
    }
    if (els["tab-cap-cabs"]) {
      els["tab-cap-cabs"].addEventListener("click", () => {
        app.captureCategory = "cab";
        updateCaptureTabs();
        renderCaptureManagerSlots();
        renderCaptureLibrary();
      });
    }

    if (els["capture-slot-search"]) {
      els["capture-slot-search"].addEventListener("input", () => {
        app.captureSearch = els["capture-slot-search"].value;
        renderCaptureManagerSlots();
      });
    }

    document.querySelectorAll(".capture-filter-chips .chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        app.captureFilter = chip.getAttribute("data-filter") || "all";
        document.querySelectorAll(".capture-filter-chips .chip").forEach((c) => {
          c.classList.toggle("is-active", c === chip);
        });
        renderCaptureManagerSlots();
      });
    });

    if (els["capture-file-dropzone"]) {
      const dropzone = els["capture-file-dropzone"];
      dropzone.addEventListener("dragover", (ev) => {
        ev.preventDefault();
        dropzone.classList.add("is-dragover");
      });
      dropzone.addEventListener("dragleave", () => {
        dropzone.classList.remove("is-dragover");
      });
      dropzone.addEventListener("drop", (ev) => {
        ev.preventDefault();
        dropzone.classList.remove("is-dragover");
        if (ev.dataTransfer?.files?.length) {
          void validateAndImportCapture(ev.dataTransfer.files[0]);
        }
      });
    }

    if (els["capture-file-input"]) {
      els["capture-file-input"].addEventListener("change", (ev) => {
        const file = ev.target.files?.[0];
        if (file) {
          void validateAndImportCapture(file);
        }
      });
    }

    document.querySelectorAll("[data-close-modal]").forEach((btn) => {
      btn.addEventListener("click", () => {
        closeModal(btn.getAttribute("data-close-modal"));
      });
    });
    document.querySelectorAll(".modal-backdrop").forEach((backdrop) => {
      backdrop.addEventListener("click", (ev) => {
        if (ev.target === backdrop) {
          closeModal(backdrop.id);
        }
      });
    });
    document.addEventListener("keydown", (ev) => {
      if (ev.target instanceof Element && ev.target.closest("input, select, textarea")) {
        if (ev.key === "Escape") {
          ev.target.blur();
        }
        return;
      }
      if (ev.key === "Escape") {
        ["modal-save", "modal-revert", "modal-backup", "modal-capture-manager"].forEach((id) => {
          if (els[id] && !els[id].hidden) closeModal(id);
        });
        if (els["effects-drawer"] && !els["effects-drawer"].hidden) {
          toggleEffectsDrawer(false);
        }
        if (els["presets-drawer"] && els["presets-drawer"].classList.contains("drawer-open")) {
          togglePresetsDrawer(false);
        }
      } else if (ev.key === "p" || ev.key === "P") {
        ev.preventDefault();
        togglePresetsDrawer();
      } else if (ev.key === "e" || ev.key === "E") {
        ev.preventDefault();
        toggleEffectsDrawer();
      } else if (ev.key === "c" || ev.key === "C") {
        ev.preventDefault();
        openCaptureManager(app.captureCategory || "amp");
      }
    });
  }

  async function init() {
    cacheElements();
    bindEvents();
    await Promise.all([refreshPorts(), refreshState({ silent: true }), refreshPresetsCatalog()]);
    app.pollTimerId = setInterval(() => {
      if (app.state?.connected) {
        void refreshState({ fromPoll: true });
      }
    }, POLL_INTERVAL_MS);
  }

  window.addEventListener("DOMContentLoaded", () => {
    void init();
  });
})();

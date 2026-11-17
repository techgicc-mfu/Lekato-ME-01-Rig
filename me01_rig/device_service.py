"""Stateful coordinator for ME-01 handshake, polling, undo, backups, and verified flash saves."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from .protocol import (
    ADDR_ACTIVE_PRESET,
    ADDR_AMP_NAMES,
    ADDR_CAB_NAMES,
    ADDR_RAM_BASE,
    BLOCK_IDS,
    BLOCKS,
    CMD_IDENTITY,
    CMD_READ,
    FACTORY_SLOT_COUNT,
    NAME_RECORD_COUNT,
    NAME_TABLE_SIZE,
    PRESET_SIZE,
    SPACE_NAMES,
    SPACE_PRESET,
    TOTAL_PRESET_SLOTS,
    PresetImage,
    ProtocolError,
    build_change_knob,
    build_change_model,
    build_change_routing,
    build_identity_query,
    build_load_preset,
    build_read_request,
    build_rename_slot,
    build_save_flash,
    build_toggle_block,
    decode_name_table,
    is_ack_frame,
    parse_frame,
    unwrap_sysex,
    wrap_sysex,
)
from .winmm_midi import MidiPortPair, MidiTransportError, WinMMTransport, find_candidate_pairs

DEFAULT_TIMEOUT_MS = 800
FLASH_SAVE_TIMEOUT_MS = 3000
UNDO_STACK_LIMIT = 30


def _require_bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ProtocolError(f"{name} must be a boolean, got {type(value).__name__}")
    return value


def _require_port_id(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProtocolError(f"{name} must be an int, got {type(value).__name__}")
    if value < 0:
        raise ProtocolError(f"{name} must be >= 0, got {value}")
    return value


def _require_slot_id(value: Any, name: str = "preset_id") -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProtocolError(f"{name} must be an int, got {type(value).__name__}")
    if not (0 <= value < TOTAL_PRESET_SLOTS):
        raise ProtocolError(f"{name} out of range [0, {TOTAL_PRESET_SLOTS - 1}]: {value}")
    return value


def _require_range(value: Any, low: int, high: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProtocolError(f"{name} must be an int, got {type(value).__name__}")
    if not (low <= value <= high):
        raise ProtocolError(f"{name} out of range [{low}, {high}]: {value}")
    return value


def _normalize_port_pair(pair: Any) -> dict[str, Any]:
    if isinstance(pair, dict):
        return {
            "in_id": int(pair["in_id"]),
            "in_name": str(pair["in_name"]),
            "out_id": int(pair["out_id"]),
            "out_name": str(pair["out_name"]),
            "match_score": int(pair.get("match_score", 0)),
        }
    return {
        "in_id": int(pair.in_id),
        "in_name": str(pair.in_name),
        "out_id": int(pair.out_id),
        "out_name": str(pair.out_name),
        "match_score": int(pair.match_score),
    }


def _parse_backup_slots(backup_data: Any) -> list[bytes]:
    if not isinstance(backup_data, dict):
        raise ProtocolError("backup_data must be a JSON object")
    presets_hex = backup_data.get("presets_hex")
    if isinstance(presets_hex, (str, bytes, bytearray)) or not isinstance(presets_hex, Sequence):
        raise ProtocolError("backup_data missing presets_hex list")
    if len(presets_hex) != TOTAL_PRESET_SLOTS:
        raise ProtocolError(
            f"backup_data presets_hex must contain {TOTAL_PRESET_SLOTS} slots, got {len(presets_hex)}"
        )
    slots: list[bytes] = []
    for idx, item in enumerate(presets_hex):
        if not isinstance(item, str):
            raise ProtocolError(f"backup_data presets_hex[{idx}] must be a hex string")
        try:
            raw = bytes.fromhex(item)
        except ValueError as exc:
            raise ProtocolError(f"Invalid hex in backup_data presets_hex[{idx}]: {exc}") from exc
        slots.append(PresetImage.from_bytes(raw).to_bytes())
    return slots


def _write_json_atomic(target_path: Path, payload: dict[str, Any]) -> Path:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target_path.stem}-",
        suffix=".tmp",
        dir=str(target_path.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, target_path)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return target_path


def _unique_backup_path(backup_dir: Path, prefix: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    candidate = backup_dir / f"{prefix}-{stamp}.json"
    counter = 1
    while candidate.exists():
        candidate = backup_dir / f"{prefix}-{stamp}-{counter}.json"
        counter += 1
    return candidate


def _decode_fixture_names(
    fixture: dict[str, Any],
    vector_key: str,
    list_key: str,
    prefix: str,
) -> list[str]:
    vectors = fixture.get("captured_vectors")
    if isinstance(vectors, dict) and isinstance(vectors.get(vector_key), str):
        frame = parse_frame(unwrap_sysex(bytes.fromhex(vectors[vector_key])))
        return decode_name_table(frame.data)
    raw_list = fixture.get(list_key)
    if isinstance(raw_list, list) and len(raw_list) == 20:
        return [str(item) for item in raw_list]
    return [f"{prefix} {idx + 1}" for idx in range(20)]


class DeviceService:
    """Thread-safe ME-01 device service managing MIDI I/O, sync polling, undo, backups, and flash saves."""

    def __init__(
        self,
        backup_dir: Path,
        fixture_path: Path,
        transport_factory: Callable[[int, int], Any] | None = None,
        poll_interval_s: float = 1.8,
        suppress_window_s: float = 1.2,
        port_finder: Callable[[], list[MidiPortPair]] | None = None,
    ) -> None:
        if isinstance(poll_interval_s, bool) or not isinstance(poll_interval_s, (int, float)) or poll_interval_s <= 0:
            raise ValueError("poll_interval_s must be > 0")
        if (
            isinstance(suppress_window_s, bool)
            or not isinstance(suppress_window_s, (int, float))
            or suppress_window_s < 0
        ):
            raise ValueError("suppress_window_s must be >= 0")

        self._backup_dir = Path(backup_dir)
        self._fixture_path = Path(fixture_path)
        self._transport_factory = (
            transport_factory if transport_factory is not None else (lambda in_id, out_id: WinMMTransport(in_id, out_id))
        )
        self._custom_port_finder = port_finder
        self._port_finder = port_finder if port_finder is not None else find_candidate_pairs
        self._poll_interval_s = float(poll_interval_s)
        self._suppress_window_s = float(suppress_window_s)

        self._op_lock = threading.RLock()
        self._state_lock = threading.RLock()

        self._connected = False
        self._demo = False
        self._transport: Any = None
        self._ports: dict[str, Any] | None = None
        self._identity: str | None = None
        self._amps: list[str] = []
        self._cabs: list[str] = []
        self._active_preset: int | None = None
        self._ram_bytes: bytes | None = None
        self._slots: list[bytes] = []
        self._undo_stack: deque[bytes] = deque(maxlen=UNDO_STACK_LIMIT)
        self._last_backup_path: str | None = None
        self._last_error: str | None = None
        self._session_backup_created = False

        self._edit_seq = 0
        self._last_edit_ts = 0.0
        self._flash_busy = False

        self._poll_thread: threading.Thread | None = None
        self._poll_stop: threading.Event | None = None

    def list_ports(self) -> list[dict[str, Any]]:
        """Return candidate WinMM MIDI input/output pairs as JSON-serializable dicts."""
        return [_normalize_port_pair(pair) for pair in self._port_finder()]

    def connect(
        self,
        in_id: int | None = None,
        out_id: int | None = None,
        auto_backup: bool = True,
        start_polling: bool = True,
    ) -> dict[str, Any]:
        """Open MIDI transport, perform ME-01 handshake + 80-slot read, and optionally start polling."""
        _require_bool(auto_backup, "auto_backup")
        _require_bool(start_polling, "start_polling")
        if in_id is not None:
            in_id = _require_port_id(in_id, "in_id")
        if out_id is not None:
            out_id = _require_port_id(out_id, "out_id")

        with self._op_lock:
            resolved_in, resolved_out, port_meta = self._resolve_ports(in_id, out_id)
            self.disconnect()

            transport = self._transport_factory(resolved_in, resolved_out)
            try:
                if hasattr(transport, "open"):
                    transport.open()
                identity = self._read_identity(transport)
                amps = decode_name_table(
                    self._read_memory(transport, SPACE_NAMES, ADDR_AMP_NAMES, NAME_TABLE_SIZE)
                )
                cabs = decode_name_table(
                    self._read_memory(transport, SPACE_NAMES, ADDR_CAB_NAMES, NAME_TABLE_SIZE)
                )
                active_preset = self._read_active_preset(transport)
                ram_bytes = self._read_ram(transport)
                slots = [
                    PresetImage.from_bytes(
                        self._read_memory(transport, SPACE_PRESET, slot * PRESET_SIZE, PRESET_SIZE)
                    ).to_bytes()
                    for slot in range(TOTAL_PRESET_SLOTS)
                ]
            except Exception as exc:
                try:
                    if hasattr(transport, "close"):
                        transport.close()
                except Exception:
                    pass
                with self._state_lock:
                    self._last_error = str(exc)
                raise

            try:
                with self._state_lock:
                    self._connected = True
                    self._demo = False
                    self._transport = transport
                    self._ports = port_meta
                    self._identity = identity
                    self._amps = amps
                    self._cabs = cabs
                    self._active_preset = active_preset
                    self._ram_bytes = ram_bytes
                    self._slots = slots
                    self._undo_stack.clear()
                    self._last_error = None
                    self._edit_seq += 1
                    self._last_edit_ts = 0.0

                    if auto_backup and not self._session_backup_created:
                        backup_meta = self._write_backup_locked(prefix="me01-auto-backup")
                        self._session_backup_created = True
                        self._last_backup_path = backup_meta["path"]

                    if start_polling:
                        self._start_polling_locked()
            except Exception as exc:
                self.disconnect()
                with self._state_lock:
                    self._last_error = str(exc)
                raise

            return self.get_state()

    def enter_demo_mode(self) -> dict[str, Any]:
        """Load the captured fixture snapshot into an offline in-memory sandbox."""
        with self._op_lock:
            self.disconnect()
            fixture = json.loads(self._fixture_path.read_text(encoding="utf-8"))
            identity = str(fixture.get("identity", "ME-01_DEMO"))
            active_preset = _require_slot_id(fixture.get("active_preset", 0), "active_preset")
            amps = _decode_fixture_names(fixture, "amps_raw", "amps", "AMP")
            cabs = _decode_fixture_names(fixture, "cabs_raw", "cabs", "CAB")
            slots = _parse_backup_slots(fixture)

            ram_hex = fixture.get("ram_hex")
            if isinstance(ram_hex, str):
                ram_bytes = PresetImage.from_bytes(bytes.fromhex(ram_hex)).to_bytes()
            else:
                ram_bytes = slots[active_preset]

            with self._state_lock:
                self._connected = False
                self._demo = True
                self._transport = None
                self._ports = None
                self._identity = identity
                self._amps = amps
                self._cabs = cabs
                self._active_preset = active_preset
                self._ram_bytes = ram_bytes
                self._slots = slots
                self._undo_stack.clear()
                self._last_error = None
                self._edit_seq += 1
                self._last_edit_ts = 0.0

            return self.get_state()

    def disconnect(self) -> None:
        """Stop background polling, close transport, and reset live session state."""
        with self._op_lock:
            with self._state_lock:
                poll_thread = self._poll_thread
                poll_stop = self._poll_stop
                transport = self._transport
                self._connected = False
                self._demo = False
                self._transport = None
                self._poll_thread = None
                self._poll_stop = None

            if poll_stop is not None:
                poll_stop.set()
            if poll_thread is not None and poll_thread is not threading.current_thread():
                poll_thread.join(timeout=2.0)

            try:
                if transport is not None and hasattr(transport, "close"):
                    transport.close()
            finally:
                with self._state_lock:
                    self._ports = None
                    self._identity = None
                    self._amps = []
                    self._cabs = []
                    self._active_preset = None
                    self._ram_bytes = None
                    self._slots = []
                    self._undo_stack.clear()
                    self._last_error = None
                    self._edit_seq += 1
                    self._last_edit_ts = 0.0

    def get_state(self) -> dict[str, Any]:
        """Return a thread-safe JSON-serializable snapshot of current device state."""
        with self._state_lock:
            amps = list(self._amps)
            cabs = list(self._cabs)
            ram_dict = (
                PresetImage.from_bytes(self._ram_bytes).to_dict(amps=amps, cabs=cabs)
                if self._ram_bytes is not None
                else None
            )
            presets_summary = [self._build_preset_summary(idx, raw92, amps, cabs) for idx, raw92 in enumerate(self._slots)]
            dirty_from_slot = bool(
                self._ram_bytes is not None
                and self._active_preset is not None
                and 0 <= self._active_preset < len(self._slots)
                and self._ram_bytes != self._slots[self._active_preset]
            )
            return {
                "connected": self._connected,
                "demo": self._demo,
                "identity": self._identity,
                "ports": dict(self._ports) if self._ports is not None else None,
                "active_preset": self._active_preset,
                "amps": amps,
                "cabs": cabs,
                "ram": ram_dict,
                "presets_summary": presets_summary,
                "dirty_from_slot": dirty_from_slot,
                "undo_depth": len(self._undo_stack),
                "last_backup_path": self._last_backup_path,
                "last_error": self._last_error,
            }

    def get_presets(self) -> list[dict[str, Any]]:
        """Return full parsed preset entries for all loaded slots."""
        with self._state_lock:
            amps = list(self._amps)
            cabs = list(self._cabs)
            return [
                {
                    "preset_id": idx,
                    "label": f"P{idx + 1:02d}",
                    "bank": "factory" if idx < FACTORY_SLOT_COUNT else "user",
                    "locked": idx < FACTORY_SLOT_COUNT,
                    "raw_hex": raw92.hex(),
                    "parsed": PresetImage.from_bytes(raw92).to_dict(amps=amps, cabs=cabs),
                }
                for idx, raw92 in enumerate(self._slots)
            ]

    def poll_once(self) -> bool:
        """Poll active preset and RAM once unless disconnected, demo, busy, or suppressed."""
        with self._state_lock:
            if not self._connected or self._demo or self._transport is None or self._flash_busy:
                return False
            if (time.monotonic() - self._last_edit_ts) < self._suppress_window_s:
                return False
            transport = self._transport
            seq_before = self._edit_seq

        active_preset = self._read_active_preset(transport)
        ram_bytes = self._read_ram(transport)

        with self._state_lock:
            if (
                not self._connected
                or self._demo
                or self._flash_busy
                or self._transport is not transport
                or self._edit_seq != seq_before
                or (time.monotonic() - self._last_edit_ts) < self._suppress_window_s
            ):
                return False
            self._active_preset = active_preset
            self._ram_bytes = ram_bytes
            self._last_error = None
            return True

    def load_preset(self, preset_id: int) -> dict[str, Any]:
        """Load flash preset slot 0..79 into hardware/demo RAM and refresh cached state."""
        frame = build_load_preset(preset_id)
        with self._op_lock:
            transport = self._require_active_session()
            with self._state_lock:
                self._edit_seq += 1
                self._last_edit_ts = time.monotonic()

            if transport is not None:
                self._write_ack(transport, frame)
                new_ram = self._read_ram(transport)
            else:
                with self._state_lock:
                    new_ram = self._slots[preset_id]

            with self._state_lock:
                self._active_preset = preset_id
                self._ram_bytes = new_ram
                self._undo_stack.clear()
                self._edit_seq += 1
                self._last_edit_ts = time.monotonic()
                self._last_error = None

            return self.get_state()

    def refresh_ram(self) -> dict[str, Any]:
        """Non-destructively re-read active preset and live RAM from connected hardware."""
        with self._op_lock:
            transport = self._require_active_session()
            if transport is not None:
                active_preset = self._read_active_preset(transport)
                ram_bytes = self._read_ram(transport)
                with self._state_lock:
                    self._active_preset = active_preset
                    self._ram_bytes = ram_bytes
                    self._edit_seq += 1
                    self._last_error = None
            return self.get_state()

    def revert_to_slot(self) -> dict[str, Any]:
        """Reload the currently active flash slot into live RAM, discarding unsaved edits."""
        with self._op_lock:
            self._require_active_session()
            with self._state_lock:
                active_preset = self._active_preset
            if active_preset is None:
                raise MidiTransportError("No active preset selected")
            return self.load_preset(active_preset)

    def toggle_block(self, block_id: int, enabled: bool) -> dict[str, Any]:
        """Enable or bypass a signal-chain block (0..5) in live RAM."""
        frame = build_toggle_block(block_id, enabled)

        def _mutate(prev_ram: bytes) -> bytes:
            img = PresetImage.from_bytes(prev_ram)
            img.states[block_id] = 1 if enabled else 0
            return img.to_bytes()

        return self._apply_ram_write(frame, _mutate)

    def change_model(self, block_id: int, model_id: int) -> dict[str, Any]:
        """Select a model within a block and immediately re-read live RAM."""
        frame = build_change_model(block_id, model_id)
        with self._op_lock:
            transport = self._require_active_session()
            with self._state_lock:
                assert self._ram_bytes is not None
                prev_ram = self._ram_bytes
                self._edit_seq += 1
                self._last_edit_ts = time.monotonic()

            if transport is not None:
                self._write_ack(transport, frame)
                new_ram = self._read_ram(transport)
            else:
                img = PresetImage.from_bytes(prev_ram)
                img.models[block_id] = model_id
                new_ram = img.to_bytes()

            with self._state_lock:
                if new_ram != prev_ram:
                    self._undo_stack.append(prev_ram)
                self._ram_bytes = new_ram
                self._edit_seq += 1
                self._last_edit_ts = time.monotonic()
                self._last_error = None

            return self.get_state()

    def change_knob(self, addr: int, value: int) -> dict[str, Any]:
        """Set patch volume (addr=0) or block knob value (even addr 0x14..0x5A) in live RAM."""
        frame = build_change_knob(addr, value)

        def _mutate(prev_ram: bytes) -> bytes:
            buf = bytearray(prev_ram)
            buf[addr : addr + 2] = value.to_bytes(2, "little")
            return PresetImage.from_bytes(bytes(buf)).to_bytes()

        return self._apply_ram_write(frame, _mutate)

    def change_routing(self, order: Sequence[int]) -> dict[str, Any]:
        """Update the 6-block signal chain permutation in live RAM."""
        frame = build_change_routing(order)

        def _mutate(prev_ram: bytes) -> bytes:
            img = PresetImage.from_bytes(prev_ram)
            img.order = list(order)
            return img.to_bytes()

        return self._apply_ram_write(frame, _mutate)

    def _apply_ram_write(self, frame: bytes, mutator: Callable[[bytes], bytes]) -> dict[str, Any]:
        with self._op_lock:
            transport = self._require_active_session()
            with self._state_lock:
                assert self._ram_bytes is not None
                prev_ram = self._ram_bytes
                new_ram = mutator(prev_ram)
                self._edit_seq += 1
                self._last_edit_ts = time.monotonic()

            if transport is not None:
                self._write_ack(transport, frame)

            with self._state_lock:
                if new_ram != prev_ram:
                    self._undo_stack.append(prev_ram)
                self._ram_bytes = new_ram
                self._edit_seq += 1
                self._last_edit_ts = time.monotonic()
                self._last_error = None

            return self.get_state()

    def apply_preset_to_ram(self, raw92: bytes, push_undo: bool = True) -> dict[str, Any]:
        """Apply a 92-byte preset image into live RAM (models before knobs), then re-read RAM."""
        _require_bool(push_undo, "push_undo")
        target = PresetImage.from_bytes(raw92)
        target_bytes = target.to_bytes()

        with self._op_lock:
            transport = self._require_active_session()
            with self._state_lock:
                assert self._ram_bytes is not None
                prev_ram = self._ram_bytes
                self._edit_seq += 1
                self._last_edit_ts = time.monotonic()

            if transport is not None:
                current = PresetImage.from_bytes(prev_ram)
                if current.order != target.order:
                    self._write_ack(transport, build_change_routing(target.order))

                model_changed = [current.models[blk] != target.models[blk] for blk in BLOCK_IDS]
                for blk in BLOCK_IDS:
                    if model_changed[blk]:
                        self._write_ack(transport, build_change_model(blk, target.models[blk]))

                for blk in BLOCK_IDS:
                    for slot in range(6):
                        if model_changed[blk] or current.knobs[blk][slot] != target.knobs[blk][slot]:
                            knob_addr = PresetImage.knob_addr(blk, slot)
                            self._write_ack(transport, build_change_knob(knob_addr, target.knobs[blk][slot]))

                for blk in BLOCK_IDS:
                    if model_changed[blk] or current.states[blk] != target.states[blk]:
                        self._write_ack(transport, build_toggle_block(blk, bool(target.states[blk])))

                if current.volume != target.volume:
                    self._write_ack(transport, build_change_knob(0, target.volume))

                final_bytes = self._read_ram(transport)
            else:
                final_bytes = target_bytes

            with self._state_lock:
                if push_undo and final_bytes != prev_ram:
                    self._undo_stack.append(prev_ram)
                self._ram_bytes = final_bytes
                self._edit_seq += 1
                self._last_edit_ts = time.monotonic()
                self._last_error = None

            return self.get_state()

    def undo(self) -> dict[str, Any]:
        """Replay the most recent 92-byte RAM snapshot from the local undo stack."""
        with self._op_lock:
            self._require_active_session()
            with self._state_lock:
                if not self._undo_stack:
                    return self.get_state()
                target_bytes = self._undo_stack[-1]

            state = self.apply_preset_to_ram(target_bytes, push_undo=False)
            with self._state_lock:
                if self._undo_stack and self._undo_stack[-1] == target_bytes:
                    self._undo_stack.pop()
                state["undo_depth"] = len(self._undo_stack)
            return state

    def save_flash_slot(self, preset_id: int, allow_factory: bool = False) -> dict[str, Any]:
        """Pre-read slot, write atomic pre-save backup, save live RAM to flash, and verify read-back."""
        _require_bool(allow_factory, "allow_factory")
        slot_id = _require_slot_id(preset_id, "preset_id")
        # Validate factory lock upfront before checking transport or touching files.
        build_save_flash(slot_id, b"\x00" * PRESET_SIZE, allow_factory=allow_factory)

        with self._op_lock:
            transport = self._require_active_session()
            with self._state_lock:
                assert self._ram_bytes is not None
                ram_bytes = PresetImage.from_bytes(self._ram_bytes).to_bytes()
                self._flash_busy = True

            try:
                if transport is not None:
                    pre_slot_bytes = self._read_memory(
                        transport, SPACE_PRESET, slot_id * PRESET_SIZE, PRESET_SIZE
                    )
                    with self._state_lock:
                        if len(self._slots) == TOTAL_PRESET_SLOTS:
                            try:
                                self._slots[slot_id] = PresetImage.from_bytes(pre_slot_bytes).to_bytes()
                            except ProtocolError:
                                pass
                else:
                    with self._state_lock:
                        pre_slot_bytes = self._slots[slot_id]

                with self._state_lock:
                    backup_meta = self._write_backup_locked(
                        prefix=f"me01-presave-P{slot_id + 1:02d}",
                        slot_overrides={slot_id: pre_slot_bytes},
                    )
                    backup_path = backup_meta["path"]
                    self._last_backup_path = backup_path

                if transport is not None:
                    self._write_and_verify_flash_slot(
                        transport=transport,
                        slot_id=slot_id,
                        target_bytes=ram_bytes,
                        pre_slot_bytes=pre_slot_bytes,
                        backup_path=backup_path,
                        allow_factory=allow_factory,
                    )

                with self._state_lock:
                    self._slots[slot_id] = ram_bytes
                    self._last_error = None
            finally:
                with self._state_lock:
                    self._flash_busy = False

            state = self.get_state()
            return {
                **state,
                "preset_id": slot_id,
                "label": f"P{slot_id + 1:02d}",
                "backup_path": backup_path,
                "verified": True,
            }

    def export_backup(self, path: Path | None = None) -> dict[str, Any]:
        """Write an atomic JSON backup of all 80 slots and live RAM, returning serializable metadata."""
        dest = Path(path) if path is not None else None
        with self._op_lock:
            self._require_active_session()
            with self._state_lock:
                meta = self._write_backup_locked(prefix="me01-backup", path=dest)
                self._last_backup_path = meta["path"]
                return meta

    def audition_backup_preset(self, backup_data: dict[str, Any], preset_id: int) -> dict[str, Any]:
        """Load one preset from backup JSON into live RAM without modifying flash slots."""
        slot_id = _require_slot_id(preset_id, "preset_id")
        slots = _parse_backup_slots(backup_data)
        return self.apply_preset_to_ram(slots[slot_id], push_undo=True)

    def batch_restore_backup(
        self,
        backup_data: dict[str, Any],
        slot_ids: Sequence[int],
        allow_factory: bool = False,
    ) -> dict[str, Any]:
        """Restore selected slots from backup JSON to flash with safety backup and read-back verify."""
        _require_bool(allow_factory, "allow_factory")
        if isinstance(slot_ids, (str, bytes, bytearray)) or not isinstance(slot_ids, Sequence):
            raise ProtocolError("slot_ids must be a sequence of slot indices")
        if len(slot_ids) == 0:
            raise ProtocolError("slot_ids must not be empty")

        deduped_slots = list(dict.fromkeys(_require_slot_id(sid, "slot_id") for sid in slot_ids))
        backup_slots = _parse_backup_slots(backup_data)
        for slot_id in deduped_slots:
            build_save_flash(slot_id, backup_slots[slot_id], allow_factory=allow_factory)

        with self._op_lock:
            transport = self._require_active_session()
            with self._state_lock:
                self._flash_busy = True

            try:
                pre_snapshots: dict[int, bytes] = {}
                if transport is not None:
                    for slot_id in deduped_slots:
                        pre_snapshots[slot_id] = self._read_memory(
                            transport, SPACE_PRESET, slot_id * PRESET_SIZE, PRESET_SIZE
                        )
                else:
                    with self._state_lock:
                        for slot_id in deduped_slots:
                            pre_snapshots[slot_id] = self._slots[slot_id]

                with self._state_lock:
                    for slot_id, raw in pre_snapshots.items():
                        try:
                            self._slots[slot_id] = PresetImage.from_bytes(raw).to_bytes()
                        except ProtocolError:
                            pass
                    backup_meta = self._write_backup_locked(
                        prefix="me01-prerestore",
                        slot_overrides=pre_snapshots,
                    )
                    backup_path = backup_meta["path"]
                    self._last_backup_path = backup_path

                restored_slots: list[int] = []
                for slot_id in deduped_slots:
                    target_bytes = backup_slots[slot_id]
                    if transport is not None:
                        self._write_and_verify_flash_slot(
                            transport=transport,
                            slot_id=slot_id,
                            target_bytes=target_bytes,
                            pre_slot_bytes=pre_snapshots[slot_id],
                            backup_path=backup_path,
                            allow_factory=allow_factory,
                        )
                    with self._state_lock:
                        self._slots[slot_id] = target_bytes
                    restored_slots.append(slot_id)

                with self._state_lock:
                    self._last_error = None
            finally:
                with self._state_lock:
                    self._flash_busy = False

            state = self.get_state()
            return {
                **state,
                "restored_slots": restored_slots,
                "backup_path": backup_path,
                "verified": True,
            }

    def rename_slot(self, category: str, slot: int, name: str) -> dict[str, Any]:
        """Rename an AMP (0x90000000) or CAB (0x80000000) slot in device flash memory."""
        cat = str(category).lower().strip()
        if cat not in ("amp", "cab"):
            raise ProtocolError(f"category must be 'amp' or 'cab', got {category!r}")
        if not isinstance(name, str):
            raise ProtocolError(f"name must be str, got {type(name).__name__}")
        clean_name = name.strip()
        if not clean_name:
            raise ProtocolError("Slot name cannot be empty")
        slot_idx = _require_range(slot, 0, NAME_RECORD_COUNT - 1, "slot")
        frame = build_rename_slot(cat, slot_idx, clean_name)

        with self._op_lock:
            transport = self._require_active_session()
            with self._state_lock:
                self._edit_seq += 1
                self._last_edit_ts = time.monotonic()

            if transport is not None:
                self._write_ack(transport, frame)
                # Re-read the updated 280-byte name table from hardware
                base_addr = ADDR_AMP_NAMES if cat == "amp" else ADDR_CAB_NAMES
                updated_table = decode_name_table(
                    self._read_memory(transport, SPACE_NAMES, base_addr, NAME_TABLE_SIZE)
                )
                with self._state_lock:
                    if cat == "amp":
                        self._amps = updated_table
                    else:
                        self._cabs = updated_table
            else:
                with self._state_lock:
                    target_list = self._amps if cat == "amp" else self._cabs
                    if slot_idx < len(target_list):
                        target_list[slot_idx] = clean_name[:13]
                    else:
                        while len(target_list) < slot_idx:
                            target_list.append(f"{cat.upper()} {len(target_list) + 1}")
                        target_list.append(clean_name[:13])

            return {
                "ok": True,
                "category": cat,
                "slot": slot_idx,
                "name": clean_name[:13],
                "state": self.get_state(),
            }

    def audition_slot(self, category: str, slot: int) -> dict[str, Any]:
        """Audition an AMP or CAB slot in live RAM, enabling the block so it is heard immediately."""
        cat = str(category).lower().strip()
        if cat not in ("amp", "cab"):
            raise ProtocolError(f"category must be 'amp' or 'cab', got {category!r}")
        slot_idx = _require_range(slot, 0, NAME_RECORD_COUNT - 1, "slot")
        block_id = 1 if cat == "amp" else 5

        # 1. Change model in RAM
        self.change_model(block_id, slot_idx)

        # 2. Ensure block is enabled so sound passes through
        with self._state_lock:
            ram = self._ram_bytes
        if ram:
            img = PresetImage.from_bytes(ram)
            if not img.states[block_id]:
                self.toggle_block(block_id, True)

        return {
            "ok": True,
            "category": cat,
            "slot": slot_idx,
            "block_id": block_id,
            "state": self.get_state(),
        }

    def get_curated_library(self) -> dict[str, Any]:
        """Return the curated library of native community Overdrives, Amps, and Cabinet IRs."""
        return {
            "categories": [
                {
                    "id": "overdrives",
                    "name": "Overdrives & Distortions",
                    "kind": "amp",
                    "models": [
                        {
                            "id": "ts9",
                            "name": "3VAVE_TS",
                            "display_name": "Tube Screamer TS9",
                            "origin": "Ibanez TS9 / M-VAVE",
                            "desc": "Classic mid-hump overdrive, smooth saturation, tight low-end boost",
                            "tags": ["Overdrive", "Mid Boost", "Classic"],
                        },
                        {
                            "id": "rat",
                            "name": "4RAT_OD",
                            "display_name": "ProCo RAT",
                            "origin": "ProCo RAT / M-VAVE",
                            "desc": "Aggressive hard-clipping distortion with rich harmonic fuzz edge",
                            "tags": ["Distortion", "Fuzz", "Rock"],
                        },
                        {
                            "id": "guvnor",
                            "name": "7MS_GV2",
                            "display_name": "Marshall Guv'nor",
                            "origin": "Marshall Guv'nor / M-VAVE",
                            "desc": "Plexi-in-a-box British overdrive with full 3-band EQ response",
                            "tags": ["Overdrive", "British", "Plexi"],
                        },
                        {
                            "id": "ds1",
                            "name": "6VAVE_DS",
                            "display_name": "Orange Distortion",
                            "origin": "Boss DS-1 Style / M-VAVE",
                            "desc": "Pronounced mid-scoop hard clipping distortion for grunge and 80s rock",
                            "tags": ["Distortion", "Orange", "80s"],
                        },
                        {
                            "id": "hts",
                            "name": "5VAVE_HTS",
                            "display_name": "High-Gain TS",
                            "origin": "M-VAVE Custom TS",
                            "desc": "Hot-rodded Tube Screamer with extended gain range and clarity",
                            "tags": ["Overdrive", "Hot Rod", "Lead"],
                        },
                        {
                            "id": "marsh_drive",
                            "name": "6 marshalldri",
                            "display_name": "Marshall Drive",
                            "origin": "Marshall Bluesbreaker Capture",
                            "desc": "Organic tube overdrive breaking into natural British power-amp grind",
                            "tags": ["Overdrive", "Blues", "Crunch"],
                        },
                        {
                            "id": "od_marvicto",
                            "name": "4OD-MarVicto",
                            "display_name": "Victory OD",
                            "origin": "Victory Marshall Overdrive",
                            "desc": "Modern boutique British high-headroom overdrive",
                            "tags": ["Overdrive", "Boutique", "Modern"],
                        },
                    ],
                },
                {
                    "id": "clean",
                    "name": "Clean Preamps & Amps",
                    "kind": "amp",
                    "models": [
                        {
                            "id": "jc120",
                            "name": "1J120_CL",
                            "display_name": "Roland JC-120",
                            "origin": "Roland Jazz Chorus",
                            "desc": "Ultra-clean solid-state platform with crystalline highs",
                            "tags": ["Clean", "Solid State", "Chorus"],
                        },
                        {
                            "id": "jcm900_cl",
                            "name": "2J900_CL",
                            "display_name": "JCM900 Clean",
                            "origin": "Marshall JCM900 Channel A",
                            "desc": "Bright British clean with articulate chime",
                            "tags": ["Clean", "British", "Chime"],
                        },
                        {
                            "id": "fender_twin",
                            "name": "1UWE-Twins",
                            "display_name": "Fender '65 Twin",
                            "origin": "Fender Twin Reverb",
                            "desc": "American blackface clean headroom, deep lows, sparkling bell highs",
                            "tags": ["Clean", "American", "Blackface"],
                        },
                        {
                            "id": "vox_ac30",
                            "name": "2UK-C30Normal",
                            "display_name": "Vox AC30 Top Boost",
                            "origin": "Vox AC30",
                            "desc": "Class-A British chime, glassy breakup at edge of overdrive",
                            "tags": ["Clean", "Chime", "Class A"],
                        },
                    ],
                },
                {
                    "id": "crunch",
                    "name": "Crunch & Classic Rock",
                    "kind": "amp",
                    "models": [
                        {
                            "id": "jcm800",
                            "name": "Marshall 800",
                            "display_name": "Marshall JCM800",
                            "origin": "Marshall 2203 JCM800",
                            "desc": "The definitive 80s hard rock voice with cutting midrange bite",
                            "tags": ["Crunch", "Hard Rock", "British"],
                        },
                        {
                            "id": "victor_mars",
                            "name": "4Victor Mars",
                            "display_name": "Victory Sheriff",
                            "origin": "Victory Amps",
                            "desc": "Boutique hot-rodded vintage British crunch",
                            "tags": ["Crunch", "Boutique", "Rock"],
                        },
                        {
                            "id": "engl_savage",
                            "name": "7ENGL SAVAGE",
                            "display_name": "Engl Savage 120",
                            "origin": "ENGL Savage",
                            "desc": "German precision high-gain crunch with brutal attack",
                            "tags": ["Crunch", "German", "Tight"],
                        },
                    ],
                },
                {
                    "id": "highgain",
                    "name": "High-Gain & Modern Lead",
                    "kind": "amp",
                    "models": [
                        {
                            "id": "evh5150",
                            "name": "9EVH 5150",
                            "display_name": "Peavey 5150 / 6505",
                            "origin": "EVH 5150 Block Letter",
                            "desc": "Legendary modern metal tone with crushing gain and aggressive bite",
                            "tags": ["High Gain", "Metal", "Modern"],
                        },
                        {
                            "id": "fortin_cali",
                            "name": "10Fortin Cali",
                            "display_name": "Fortin Cali Mod",
                            "origin": "Fortin Amplification",
                            "desc": "Ultra-tight boutique modified high-gain monster",
                            "tags": ["High Gain", "Djent", "Boutique"],
                        },
                        {
                            "id": "soldano",
                            "name": "NDSP Soldano",
                            "display_name": "Soldano SLO-100",
                            "origin": "Neural DSP Soldano SLO-100",
                            "desc": "Singing saturation, thick creamy leads, and huge low-end punch",
                            "tags": ["High Gain", "Lead", "American"],
                        },
                        {
                            "id": "mesa_recto",
                            "name": "12MES-FG",
                            "display_name": "Mesa Dual Rectifier",
                            "origin": "Mesa Boogie Dual Rectifier",
                            "desc": "Massive wall-of-sound distortion with scoopable mids and booming bass",
                            "tags": ["High Gain", "Wall of Sound", "90s Metal"],
                        },
                        {
                            "id": "friedman",
                            "name": "Friedman Pink",
                            "display_name": "Friedman Pink Taco",
                            "origin": "Friedman Amplification",
                            "desc": "Modified Plexi saturation with harmonically rich overdrive",
                            "tags": ["High Gain", "Lead", "Boutique"],
                        },
                    ],
                },
                {
                    "id": "bass",
                    "name": "Bass Amplifiers",
                    "kind": "amp",
                    "models": [
                        {
                            "id": "ampeg_svt",
                            "name": "17ApSVT_BS",
                            "display_name": "Ampeg SVT Classic",
                            "origin": "Ampeg SVT",
                            "desc": "All-tube 300W bass power with thunderous low end and tube growl",
                            "tags": ["Bass", "Tube", "Rock"],
                        },
                        {
                            "id": "aguilar",
                            "name": "16AgDb750_BS",
                            "display_name": "Aguilar DB750",
                            "origin": "Aguilar DB750",
                            "desc": "Hybrid tube-preamp bass amplifier with huge headroom and punch",
                            "tags": ["Bass", "Punch", "Modern"],
                        },
                        {
                            "id": "darkglass",
                            "name": "19DgXu_BS",
                            "display_name": "Darkglass Microtubes",
                            "origin": "Darkglass Electronics",
                            "desc": "Cutting aggressive bass distortion with surgical clean blend",
                            "tags": ["Bass", "Distortion", "Metal"],
                        },
                    ],
                },
                {
                    "id": "cabinets",
                    "name": "Cabinet Impulse Responses (IRs)",
                    "kind": "cab",
                    "models": [
                        {
                            "id": "mrsh_1960",
                            "name": "Marshall 1960",
                            "display_name": "Marshall 1960A 4x12 G12T-75",
                            "origin": "Marshall / Shure SM57",
                            "desc": "Industry standard 4x12 rock cabinet with scooped mids and crisp highs",
                            "tags": ["Cab IR", "4x12", "Rock"],
                        },
                        {
                            "id": "mesa_v30",
                            "name": "Mesa 4x12 Ove",
                            "display_name": "Mesa Oversized 4x12 V30",
                            "origin": "Mesa Boogie / Celestion V30",
                            "desc": "Huge low-end resonance and focused midrange punch for heavy music",
                            "tags": ["Cab IR", "4x12", "Metal"],
                        },
                        {
                            "id": "vox_212",
                            "name": "04B_Vox 2 AC1",
                            "display_name": "Vox AC30 2x12 Alnico Blue",
                            "origin": "Vox 2x12 / Celestion Blue",
                            "desc": "Sparkling chime and warm vintage midrange compression",
                            "tags": ["Cab IR", "2x12", "Vintage"],
                        },
                        {
                            "id": "orange_212",
                            "name": "10OrPPC212",
                            "display_name": "Orange PPC212 Closed Back",
                            "origin": "Orange / Celestion V30",
                            "desc": "Thick heavy birch construction with dark punchy response",
                            "tags": ["Cab IR", "2x12", "Stoner/Doom"],
                        },
                        {
                            "id": "ampeg_810",
                            "name": "AgSVT410",
                            "display_name": "Ampeg SVT 8x10 Refrigerator",
                            "origin": "Ampeg 8x10",
                            "desc": "The benchmark stadium bass cabinet with tight punch and infinite low end",
                            "tags": ["Cab IR", "Bass", "8x10"],
                        },
                    ],
                },
            ]
        }

    def _resolve_ports(
        self, in_id: int | None, out_id: int | None
    ) -> tuple[int, int, dict[str, Any]]:
        if in_id is None or out_id is None:
            pairs = sorted(
                self._port_finder(),
                key=lambda p: (-int(p.match_score), int(p.in_id), int(p.out_id)),
            )
            if not pairs:
                raise MidiTransportError("No matching USB-MIDI input/output port pairs found")
            best = pairs[0]
            resolved_in = best.in_id if in_id is None else in_id
            resolved_out = best.out_id if out_id is None else out_id
            matched = next(
                (p for p in pairs if p.in_id == resolved_in and p.out_id == resolved_out),
                best if (in_id is None and out_id is None) else None,
            )
            if matched is not None:
                return resolved_in, resolved_out, _normalize_port_pair(matched)
            return (
                resolved_in,
                resolved_out,
                {
                    "in_id": resolved_in,
                    "in_name": f"MIDI In {resolved_in}",
                    "out_id": resolved_out,
                    "out_name": f"MIDI Out {resolved_out}",
                    "match_score": 0,
                },
            )

        if self._custom_port_finder is not None:
            for pair in self._custom_port_finder():
                if pair.in_id == in_id and pair.out_id == out_id:
                    return in_id, out_id, _normalize_port_pair(pair)

        return (
            in_id,
            out_id,
            {
                "in_id": in_id,
                "in_name": f"MIDI In {in_id}",
                "out_id": out_id,
                "out_name": f"MIDI Out {out_id}",
                "match_score": 0,
            },
        )

    def _require_active_session(self) -> Any:
        with self._state_lock:
            if self._connected:
                if self._transport is None or self._ram_bytes is None:
                    raise MidiTransportError("Connected transport state is incomplete")
                return self._transport
            if self._demo:
                if self._ram_bytes is None:
                    raise MidiTransportError("Demo state is not initialized")
                return None
            raise MidiTransportError("Device is not connected (connect to ME-01 or enter demo mode)")

    def _start_polling_locked(self) -> None:
        stop_event = threading.Event()
        thread = threading.Thread(
            target=self._poll_loop,
            args=(stop_event,),
            name="me01-poll",
            daemon=True,
        )
        self._poll_stop = stop_event
        self._poll_thread = thread
        thread.start()

    def _poll_loop(self, stop_event: threading.Event) -> None:
        while not stop_event.wait(self._poll_interval_s):
            try:
                self.poll_once()
            except Exception as exc:
                with self._state_lock:
                    if self._connected:
                        self._last_error = str(exc)

    def _write_backup_locked(
        self,
        *,
        prefix: str,
        path: Path | None = None,
        slot_overrides: dict[int, bytes] | None = None,
    ) -> dict[str, Any]:
        slots = list(self._slots)
        if slot_overrides:
            for idx, raw in slot_overrides.items():
                slots[idx] = raw

        created_at = datetime.now(timezone.utc).isoformat()
        payload = {
            "version": 1,
            "created_at": created_at,
            "identity": self._identity,
            "active_preset": self._active_preset,
            "amps": list(self._amps),
            "cabs": list(self._cabs),
            "ram_hex": self._ram_bytes.hex() if self._ram_bytes is not None else "",
            "presets_hex": [raw.hex() for raw in slots],
        }
        dest = path if path is not None else _unique_backup_path(self._backup_dir, prefix)
        written = _write_json_atomic(dest, payload)
        return {
            "path": str(written),
            "filename": written.name,
            "created_at": created_at,
            "preset_count": len(slots),
            "data": payload,
        }

    def _write_and_verify_flash_slot(
        self,
        *,
        transport: Any,
        slot_id: int,
        target_bytes: bytes,
        pre_slot_bytes: bytes,
        backup_path: str,
        allow_factory: bool,
    ) -> None:
        save_frame = build_save_flash(slot_id, target_bytes, allow_factory=allow_factory)
        try:
            self._write_ack(transport, save_frame, timeout_ms=FLASH_SAVE_TIMEOUT_MS)
            readback = self._read_memory(
                transport,
                SPACE_PRESET,
                slot_id * PRESET_SIZE,
                PRESET_SIZE,
                timeout_ms=DEFAULT_TIMEOUT_MS,
            )
        except Exception as exc:
            msg = (
                f"Flash write/read-back failed on P{slot_id + 1:02d} "
                f"(pre-save backup saved at {backup_path}): {exc}"
            )
            with self._state_lock:
                self._last_error = msg
            raise MidiTransportError(msg) from exc

        if readback == target_bytes:
            return

        restore_status = "restore succeeded"
        try:
            restore_frame = build_save_flash(slot_id, pre_slot_bytes, allow_factory=True)
            self._write_ack(transport, restore_frame, timeout_ms=FLASH_SAVE_TIMEOUT_MS)
            try:
                verify_restore = self._read_memory(
                    transport,
                    SPACE_PRESET,
                    slot_id * PRESET_SIZE,
                    PRESET_SIZE,
                    timeout_ms=DEFAULT_TIMEOUT_MS,
                )
                if verify_restore == pre_slot_bytes:
                    with self._state_lock:
                        if len(self._slots) == TOTAL_PRESET_SLOTS:
                            self._slots[slot_id] = pre_slot_bytes
                else:
                    restore_status = "restore verification mismatch"
            except Exception as verify_exc:
                restore_status = f"restore written, verify error: {verify_exc}"
        except Exception as restore_exc:
            restore_status = f"restore failed: {restore_exc}"

        msg = (
            f"Flash read-back mismatch on P{slot_id + 1:02d}; attempted single restore "
            f"({restore_status}). Pre-save backup saved at {backup_path}"
        )
        with self._state_lock:
            self._last_error = msg
        raise MidiTransportError(msg)

    @staticmethod
    def _build_preset_summary(
        idx: int, raw92: bytes, amps: list[str], cabs: list[str]
    ) -> dict[str, Any]:
        img = PresetImage.from_bytes(raw92)
        amp_id = img.models[1]
        cab_id = img.models[5]
        amp_name = amps[amp_id] if 0 <= amp_id < len(amps) else BLOCKS[1].models[amp_id].name
        cab_name = cabs[cab_id] if 0 <= cab_id < len(cabs) else BLOCKS[5].models[cab_id].name
        return {
            "preset_id": idx,
            "label": f"P{idx + 1:02d}",
            "bank": "factory" if idx < FACTORY_SLOT_COUNT else "user",
            "locked": idx < FACTORY_SLOT_COUNT,
            "volume": img.volume,
            "order": list(img.order),
            "states": list(img.states),
            "models": list(img.models),
            "amp_name": amp_name,
            "cab_name": cab_name,
            "raw_hex": raw92.hex(),
        }

    @staticmethod
    def _read_identity(transport: Any) -> str:
        reply = transport.transact(wrap_sysex(build_identity_query()), timeout_ms=DEFAULT_TIMEOUT_MS)
        frame = parse_frame(unwrap_sysex(reply))
        if frame.cmd != CMD_IDENTITY:
            raise ProtocolError(f"Expected identity reply (0x11), got 0x{frame.cmd:02x}")
        return frame.body.split(b"\x00", 1)[0].decode("ascii", errors="replace").strip()

    @staticmethod
    def _read_memory(
        transport: Any,
        space: int,
        addr: int,
        size: int,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ) -> bytes:
        req = wrap_sysex(build_read_request(space, addr, size))
        reply = transport.transact(req, timeout_ms=timeout_ms)
        frame = parse_frame(unwrap_sysex(reply))
        if frame.cmd != CMD_READ:
            raise ProtocolError(f"Expected read reply (0x23), got 0x{frame.cmd:02x}")
        if frame.space != space or frame.address != addr:
            raise ProtocolError(
                f"Read reply address mismatch: expected space=0x{space:02x} addr=0x{addr:08x}, "
                f"got space={frame.space} addr={frame.address}"
            )
        if len(frame.data) != size:
            raise ProtocolError(
                f"Read reply size mismatch: expected {size} bytes, got {len(frame.data)}"
            )
        return frame.data

    @classmethod
    def _read_active_preset(cls, transport: Any) -> int:
        data = cls._read_memory(transport, SPACE_PRESET, ADDR_ACTIVE_PRESET, 4)
        return _require_slot_id(data[0], "active_preset")

    @classmethod
    def _read_ram(cls, transport: Any) -> bytes:
        raw = cls._read_memory(transport, SPACE_PRESET, ADDR_RAM_BASE, PRESET_SIZE)
        return PresetImage.from_bytes(raw).to_bytes()

    @staticmethod
    def _write_ack(transport: Any, frame_bytes: bytes, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> None:
        reply = transport.transact(wrap_sysex(frame_bytes), timeout_ms=timeout_ms)
        raw_reply = unwrap_sysex(reply)
        parse_frame(raw_reply)
        if not is_ack_frame(raw_reply):
            raise ProtocolError(f"Expected ME-01 write ACK frame, got {raw_reply.hex()}")

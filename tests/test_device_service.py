from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any, Callable

from me01_rig.device_service import DeviceService
from me01_rig.protocol import (
    ACK_FRAME,
    ADDR_ACTIVE_PRESET,
    ADDR_AMP_NAMES,
    ADDR_CAB_NAMES,
    ADDR_LOAD_PRESET_BASE,
    ADDR_RAM_BASE,
    ADDR_RAM_ROUTING,
    BLOCKS,
    CMD_IDENTITY,
    CMD_READ,
    CMD_WRITE,
    NAME_TABLE_SIZE,
    PRESET_SIZE,
    SPACE_NAMES,
    SPACE_PRESET,
    TOTAL_PRESET_SLOTS,
    FactorySlotLockedError,
    PresetImage,
    ProtocolError,
    build_frame,
    parse_frame,
    unwrap_sysex,
    wrap_sysex,
)
from me01_rig.winmm_midi import MidiPortPair, MidiTransportError

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "me01_captured_vectors.json"


class FakeTransport:
    """In-memory ME-01 Sinco USB-MIDI SysEx transport for deterministic tests."""

    def __init__(self, fixture_data: dict[str, Any], in_id: int = 0, out_id: int = 1) -> None:
        self.in_id = in_id
        self.out_id = out_id
        self.is_open = False
        self.closed_count = 0
        self.identity = str(fixture_data["identity"])
        self.active_preset = int(fixture_data["active_preset"])
        self.ram = bytearray.fromhex(fixture_data["ram_hex"])
        self.slots = [bytearray.fromhex(h) for h in fixture_data["presets_hex"]]

        vectors = fixture_data["captured_vectors"]
        self.amps_table = bytearray(parse_frame(unwrap_sysex(bytes.fromhex(vectors["amps_raw"]))).data)
        self.cabs_table = bytearray(parse_frame(unwrap_sysex(bytes.fromhex(vectors["cabs_raw"]))).data)

        self.write_log: list[tuple[int, bytes, int]] = []
        self.read_log: list[tuple[int, int, int]] = []
        self.flash_writes: list[tuple[int, bytes, int]] = []

        # Fault-injection & race test hooks
        self.reset_knobs_on_model_change = False
        self.corrupt_next_flash_write = False
        self.fail_next_restore_write = False
        self.fail_on_flash_write_slot: int | None = None
        self.on_transact: Callable[[FakeTransport, Any], None] | None = None
        self._lock = threading.Lock()

    def open(self) -> None:
        self.is_open = True

    def close(self) -> None:
        self.is_open = False
        self.closed_count += 1

    def transact(self, sysex_out: bytes, timeout_ms: int = 800) -> bytes:
        if not self.is_open:
            raise MidiTransportError("FakeTransport is not open")
        req = parse_frame(unwrap_sysex(sysex_out))
        if self.on_transact is not None:
            self.on_transact(self, req)

        with self._lock:
            if req.cmd == CMD_IDENTITY:
                ident_bytes = self.identity.encode("ascii").ljust(27, b"\x00")
                return wrap_sysex(build_frame(CMD_IDENTITY, ident_bytes))

            if req.cmd == CMD_READ:
                assert req.space is not None and req.address is not None and req.size is not None
                self.read_log.append((req.space, req.address, req.size))
                payload = self._handle_read(req.space, req.address, req.size)
                body = (
                    bytes([req.space])
                    + req.address.to_bytes(4, "little")
                    + len(payload).to_bytes(3, "little")
                    + payload
                )
                return wrap_sysex(build_frame(CMD_READ, body))

            if req.cmd == CMD_WRITE:
                assert req.space is not None and req.address is not None
                self.write_log.append((req.address, req.data, timeout_ms))
                self._handle_write(req.space, req.address, req.data, timeout_ms)
                return wrap_sysex(ACK_FRAME)

            raise ProtocolError(f"Unsupported fake command: 0x{req.cmd:02x}")

    def _handle_read(self, space: int, addr: int, size: int) -> bytes:
        if space == SPACE_NAMES:
            if addr == ADDR_AMP_NAMES and size == NAME_TABLE_SIZE:
                return self.amps_table
            if addr == ADDR_CAB_NAMES and size == NAME_TABLE_SIZE:
                return self.cabs_table
            raise ProtocolError(f"Unexpected name table read: addr=0x{addr:08x}, size={size}")

        if space == SPACE_PRESET:
            if addr == ADDR_ACTIVE_PRESET and size == 4:
                return bytes([self.active_preset, self.active_preset, 0, 0])
            if addr == ADDR_RAM_BASE and size == PRESET_SIZE:
                return bytes(self.ram)
            if addr < TOTAL_PRESET_SLOTS * PRESET_SIZE and addr % PRESET_SIZE == 0 and size == PRESET_SIZE:
                slot = addr // PRESET_SIZE
                return bytes(self.slots[slot])

        raise ProtocolError(f"Unexpected read: space=0x{space:02x}, addr=0x{addr:08x}, size={size}")

    def _handle_write(self, space: int, addr: int, data: bytes, timeout_ms: int) -> None:
        if space == SPACE_NAMES:
            if ADDR_AMP_NAMES <= addr < ADDR_AMP_NAMES + NAME_TABLE_SIZE:
                offset = addr - ADDR_AMP_NAMES
                self.amps_table[offset : offset + len(data)] = data
                return
            if ADDR_CAB_NAMES <= addr < ADDR_CAB_NAMES + NAME_TABLE_SIZE:
                offset = addr - ADDR_CAB_NAMES
                self.cabs_table[offset : offset + len(data)] = data
                return
            raise ProtocolError(f"Unexpected name table write: addr=0x{addr:08x}")

        if space != SPACE_PRESET:
            raise ProtocolError(f"Unexpected write space: 0x{space:02x}")

        if ADDR_LOAD_PRESET_BASE <= addr < ADDR_LOAD_PRESET_BASE + TOTAL_PRESET_SLOTS:
            slot = addr - ADDR_LOAD_PRESET_BASE
            self.active_preset = slot
            self.ram[:] = self.slots[slot]
            return

        if addr == ADDR_RAM_ROUTING and len(data) == 6:
            self.ram[2:8] = data
            return

        if ADDR_RAM_BASE + 0x08 <= addr <= ADDR_RAM_BASE + 0x0D and len(data) == 1:
            blk = addr - (ADDR_RAM_BASE + 0x08)
            self.ram[0x08 + blk] = data[0]
            return

        if ADDR_RAM_BASE + 0x0E <= addr <= ADDR_RAM_BASE + 0x13 and len(data) == 1:
            blk = addr - (ADDR_RAM_BASE + 0x0E)
            self.ram[0x0E + blk] = data[0]
            if self.reset_knobs_on_model_change:
                base = BLOCKS[blk].base_addr
                for slot in range(6):
                    self.ram[base + slot * 2 : base + slot * 2 + 2] = (0).to_bytes(2, "little")
            return

        if addr == ADDR_RAM_BASE and len(data) == 2:
            self.ram[0:2] = data
            return

        if ADDR_RAM_BASE + 0x14 <= addr <= ADDR_RAM_BASE + 0x5A and (addr - ADDR_RAM_BASE) % 2 == 0 and len(data) == 2:
            offset = addr - ADDR_RAM_BASE
            self.ram[offset : offset + 2] = data
            return

        if addr < TOTAL_PRESET_SLOTS * PRESET_SIZE and addr % PRESET_SIZE == 0 and len(data) == PRESET_SIZE:
            slot = addr // PRESET_SIZE
            if self.fail_on_flash_write_slot == slot:
                raise MidiTransportError(f"Simulated flash write timeout on slot {slot}")
            is_restore_attempt = any(w_slot == slot for w_slot, _, _ in self.flash_writes)
            self.flash_writes.append((slot, bytes(data), timeout_ms))
            if is_restore_attempt and self.fail_next_restore_write:
                self.fail_next_restore_write = False
                raise MidiTransportError("Simulated USB error during restore write")
            stored = bytearray(data)
            if self.corrupt_next_flash_write:
                self.corrupt_next_flash_write = False
                stored[0] ^= 0x01
            self.slots[slot][:] = stored
            return

        raise ProtocolError(f"Disallowed or unexpected write: addr=0x{addr:08x}, len={len(data)}")


class DeviceServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture_data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        self.temp_dir = tempfile.TemporaryDirectory()
        self.backup_dir = Path(self.temp_dir.name) / "backups"
        self.transports: list[FakeTransport] = []

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _make_service(
        self,
        *,
        poll_interval_s: float = 0.05,
        suppress_window_s: float = 0.25,
        port_pairs: list[MidiPortPair] | None = None,
    ) -> DeviceService:
        if port_pairs is None:
            port_pairs = [
                MidiPortPair(0, "Microsoft GS Wavetable Synth", 0, "Microsoft GS Wavetable Synth", 20),
                MidiPortPair(2, "USB-Midi", 3, "USB-Midi", 150),
            ]

        def factory(in_id: int, out_id: int) -> FakeTransport:
            transport = FakeTransport(self.fixture_data, in_id=in_id, out_id=out_id)
            self.transports.append(transport)
            return transport

        return DeviceService(
            backup_dir=self.backup_dir,
            fixture_path=FIXTURE_PATH,
            transport_factory=factory,
            poll_interval_s=poll_interval_s,
            suppress_window_s=suppress_window_s,
            port_finder=lambda: list(port_pairs),
        )

    def test_connect_handshake_and_auto_backup(self) -> None:
        svc = self._make_service()
        ports = svc.list_ports()
        self.assertEqual(len(ports), 2)
        self.assertEqual(ports[0]["in_id"], 0)

        state = svc.connect(auto_backup=True, start_polling=False)
        self.addCleanup(svc.disconnect)

        self.assertTrue(state["connected"])
        self.assertFalse(state["demo"])
        self.assertEqual(state["identity"], "ME-01_016")
        self.assertEqual(state["ports"]["in_id"], 2)
        self.assertEqual(state["ports"]["out_id"], 3)
        self.assertEqual(state["active_preset"], 71)
        self.assertEqual(len(state["amps"]), 20)
        self.assertEqual(state["amps"][0], "UWE-Twins")
        self.assertEqual(len(state["cabs"]), 20)
        self.assertEqual(state["cabs"][0], "AC-SeVin")
        self.assertEqual(state["cabs"][16], "412 Mesa Stan")
        self.assertEqual(state["ram"]["raw_hex"], self.fixture_data["ram_hex"])
        self.assertFalse(state["dirty_from_slot"])
        self.assertEqual(state["undo_depth"], 0)
        self.assertIsNone(state["last_error"])

        presets = svc.get_presets()
        self.assertEqual(len(presets), 80)
        self.assertEqual(presets[0]["label"], "P01")
        self.assertEqual(presets[0]["bank"], "factory")
        self.assertTrue(presets[0]["locked"])
        self.assertEqual(presets[79]["label"], "P80")
        self.assertEqual(presets[79]["bank"], "user")
        self.assertFalse(presets[79]["locked"])
        self.assertEqual(presets[71]["parsed"]["raw_hex"], self.fixture_data["p72_hex"])

        backup_path_str = state["last_backup_path"]
        self.assertIsNotNone(backup_path_str)
        backup_path = Path(backup_path_str)
        self.assertTrue(backup_path.exists())
        backup_json = json.loads(backup_path.read_text(encoding="utf-8"))
        self.assertEqual(backup_json["identity"], "ME-01_016")
        self.assertEqual(len(backup_json["presets_hex"]), 80)
        self.assertEqual(backup_json["presets_hex"][0], self.fixture_data["p01_hex"])

        # Reconnecting in the same session should not spam a second auto-backup.
        svc.connect(auto_backup=True, start_polling=False)
        backup_files = list(self.backup_dir.glob("*.json"))
        self.assertEqual(len(backup_files), 1)

        # Empty port list when no IDs specified raises MidiTransportError.
        empty_svc = self._make_service(port_pairs=[])
        with self.assertRaises(MidiTransportError):
            empty_svc.connect(start_polling=False)

    def test_poll_respects_edit_suppression_window_and_inflight_race(self) -> None:
        svc = self._make_service(suppress_window_s=0.2)
        self.assertFalse(svc.poll_once())

        svc.connect(auto_backup=False, start_polling=False)
        self.addCleanup(svc.disconnect)
        transport = self.transports[-1]

        # Local edit updates cached RAM and sets suppression window.
        edited = svc.change_knob(0, 42)
        self.assertEqual(edited["ram"]["volume"], 42)
        self.assertTrue(edited["dirty_from_slot"])

        # Simulate external hardware change while still inside suppression window.
        transport.ram[0:2] = (99).to_bytes(2, "little")
        self.assertFalse(svc.poll_once())
        self.assertEqual(svc.get_state()["ram"]["volume"], 42)

        # Wait for suppression window to expire -> poll_once syncs hardware RAM.
        time.sleep(0.25)
        self.assertTrue(svc.poll_once())
        synced = svc.get_state()
        self.assertEqual(synced["ram"]["volume"], 99)

        # In-flight race: poll_once starts a RAM read, and a local edit occurs before reply lands.
        poll_reading = threading.Event()
        allow_reply = threading.Event()

        def hook(tr: FakeTransport, req: Any) -> None:
            if req.cmd == CMD_READ and req.address == ADDR_RAM_BASE:
                poll_reading.set()
                allow_reply.wait(timeout=2.0)
                tr.on_transact = None

        transport.on_transact = hook
        poll_result: list[bool] = []

        def run_poll() -> None:
            poll_result.append(svc.poll_once())

        t = threading.Thread(target=run_poll)
        t.start()
        self.assertTrue(poll_reading.wait(timeout=2.0))

        # Local edit while poll_once's read is blocked in-flight.
        svc.change_knob(0, 33)
        allow_reply.set()
        t.join(timeout=2.0)

        self.assertEqual(poll_result, [False])
        self.assertEqual(svc.get_state()["ram"]["volume"], 33)

    def test_change_model_rereads_ram_and_undo_restores(self) -> None:
        svc = self._make_service(suppress_window_s=0.2)
        svc.connect(auto_backup=False, start_polling=False)
        self.addCleanup(svc.disconnect)
        transport = self.transports[-1]

        original_raw_hex = svc.get_state()["ram"]["raw_hex"]
        original_img = PresetImage.from_bytes(bytes.fromhex(original_raw_hex))
        transport.reset_knobs_on_model_change = True

        # Switch AMP model (block 1) from 18 -> 5; fake firmware resets AMP knobs to 0.
        read_count_before = len(transport.read_log)
        after_model = svc.change_model(1, 5)
        read_count_after = len(transport.read_log)

        self.assertGreater(read_count_after, read_count_before)
        self.assertIn((SPACE_PRESET, ADDR_RAM_BASE, PRESET_SIZE), transport.read_log[read_count_before:])
        self.assertEqual(after_model["ram"]["models"][1], 5)
        self.assertEqual(after_model["ram"]["knobs"][1], [0, 0, 0, 0, 0, 0])
        self.assertTrue(after_model["dirty_from_slot"])
        self.assertEqual(after_model["undo_depth"], 1)

        # Undo must replay model BEFORE knobs so restored knobs are NOT wiped to 0.
        restored = svc.undo()
        self.assertEqual(restored["undo_depth"], 0)
        self.assertEqual(restored["ram"]["raw_hex"], original_raw_hex)
        self.assertEqual(restored["ram"]["knobs"][1], original_img.knobs[1])
        self.assertFalse(restored["dirty_from_slot"])

        # Verify toggle, routing, load_preset, revert_to_slot, refresh_ram.
        svc.toggle_block(2, True)
        self.assertEqual(svc.get_state()["ram"]["states"][2], 1)
        svc.change_routing([5, 4, 3, 2, 1, 0])
        self.assertEqual(svc.get_state()["ram"]["order"], [5, 4, 3, 2, 1, 0])
        svc.revert_to_slot()
        self.assertEqual(svc.get_state()["ram"]["raw_hex"], original_raw_hex)
        self.assertFalse(svc.get_state()["dirty_from_slot"])

        # External RAM mutation picked up by refresh_ram.
        transport.ram[0:2] = (77).to_bytes(2, "little")
        refreshed = svc.refresh_ram()
        self.assertEqual(refreshed["ram"]["volume"], 77)

        svc.load_preset(0)
        self.assertEqual(svc.get_state()["active_preset"], 0)
        self.assertEqual(svc.get_state()["ram"]["raw_hex"], self.fixture_data["p01_hex"])

    def test_flash_save_readback_mismatch_triggers_single_restore(self) -> None:
        svc = self._make_service()
        svc.connect(auto_backup=False, start_polling=False)
        self.addCleanup(svc.disconnect)
        transport = self.transports[-1]

        original_p80 = bytes(transport.slots[79])
        svc.change_knob(0, 15)
        intended_ram = bytes.fromhex(svc.get_state()["ram"]["raw_hex"])
        self.assertNotEqual(intended_ram, original_p80)

        # Factory slot lock & strict bool check before write.
        with self.assertRaises(FactorySlotLockedError):
            svc.save_flash_slot(5, allow_factory=False)
        with self.assertRaises(ProtocolError):
            svc.save_flash_slot(79, allow_factory=1)  # type: ignore[arg-type]

        # Inject single read-back corruption on slot 79 save.
        transport.corrupt_next_flash_write = True
        with self.assertRaises(MidiTransportError) as ctx:
            svc.save_flash_slot(79)

        err_msg = str(ctx.exception)
        backup_files = list(self.backup_dir.glob("*.json"))
        self.assertEqual(len(backup_files), 1)
        pre_backup_path = backup_files[0]
        self.assertIn(str(pre_backup_path), err_msg)

        # Verify pre-save backup contains original P80 bytes.
        pre_backup_data = json.loads(pre_backup_path.read_text(encoding="utf-8"))
        self.assertEqual(pre_backup_data["presets_hex"][79], original_p80.hex())

        # Exactly 2 flash writes: 1 initial write + 1 single restore write (no retry loop).
        self.assertEqual(len(transport.flash_writes), 2)
        self.assertEqual(transport.flash_writes[0], (79, intended_ram, 3000))
        self.assertEqual(transport.flash_writes[1], (79, original_p80, 3000))
        self.assertEqual(bytes(transport.slots[79]), original_p80)

        # Even if restore write itself fails, it does not loop and cites backup path.
        transport.flash_writes.clear()
        transport.corrupt_next_flash_write = True
        transport.fail_next_restore_write = True
        with self.assertRaises(MidiTransportError) as ctx2:
            svc.save_flash_slot(79)
        self.assertEqual(len(transport.flash_writes), 2)
        self.assertIn(str(self.backup_dir), str(ctx2.exception))

        # Happy-path flash save updates slot and passes read-back verification.
        transport.flash_writes.clear()
        svc.load_preset(79)
        svc.change_knob(0, 22)
        saved = svc.save_flash_slot(79)
        self.assertTrue(saved["verified"])
        self.assertEqual(len(transport.flash_writes), 1)
        self.assertFalse(saved["dirty_from_slot"])
        self.assertEqual(bytes(transport.slots[79])[0:2], (22).to_bytes(2, "little"))

        # Explicit allow_factory=True permits overwriting factory slot when unlocked.
        transport.flash_writes.clear()
        saved_factory = svc.save_flash_slot(5, allow_factory=True)
        self.assertTrue(saved_factory["verified"])
        self.assertEqual(bytes(transport.slots[5])[0:2], (22).to_bytes(2, "little"))

    def test_batch_restore_respects_factory_lock_and_audition(self) -> None:
        svc = self._make_service()
        svc.connect(auto_backup=False, start_polling=False)
        self.addCleanup(svc.disconnect)
        transport = self.transports[-1]

        export_meta = svc.export_backup()
        export_path = Path(export_meta["path"])
        self.assertTrue(export_path.exists())
        backup_data = json.loads(export_path.read_text(encoding="utf-8"))

        # Modify slot 78 & 79 in backup_data.
        img78 = PresetImage.from_bytes(bytes.fromhex(backup_data["presets_hex"][78]))
        img78.volume = 37
        img79 = PresetImage.from_bytes(bytes.fromhex(backup_data["presets_hex"][79]))
        img79.volume = 63
        backup_data["presets_hex"][78] = img78.to_bytes().hex()
        backup_data["presets_hex"][79] = img79.to_bytes().hex()

        # Audition updates live RAM cleanly without touching flash slot.
        original_slot78 = bytes(transport.slots[78])
        auditioned = svc.audition_backup_preset(backup_data, 78)
        self.assertEqual(auditioned["ram"]["volume"], 37)
        self.assertEqual(bytes(transport.slots[78]), original_slot78)
        self.assertEqual(auditioned["undo_depth"], 1)

        # Factory lock & strict bool check on batch_restore_backup.
        with self.assertRaises(FactorySlotLockedError):
            svc.batch_restore_backup(backup_data, [5, 79], allow_factory=False)
        self.assertEqual(len(transport.flash_writes), 0)

        with self.assertRaises(ProtocolError):
            svc.batch_restore_backup(backup_data, [79], allow_factory="yes")  # type: ignore[arg-type]

        # Valid user-slot batch restore writes and verifies both slots.
        restored = svc.batch_restore_backup(backup_data, [78, 79], allow_factory=False)
        self.assertTrue(restored["verified"])
        self.assertEqual(restored["restored_slots"], [78, 79])
        self.assertEqual(bytes(transport.slots[78]), img78.to_bytes())
        self.assertEqual(bytes(transport.slots[79]), img79.to_bytes())

        # Batch restore stops immediately on first read-back mismatch and restores failed slot once.
        transport.flash_writes.clear()
        img77 = PresetImage.from_bytes(bytes.fromhex(backup_data["presets_hex"][77]))
        img77.volume = 12
        backup_data["presets_hex"][77] = img77.to_bytes().hex()
        img78_next = PresetImage.from_bytes(bytes.fromhex(backup_data["presets_hex"][78]))
        img78_next.volume = 44
        backup_data["presets_hex"][78] = img78_next.to_bytes().hex()
        original_slot77 = bytes(transport.slots[77])
        transport.corrupt_next_flash_write = True
        with self.assertRaises(MidiTransportError):
            svc.batch_restore_backup(backup_data, [77, 78], allow_factory=False)
        self.assertEqual(len(transport.flash_writes), 2)
        self.assertEqual(bytes(transport.slots[77]), original_slot77)
        self.assertEqual(bytes(transport.slots[78]), img78.to_bytes())

    def test_demo_mode_sandbox_and_safety_guards(self) -> None:
        svc = self._make_service()

        # Disconnected validation vs transport guard.
        with self.assertRaises(ProtocolError):
            svc.change_routing([0, 0, 1, 2, 3, 4])
        with self.assertRaises(MidiTransportError):
            svc.change_knob(0, 50)

        demo_state = svc.enter_demo_mode()
        self.assertFalse(demo_state["connected"])
        self.assertTrue(demo_state["demo"])
        self.assertEqual(demo_state["identity"], "ME-01_016")
        self.assertEqual(demo_state["amps"][0], "UWE-Twins")
        self.assertEqual(demo_state["cabs"][16], "412 Mesa Stan")
        self.assertFalse(svc.poll_once())

        # Demo edits work in memory without MIDI hardware.
        svc.change_knob(0, 11)
        svc.toggle_block(2, True)
        svc.change_model(1, 3)
        svc.change_routing([1, 0, 2, 3, 4, 5])
        self.assertEqual(svc.get_state()["undo_depth"], 4)
        svc.undo()
        self.assertEqual(svc.get_state()["ram"]["order"], [0, 1, 5, 2, 3, 4])

        # Factory lock still enforced in demo mode.
        with self.assertRaises(FactorySlotLockedError):
            svc.save_flash_slot(0, allow_factory=False)
        with self.assertRaises(ProtocolError):
            svc.save_flash_slot(79, allow_factory=0)  # type: ignore[arg-type]

        demo_saved = svc.save_flash_slot(79)
        self.assertTrue(demo_saved["verified"])
        self.assertTrue(Path(demo_saved["backup_path"]).exists())

        # Bounded undo stack retains at most 30 snapshots.
        for val in range(35):
            svc.change_knob(0, val + 1)
        self.assertEqual(svc.get_state()["undo_depth"], 30)

    def test_background_polling_thread_lifecycle(self) -> None:
        svc = self._make_service(poll_interval_s=0.03, suppress_window_s=0.02)
        svc.connect(auto_backup=False, start_polling=True)
        self.addCleanup(svc.disconnect)
        transport = self.transports[-1]

        time.sleep(0.05)
        transport.ram[0:2] = (55).to_bytes(2, "little")

        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            if svc.get_state()["ram"]["volume"] == 55:
                break
            time.sleep(0.02)

        self.assertEqual(svc.get_state()["ram"]["volume"], 55)
        svc.disconnect()
        self.assertFalse(svc.get_state()["connected"])
        self.assertGreaterEqual(transport.closed_count, 1)

    def test_rename_slot_and_audition(self) -> None:
        svc = self._make_service()
        svc.enter_demo_mode()
        self.addCleanup(svc.disconnect)

        # 1. Demo mode rename AMP slot 0
        res_amp = svc.rename_slot("amp", 0, "TS9 Clean")
        self.assertTrue(res_amp["ok"])
        self.assertEqual(res_amp["name"], "TS9 Clean")
        self.assertEqual(svc.get_state()["amps"][0], "TS9 Clean")

        # Demo mode normalizes non-ASCII and truncates to 13 chars exactly like hardware
        res_long = svc.rename_slot("amp", 1, "VeryLongNameExceeding13Chars")
        self.assertEqual(res_long["name"], "VeryLongNameE")
        self.assertEqual(svc.get_state()["amps"][1], "VeryLongNameE")

        # 2. Demo mode rename CAB slot 3
        res_cab = svc.rename_slot("cab", 3, "Mesa 4x12 V30")
        self.assertTrue(res_cab["ok"])
        self.assertEqual(svc.get_state()["cabs"][3], "Mesa 4x12 V30")

        # 3. Audition AMP slot 4
        res_aud_amp = svc.audition_slot("amp", 4)
        self.assertTrue(res_aud_amp["ok"])
        st = svc.get_state()
        amp_block = next(b for b in st["ram"]["blocks"] if b["block_id"] == 1)
        self.assertEqual(amp_block["model_id"], 4)
        self.assertTrue(amp_block["enabled"])

        # 4. Audition CAB slot 2
        res_aud_cab = svc.audition_slot("cab", 2)
        self.assertTrue(res_aud_cab["ok"])
        st = svc.get_state()
        cab_block = next(b for b in st["ram"]["blocks"] if b["block_id"] == 5)
        self.assertEqual(cab_block["model_id"], 2)
        self.assertTrue(cab_block["enabled"])

        # 5. Connected mode rename writes to transport and re-reads
        svc.disconnect()
        svc.connect(auto_backup=False, start_polling=False)
        transport = self.transports[-1]

        res_conn = svc.rename_slot("amp", 2, "JCM800 Mod")
        self.assertTrue(res_conn["ok"])
        self.assertEqual(svc.get_state()["amps"][2], "JCM800 Mod")
        self.assertIn(b"JCM800 Mod", bytes(transport.amps_table))

        # 6. Error handling
        with self.assertRaises(ProtocolError):
            svc.rename_slot("invalid_cat", 0, "Name")
        with self.assertRaises(ProtocolError):
            svc.rename_slot("amp", 25, "Name")
        with self.assertRaises(ProtocolError):
            svc.audition_slot("dly", 0)

    def test_get_capture_library(self) -> None:
        svc = self._make_service()
        lib = svc.get_curated_library()
        self.assertIn("categories", lib)
        cats = {c["id"]: c for c in lib["categories"]}
        self.assertIn("overdrives", cats)
        self.assertIn("clean", cats)
        self.assertIn("crunch", cats)
        self.assertIn("highgain", cats)
        self.assertIn("bass", cats)
        self.assertIn("cabinets", cats)

        # Check that overdrive models exist
        od_names = [m["name"] for m in cats["overdrives"]["models"]]
        self.assertTrue(any("TS" in name or "Screamer" in name for name in od_names))
        self.assertTrue(any("RAT" in name for name in od_names))


if __name__ == "__main__":
    unittest.main()

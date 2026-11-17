import json
import unittest
from pathlib import Path

from me01_rig.protocol import (
    BLOCK_IDS,
    BLOCK_NAMES,
    BLOCKS,
    FactorySlotLockedError,
    PresetImage,
    ProtocolError,
    bpm_to_delay_raw,
    build_change_knob,
    build_change_model,
    build_change_routing,
    build_frame,
    build_identity_query,
    build_load_preset,
    build_read_request,
    build_save_flash,
    build_toggle_block,
    decode7,
    decode_name_table,
    encode7,
    format_knob_display,
    is_ack_frame,
    parse_frame,
    unwrap_sysex,
    wrap_sysex,
    encode_name_record,
    build_rename_slot,
    parse_capture_header,
    parse_wav_header,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "me01_captured_vectors.json"


class ProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixtures = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    def test_encode7_decode7_and_captured_vectors(self) -> None:
        self.assertEqual(
            wrap_sysex(build_identity_query()),
            bytes.fromhex("f0003245000000407ff7"),
        )

        # Round-trip encode7/decode7 across boundary lengths and trailing flush bytes.
        for length in range(0, 32):
            raw = bytes((i * 37 + 11) & 0xFF for i in range(length))
            packed = encode7(raw)
            self.assertTrue(all(b <= 0x7F for b in packed))
            self.assertEqual(decode7(packed), raw)
            # When hardware appends a zero flush byte to a 7-byte aligned payload, decode7 ignores it.
            if length > 0 and length % 7 == 0:
                self.assertEqual(decode7(packed + b"\x00"), raw)

        vectors = self.fixtures["captured_vectors"]

        ident_frame = parse_frame(unwrap_sysex(bytes.fromhex(vectors["ident_raw"])))
        self.assertEqual(ident_frame.cmd, 0x11)
        self.assertEqual(
            ident_frame.body.split(b"\x00", 1)[0].decode("ascii"),
            self.fixtures["identity"],
        )

        sync_frame = parse_frame(unwrap_sysex(bytes.fromhex(vectors["sync_raw"])))
        self.assertEqual(sync_frame.cmd, 0x23)
        self.assertEqual(sync_frame.space, 0x04)
        self.assertEqual(sync_frame.address, 0x20000000)
        self.assertEqual(sync_frame.size, 4)
        self.assertEqual(sync_frame.data[0], self.fixtures["active_preset"])

        ram_frame = parse_frame(unwrap_sysex(bytes.fromhex(vectors["ram_raw"])))
        self.assertEqual(ram_frame.cmd, 0x23)
        self.assertEqual(ram_frame.space, 0x04)
        self.assertEqual(ram_frame.address, 0x10000000)
        self.assertEqual(ram_frame.size, 92)
        self.assertEqual(ram_frame.data.hex(), self.fixtures["ram_hex"])

        amps_frame = parse_frame(unwrap_sysex(bytes.fromhex(vectors["amps_raw"])))
        self.assertEqual(amps_frame.cmd, 0x23)
        self.assertEqual(amps_frame.space, 0x05)
        self.assertEqual(amps_frame.address, 0x90000000)
        self.assertEqual(amps_frame.size, 280)
        amps = decode_name_table(amps_frame.data)
        self.assertEqual(len(amps), 20)
        self.assertEqual(amps[0], "UWE-Twins")
        self.assertEqual(amps[13], "Juice JIM r")
        self.assertEqual(amps[14], "4OD-MarVicto")
        self.assertEqual(amps[19], "Friedman Pink")

        cabs_frame = parse_frame(unwrap_sysex(bytes.fromhex(vectors["cabs_raw"])))
        self.assertEqual(cabs_frame.cmd, 0x23)
        self.assertEqual(cabs_frame.space, 0x05)
        self.assertEqual(cabs_frame.address, 0x80000000)
        self.assertEqual(cabs_frame.size, 280)
        cabs = decode_name_table(cabs_frame.data)
        self.assertEqual(len(cabs), 20)
        self.assertEqual(cabs[0], "AC-SeVin")
        self.assertEqual(cabs[11], "MESA_412")
        self.assertEqual(cabs[6], "04E_Vox 5 AC3")
        self.assertEqual(cabs[16], "412 Mesa Stan")
        self.assertEqual(cabs[19], "4x12_ MESA_Bo")

        with self.assertRaises(ProtocolError):
            decode_name_table(b"\x00" * 279)

        # Read request framing sanity
        req = parse_frame(build_read_request(0x04, 0x10000000, 92))
        self.assertEqual((req.cmd, req.space, req.address, req.size), (0x23, 0x04, 0x10000000, 92))
        with self.assertRaises(ProtocolError):
            build_read_request(0x04, 80 * 92, 92)

    def test_malformed_sysex_rejected(self) -> None:
        valid_syx = bytearray.fromhex(self.fixtures["captured_vectors"]["sync_raw"])
        valid_raw = bytearray(unwrap_sysex(bytes(valid_syx)))

        malformed_sysex_cases = [
            b"",
            b"\xf0\xf7",
            bytes(valid_syx[:-1]),          # missing F7
            bytes(valid_syx[1:]),           # missing F0
            bytes(valid_syx[:8]),           # truncated
            bytes([0xF0, 0x80, 0xF7]),      # non-7-bit byte in payload
            bytes.fromhex("f07e7f0601f7"),  # foreign Universal Non-Realtime SysEx
        ]
        for packet in malformed_sysex_cases:
            with self.subTest(packet=packet.hex()):
                with self.assertRaises(ProtocolError):
                    frame = unwrap_sysex(packet)
                    parse_frame(frame)

        # Non-00-59 header
        bad_hdr = bytearray(valid_raw)
        bad_hdr[1] = 0x58
        with self.assertRaises(ProtocolError):
            parse_frame(bytes(bad_hdr))

        # Corrupted checksum byte
        bad_cksum = bytearray(valid_raw)
        bad_cksum[-1] ^= 0xFF
        with self.assertRaises(ProtocolError):
            parse_frame(bytes(bad_cksum))

        # Truncated frame
        with self.assertRaises(ProtocolError):
            parse_frame(bytes(valid_raw[:-2]))

        # Non-Sinco payload inside valid SysEx wrapper
        with self.assertRaises(ProtocolError):
            parse_frame(unwrap_sysex(wrap_sysex(b"\x7e\x7f\x06\x01\x00\x00\x00")))

        # Short 0x22 / 0x23 body (< 8 bytes)
        for mem_cmd in (0x22, 0x23):
            with self.subTest(mem_cmd=hex(mem_cmd), case="short_body"):
                with self.assertRaises(ProtocolError):
                    parse_frame(build_frame(mem_cmd, b"\x04\x00\x00\x00\x10\x04\x00"))

        # 0x22 write with declared size > 0 and empty payload must fail
        with self.assertRaises(ProtocolError):
            parse_frame(build_frame(0x22, b"\x04\x00\x00\x00\x10\x04\x00\x00"))

        # 0x23 reply with non-empty data whose length != declared size must fail
        with self.assertRaises(ProtocolError):
            parse_frame(build_frame(0x23, b"\x04\x00\x00\x00\x10\x04\x00\x00\x01\x02"))

    def test_preset_image_roundtrip(self) -> None:
        ram_bytes = bytes.fromhex(self.fixtures["ram_hex"])
        p72 = PresetImage.from_bytes(ram_bytes)
        self.assertEqual(p72.volume, 100)
        self.assertEqual(p72.order, [0, 1, 5, 2, 3, 4])
        self.assertEqual(p72.states, [1, 1, 0, 1, 1, 1])
        self.assertEqual(p72.models, [2, 18, 0, 2, 1, 11])
        self.assertEqual(len(p72.to_bytes()), 92)
        self.assertEqual(p72.to_bytes(), ram_bytes)

        p01_bytes = bytes.fromhex(self.fixtures["p01_hex"])
        p01 = PresetImage.from_bytes(p01_bytes)
        self.assertEqual(p01.volume, 90)
        self.assertEqual(p01.to_bytes(), p01_bytes)

        # Round-trip all 80 presets in fixture
        for idx, hex_str in enumerate(self.fixtures["presets_hex"]):
            raw = bytes.fromhex(hex_str)
            img = PresetImage.from_bytes(raw)
            self.assertEqual(img.to_bytes(), raw, f"Slot {idx} mismatch")

        # Mutate fields and round-trip via to_dict / from_dict
        mutated = PresetImage.from_bytes(ram_bytes)
        mutated.volume = 77
        mutated.order = [5, 4, 3, 2, 1, 0]
        mutated.states[2] = 1
        mutated.models[1] = 4
        mutated.knobs[5][2] = 63
        self.assertEqual(len(mutated.to_bytes()), 92)
        self.assertEqual(PresetImage.from_bytes(mutated.to_bytes()), mutated)

        d = mutated.to_dict(amps=self.fixtures["amps"], cabs=self.fixtures["cabs"])
        self.assertEqual(d["volume"], 77)
        self.assertEqual(PresetImage.from_dict(d), mutated)
        blocks_by_id = {b["block_id"]: b for b in d["blocks"]}
        self.assertEqual(blocks_by_id[1]["model_name"], self.fixtures["amps"][4])
        self.assertEqual(blocks_by_id[5]["model_name"], self.fixtures["cabs"][11])

        # Reject invalid preset bytes and dict fields
        with self.assertRaises(ProtocolError):
            PresetImage.from_bytes(ram_bytes[:91])
        bad_order = bytearray(ram_bytes)
        bad_order[2:8] = bytes([0, 0, 1, 2, 3, 4])
        with self.assertRaises(ProtocolError):
            PresetImage.from_bytes(bytes(bad_order))
        bad_vol = bytearray(ram_bytes)
        bad_vol[0:2] = (101).to_bytes(2, "little")
        with self.assertRaises(ProtocolError):
            PresetImage.from_bytes(bytes(bad_vol))
        bad_model = bytearray(ram_bytes)
        bad_model[14] = 99
        with self.assertRaises(ProtocolError):
            PresetImage.from_bytes(bytes(bad_model))

        for key, bad_val in (
            ("volume", 101),
            ("order", [0, 0, 1, 2, 3, 4]),
            ("states", ["bad", 0, 0, 0, 0, 0]),
            ("states", [1, 1, 1, 1, 1]),
            ("models", [0, 0, 0, 0, 0]),
            ("knobs", [[0] * 6] * 5),
            ("knobs", [[0] * 5] * 6),
        ):
            with self.subTest(bad_dict_key=key):
                bad_dict = dict(d)
                bad_dict[key] = bad_val
                with self.assertRaises(ProtocolError):
                    PresetImage.from_dict(bad_dict)

        # Post-mutation invalid fields must still be rejected on serialization
        mutated.order = [0, 0, 1, 2, 3, 4]
        with self.assertRaises(ProtocolError):
            mutated.to_bytes()
        with self.assertRaises(ProtocolError):
            mutated.to_dict()

    def test_write_allowlist_and_validation(self) -> None:
        routing_frame = build_change_routing([0, 1, 5, 2, 3, 4])
        self.assertEqual(routing_frame[-1], 0xD4)
        parsed_routing = parse_frame(routing_frame)
        self.assertEqual(parsed_routing.cmd, 0x22)
        self.assertEqual(parsed_routing.address, 0x10000002)
        self.assertEqual(parsed_routing.data, bytes([0, 1, 5, 2, 3, 4]))

        with self.assertRaises(ProtocolError):
            build_change_routing([0, 0, 1, 2, 3, 4])
        with self.assertRaises(ProtocolError):
            build_change_routing([0, 1, 2, 3, 4])

        # Knob allowlist: addr == 0 OR even in 0x14..0x5A
        vol_frame = parse_frame(build_change_knob(0, 88))
        self.assertEqual((vol_frame.address, vol_frame.size, vol_frame.data), (0x10000000, 2, b"\x58\x00"))
        knob_frame = parse_frame(build_change_knob(0x54, 42))
        self.assertEqual((knob_frame.address, knob_frame.size, knob_frame.data), (0x10000054, 2, b"\x2a\x00"))

        for bad_addr in (0x01, 0x02, 0x12, 0x15, 0x5B, 0x5C, -2):
            with self.subTest(bad_addr=hex(bad_addr)):
                with self.assertRaises(ProtocolError):
                    build_change_knob(bad_addr, 50)

        for bad_val in (-1, 101, 150):
            with self.subTest(bad_val=bad_val):
                with self.assertRaises(ProtocolError):
                    build_change_knob(0x14, bad_val)

        # Toggle, model, load preset validation
        self.assertEqual(parse_frame(build_toggle_block(2, True)).address, 0x1000000A)
        with self.assertRaises(ProtocolError):
            build_toggle_block(6, True)

        self.assertEqual(parse_frame(build_change_model(0, 3)).data, b"\x03")
        with self.assertRaises(ProtocolError):
            build_change_model(0, 4)

        self.assertEqual(parse_frame(build_load_preset(71)).address, 0xE0000047)
        with self.assertRaises(ProtocolError):
            build_load_preset(80)

        # Save flash factory lock & bounds
        raw92 = bytes.fromhex(self.fixtures["ram_hex"])
        with self.assertRaises(FactorySlotLockedError):
            build_save_flash(0, raw92)
        with self.assertRaises(ProtocolError):
            build_save_flash(39, raw92)

        factory_unlocked = parse_frame(build_save_flash(0, raw92, allow_factory=True))
        self.assertEqual((factory_unlocked.cmd, factory_unlocked.address, factory_unlocked.size), (0x22, 0, 92))

        user_save = parse_frame(build_save_flash(79, raw92))
        self.assertEqual((user_save.cmd, user_save.address, user_save.size), (0x22, 79 * 92, 92))

        with self.assertRaises(ProtocolError):
            build_save_flash(80, raw92)
        with self.assertRaises(ProtocolError):
            build_save_flash(-1, raw92)
        with self.assertRaises(ProtocolError):
            build_save_flash(40, raw92[:91])
        for bad_allow in ("false", 1, 0, ["no"], None):
            with self.subTest(bad_allow=bad_allow):
                with self.assertRaises(ProtocolError):
                    build_save_flash(0, raw92, allow_factory=bad_allow)  # type: ignore[arg-type]
                with self.assertRaises(ProtocolError):
                    build_save_flash(40, raw92, allow_factory=bad_allow)  # type: ignore[arg-type]

        # ACK frame validation
        self.assertTrue(is_ack_frame(bytes.fromhex("00590001000000ff")))
        self.assertFalse(is_ack_frame(bytes.fromhex("0059000100000000")))
        self.assertFalse(is_ack_frame(build_frame(0x23, b"\x00")))

    def test_knob_scales_and_rev_models(self) -> None:
        self.assertEqual(BLOCK_IDS, (0, 1, 2, 3, 4, 5))
        self.assertEqual(BLOCK_NAMES, ("FX", "AMP", "MOD", "DLY", "REV", "CAB"))
        self.assertEqual(set(BLOCKS[0].models.keys()), {0, 1, 2, 3})
        self.assertEqual(BLOCKS[0].models[3].min_fw, 17)
        self.assertEqual(set(BLOCKS[1].models.keys()), set(range(20)))
        self.assertEqual(set(BLOCKS[2].models.keys()), set(range(7)))
        self.assertEqual(set(BLOCKS[3].models.keys()), set(range(5)))
        self.assertEqual(set(BLOCKS[4].models.keys()), set(range(6)))
        self.assertEqual(set(BLOCKS[5].models.keys()), set(range(20)))

        # CAB Low Cut & High Cut
        self.assertEqual(format_knob_display(5, 0, 1, 0), "20 Hz")
        self.assertEqual(format_knob_display(5, 0, 1, 24), "87 Hz")
        self.assertEqual(format_knob_display(5, 0, 1, 100), "300 Hz")
        self.assertEqual(format_knob_display(5, 0, 2, 0), "5.0 kHz")
        self.assertEqual(format_knob_display(5, 0, 2, 100), "18.0 kHz")

        # DLY Dual (50..500 ms) vs Dtape (100..1000 ms)
        self.assertEqual(format_knob_display(3, 3, 0, 0), "50 ms")
        self.assertEqual(format_knob_display(3, 3, 0, 100), "500 ms")
        self.assertEqual(format_knob_display(3, 2, 0, 0), "100 ms")
        self.assertEqual(format_knob_display(3, 2, 0, 100), "1000 ms")

        # BPM -> Delay raw
        self.assertEqual(bpm_to_delay_raw(120.0, 3), 100)
        self.assertEqual(bpm_to_delay_raw(240.0, 3), 44)
        self.assertEqual(bpm_to_delay_raw(60.0, 2), 100)
        self.assertEqual(bpm_to_delay_raw(120.0, 2), 44)
        self.assertEqual(bpm_to_delay_raw(30.0, 2), 100)  # clamped
        self.assertEqual(bpm_to_delay_raw(1500.0, 3), 0)  # clamped
        with self.assertRaises(ProtocolError):
            bpm_to_delay_raw(0, 2)
        with self.assertRaises(ProtocolError):
            bpm_to_delay_raw(120, 9)

        # REV models 0..5 all have 5 active knobs and Ghost slot 5
        for rev_model_id in range(6):
            model = BLOCKS[4].models[rev_model_id]
            self.assertEqual(len(model.knobs), 5)
            self.assertEqual(len(model.slots), 6)
            self.assertIsNone(model.slots[5])
        self.assertEqual(BLOCKS[4].models[0].slots[4], "Depth")
        self.assertEqual(BLOCKS[4].models[1].slots[4], "Depth")
        self.assertEqual(BLOCKS[4].models[2].slots[4], "Rise-T")
        self.assertEqual(BLOCKS[4].models[3].slots[4], "Combs")
        self.assertEqual(BLOCKS[4].models[4].slots[4], "Amount")
        self.assertEqual(BLOCKS[4].models[5].slots[4], "Diffusion")

    def test_encode_name_record_and_build_rename_slot(self) -> None:
        # Standard record encoding
        rec = encode_name_record("Clean TS9")
        self.assertEqual(len(rec), 14)
        self.assertEqual(rec, b"Clean TS9\x00\x00\x00\x00\x00")

        # Truncation: 13 chars max so 14th is always NUL terminator
        long_rec = encode_name_record("SuperLongCaptureName")
        self.assertEqual(len(long_rec), 14)
        self.assertEqual(long_rec, b"SuperLongCapt\x00")

        # Non-ascii handling
        unicode_rec = encode_name_record("MötleyCrüe")
        self.assertEqual(len(unicode_rec), 14)
        self.assertTrue(unicode_rec.endswith(b"\x00"))

        # Build rename AMP slot
        frame_amp = build_rename_slot("amp", 0, "TS9 Clean")
        parsed_amp = parse_frame(frame_amp)
        self.assertEqual(parsed_amp.cmd, 0x22)
        # body: space (1 byte: 0x05) + addr (4 bytes: 0x90000000) + size (3 bytes: 14) + data (14 bytes)
        self.assertEqual(parsed_amp.body[0], 0x05)
        self.assertEqual(int.from_bytes(parsed_amp.body[1:5], "little"), 0x90000000)
        self.assertEqual(int.from_bytes(parsed_amp.body[5:8], "little"), 14)
        self.assertEqual(parsed_amp.body[8:], b"TS9 Clean\x00\x00\x00\x00\x00")

        # Build rename CAB slot 19
        frame_cab = build_rename_slot("cab", 19, "V30 Mesa 4x12")
        parsed_cab = parse_frame(frame_cab)
        self.assertEqual(parsed_cab.cmd, 0x22)
        self.assertEqual(parsed_cab.body[0], 0x05)
        self.assertEqual(int.from_bytes(parsed_cab.body[1:5], "little"), 0x80000000 + 19 * 14)
        self.assertEqual(int.from_bytes(parsed_cab.body[5:8], "little"), 14)
        self.assertEqual(parsed_cab.body[8:], b"V30 Mesa 4x12\x00")

        # Boundary and invalid arguments
        with self.assertRaises(ProtocolError):
            build_rename_slot("mod", 0, "InvalidCategory")
        with self.assertRaises(ProtocolError):
            build_rename_slot("amp", -1, "InvalidSlot")
        with self.assertRaises(ProtocolError):
            build_rename_slot("cab", 20, "InvalidSlot")

    def test_capture_and_wav_header_parsers(self) -> None:
        import struct

        # Valid AM4 capture
        raw_am4 = b"AM4\x003VAVE_TS\x00\x00\x00\x00\x00" + b"\x00" * 200
        meta_am4 = parse_capture_header(raw_am4)
        self.assertEqual(meta_am4["magic"], "AM4")
        self.assertEqual(meta_am4["name"], "3VAVE_TS")
        self.assertEqual(meta_am4["kind"], "amp")
        self.assertTrue(meta_am4["valid"])

        # Valid CAB model
        raw_cab = b"CAB\x001AC-SeVin\x00\x00\x00\x00\x00" + b"\x00" * 200
        meta_cab = parse_capture_header(raw_cab)
        self.assertEqual(meta_cab["magic"], "CAB")
        self.assertEqual(meta_cab["name"], "1AC-SeVin")
        self.assertEqual(meta_cab["kind"], "cab")
        self.assertTrue(meta_cab["valid"])

        # Rejects corrupt capture
        with self.assertRaises(ProtocolError):
            parse_capture_header(b"XYZ\x00TooShort")

        # Synthetic 48kHz 24-bit mono WAV IR
        sample_rate = 48000
        channels = 1
        bits = 24
        num_samples = 1024
        byte_rate = sample_rate * channels * (bits // 8)
        block_align = channels * (bits // 8)
        data_size = num_samples * block_align
        chunk_size = 36 + data_size
        wav_bytes = struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF", chunk_size, b"WAVE",
            b"fmt ", 16, 1, channels, sample_rate, byte_rate, block_align, bits,
            b"data", data_size,
        ) + b"\x00" * data_size

        meta_wav = parse_wav_header(wav_bytes)
        self.assertEqual(meta_wav["sample_rate"], 48000)
        self.assertEqual(meta_wav["channels"], 1)
        self.assertEqual(meta_wav["bits_per_sample"], 24)
        self.assertEqual(meta_wav["samples"], 1024)
        self.assertTrue(meta_wav["valid"])

        # Rejects non-WAV
        with self.assertRaises(ProtocolError):
            parse_wav_header(b"NOT_A_WAV_FILE")

        # Rejects truncated WAV (struct.error converted to ProtocolError)
        truncated_wav = (
            b"RIFF\x30\x00\x00\x00WAVE"
            + b"JUNK\x10\x00\x00\x00"
            + (b"\x00" * 16)
            + b"fmt \x10\x00\x00\x00\x01\x00"
        )
        with self.assertRaises(ProtocolError) as ctx:
            parse_wav_header(truncated_wav)
        self.assertIn("truncated", str(ctx.exception).lower())

        # Handles odd-length chunk with 2-byte word padding
        odd_chunk_wav = (
            b"RIFF\x48\x00\x00\x00WAVE"
            b"JUNK\x03\x00\x00\x00abc\x00"  # 3 bytes + 1 padding byte
            b"fmt \x10\x00\x00\x00"
            + struct.pack("<HHIIHH", 1, channels, sample_rate, byte_rate, block_align, bits)
            + b"data\x08\x00\x00\x00" + b"\x00" * 8
        )
        meta_odd = parse_wav_header(odd_chunk_wav)
        self.assertEqual(meta_odd["sample_rate"], 48000)
        self.assertTrue(meta_odd["valid"])


if __name__ == "__main__":
    unittest.main()

"""Sinco Base-128 USB-MIDI SysEx codec, 92-byte preset schema, and write allowlist."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Sequence

SINCO_MAGIC = b"\x00\x59"
CMD_ACK = 0x00
CMD_IDENTITY = 0x11
CMD_WRITE = 0x22
CMD_READ = 0x23

SPACE_PRESET = 0x04
SPACE_NAMES = 0x05

ADDR_RAM_BASE = 0x10000000
ADDR_RAM_ROUTING = 0x10000002
ADDR_ACTIVE_PRESET = 0x20000000
ADDR_LOAD_PRESET_BASE = 0xE0000000
ADDR_CAB_NAMES = 0x80000000
ADDR_AMP_NAMES = 0x90000000

PRESET_SIZE = 92
FACTORY_SLOT_COUNT = 40
TOTAL_PRESET_SLOTS = 80
NAME_RECORD_COUNT = 20
NAME_RECORD_LEN = 14
NAME_TABLE_SIZE = NAME_RECORD_COUNT * NAME_RECORD_LEN

ACK_FRAME = b"\x00\x59\x00\x01\x00\x00\x00\xff"

BLOCK_IDS: tuple[int, ...] = (0, 1, 2, 3, 4, 5)
BLOCK_NAMES: tuple[str, ...] = ("FX", "AMP", "MOD", "DLY", "REV", "CAB")


class ProtocolError(ValueError):
    """Raised when SysEx framing, preset bytes, or command arguments fail validation."""


class FactorySlotLockedError(ProtocolError):
    """Raised when attempting to write to a factory slot (0..39) while locked."""


@dataclass(frozen=True)
class ModelSpec:
    """Definition of a single effect/amp/cab model within a block."""

    model_id: int
    name: str
    knobs: tuple[str, ...]
    min_fw: int | None = None

    @property
    def slots(self) -> tuple[str | None, ...]:
        """Return a 6-slot tuple padded with None for unused ghost slots."""
        return self.knobs + (None,) * (6 - len(self.knobs))


@dataclass(frozen=True)
class BlockSpec:
    """Definition of one of the 6 ME-01 signal chain blocks."""

    block_id: int
    name: str
    base_addr: int
    models: dict[int, ModelSpec]


def _make_indexed_models(prefix: str, count: int, knobs: tuple[str, ...]) -> dict[int, ModelSpec]:
    return {i: ModelSpec(i, f"{prefix} {i + 1}", knobs) for i in range(count)}


def _make_models(defs: Sequence[tuple[int, str, tuple[str, ...], int | None]]) -> dict[int, ModelSpec]:
    return {
        model_id: ModelSpec(model_id, name, knobs, min_fw=min_fw)
        for model_id, name, knobs, min_fw in defs
    }


BLOCKS: dict[int, BlockSpec] = {
    0: BlockSpec(
        block_id=0,
        name="FX",
        base_addr=0x14,
        models=_make_models(
            [
                (0, "Noise Gate++", ("Gate",), None),
                (1, "Boost", ("Gate", "Gain"), None),
                (2, "Compress", ("Gate", "Sustain", "Attack", "Level"), None),
                (3, "AI Gate MS", ("Gate", "Bias"), 17),
            ]
        ),
    ),
    1: BlockSpec(
        block_id=1,
        name="AMP",
        base_addr=0x20,
        models=_make_indexed_models("AMP", 20, ("Gain", "Level", "Bass", "Mid", "Treble")),
    ),
    2: BlockSpec(
        block_id=2,
        name="MOD",
        base_addr=0x2C,
        models=_make_models(
            [
                (0, "Chorus", ("Speed", "Depth", "Mix"), None),
                (1, "Phaser", ("Speed", "Midcut", "Reso", "Feedback"), None),
                (2, "Tremolo", ("Speed", "Depth", "Level"), None),
                (3, "Flanger", ("Speed", "Depth", "Feedback", "Mix"), None),
                (4, "Vibrato", ("Speed", "Depth"), None),
                (5, "Univibe", ("Speed", "Depth", "Mix"), None),
                (6, "Autofilter", ("Speed", "Min", "Max", "Mix", "Feedback"), None),
            ]
        ),
    ),
    3: BlockSpec(
        block_id=3,
        name="DLY",
        base_addr=0x38,
        models=_make_models(
            [
                (0, "Analog", ("Time", "Feedback", "Mix", "Phaser", "Pitch"), None),
                (1, "Duck", ("Time", "Feedback", "Mix", "Unpack", "Speed", "Depth"), None),
                (2, "Dtape", ("Time", "Feedback", "Mix", "Grit", "Speed", "Depth"), None),
                (3, "Dual", ("Time", "Feedback", "Mix", "T-Mode", "Speed", "Depth"), None),
                (4, "Lofi", ("Time", "Feedback", "Mix", "Grit", "Speed", "Depth"), None),
            ]
        ),
    ),
    4: BlockSpec(
        block_id=4,
        name="REV",
        base_addr=0x44,
        models=_make_models(
            [
                (0, "Room", ("Decay", "Mix", "High Pass", "Low Pass", "Depth"), None),
                (1, "Hall", ("Decay", "Mix", "High Pass", "Low Pass", "Depth"), None),
                (2, "Swell", ("Decay", "Mix", "High Pass", "Low Pass", "Rise-T"), None),
                (3, "Spring", ("Decay", "Mix", "High Pass", "Low Pass", "Combs"), None),
                (4, "Shimmer", ("Decay", "Mix", "Tone", "Pitch", "Amount"), None),
                (5, "Cloud", ("Decay", "Mix", "High Pass", "Low Pass", "Diffusion"), None),
            ]
        ),
    ),
    5: BlockSpec(
        block_id=5,
        name="CAB",
        base_addr=0x50,
        models=_make_indexed_models("CAB", 20, ("Level", "Low Cut", "High Cut")),
    ),
}


@dataclass(frozen=True)
class ParsedFrame:
    """Decoded Sinco protocol frame."""

    cmd: int
    body: bytes
    space: int | None = None
    address: int | None = None
    size: int | None = None
    data: bytes = b""


def _require_int(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ProtocolError(f"{name} must be an int, got {type(value).__name__}")
    return value


def _require_range(value: Any, low: int, high: int, name: str) -> int:
    iv = _require_int(value, name)
    if not (low <= iv <= high):
        raise ProtocolError(f"{name} out of range [{low}, {high}]: {iv}")
    return iv


def _require_sequence(value: Any, length: int, name: str) -> Sequence[Any]:
    if isinstance(value, (bytes, bytearray, str)) or not isinstance(value, Sequence):
        raise ProtocolError(f"{name} must be a sequence")
    if len(value) != length:
        raise ProtocolError(f"{name} must have length {length}, got {len(value)}")
    return value


def encode7(raw: bytes) -> bytes:
    """Encode 8-bit bytes into LSB-first 7-bit MIDI SysEx payload bytes."""
    raw_bytes = bytes(raw)
    out = bytearray()
    acc = 0
    bits = 0
    for byte in raw_bytes:
        acc |= byte << bits
        bits += 8
        while bits >= 7:
            out.append(acc & 0x7F)
            acc >>= 7
            bits -= 7
    if bits > 0:
        out.append(acc & 0x7F)
    return bytes(out)


def decode7(packed: bytes) -> bytes:
    """Decode LSB-first 7-bit SysEx payload bytes back into 8-bit bytes."""
    packed_bytes = bytes(packed)
    out = bytearray()
    acc = 0
    bits = 0
    for byte in packed_bytes:
        if byte > 0x7F:
            raise ProtocolError(f"Non-7-bit byte in SysEx payload: 0x{byte:02x}")
        acc |= byte << bits
        bits += 7
        while bits >= 8:
            out.append(acc & 0xFF)
            acc >>= 8
            bits -= 8
    return bytes(out)


def wrap_sysex(raw_frame: bytes) -> bytes:
    """Wrap a raw Sinco frame in F0 ... F7 with Base-128 encoding."""
    return b"\xF0" + encode7(raw_frame) + b"\xF7"


def unwrap_sysex(sysex_bytes: bytes) -> bytes:
    """Validate F0 ... F7 framing and Base-128 decode the inner Sinco frame."""
    data = bytes(sysex_bytes)
    if len(data) < 3 or data[0] != 0xF0 or data[-1] != 0xF7:
        raise ProtocolError("Malformed SysEx envelope: expected F0 <payload> F7")
    return decode7(data[1:-1])


def build_frame(cmd: int, body: bytes = b"") -> bytes:
    """Build a Sinco frame: 00 59 <cmd> <len24 LE> <body> <~sum(body) & 0xFF>."""
    cmd_val = _require_range(cmd, 0, 0xFF, "cmd")
    body_bytes = bytes(body)
    length = len(body_bytes)
    if length > 0xFFFFFF:
        raise ProtocolError(f"Frame body too large: {length}")
    checksum = (~sum(body_bytes)) & 0xFF
    return (
        SINCO_MAGIC
        + bytes([cmd_val])
        + length.to_bytes(3, "little")
        + body_bytes
        + bytes([checksum])
    )


def parse_frame(frame: bytes) -> ParsedFrame:
    """Validate and parse a decoded Sinco frame."""
    data = bytes(frame)
    if len(data) < 7:
        raise ProtocolError(f"Frame too short ({len(data)} bytes)")
    if data[:2] != SINCO_MAGIC:
        raise ProtocolError(f"Invalid Sinco header: {data[:2].hex()}")

    cmd = data[2]
    body_len = int.from_bytes(data[3:6], "little")
    expected_len = 6 + body_len + 1
    if len(data) != expected_len:
        raise ProtocolError(
            f"Frame length mismatch: expected {expected_len} bytes, got {len(data)}"
        )

    body = data[6 : 6 + body_len]
    expected_cksum = (~sum(body)) & 0xFF
    actual_cksum = data[-1]
    if actual_cksum != expected_cksum:
        raise ProtocolError(
            f"Checksum mismatch: expected 0x{expected_cksum:02x}, got 0x{actual_cksum:02x}"
        )

    if cmd in (CMD_WRITE, CMD_READ):
        if len(body) < 8:
            raise ProtocolError(f"Memory command 0x{cmd:02x} body too short: {len(body)}")
        space = body[0]
        address = int.from_bytes(body[1:5], "little")
        size = int.from_bytes(body[5:8], "little")
        mem_data = body[8:]
        if cmd == CMD_WRITE:
            if len(mem_data) != size:
                raise ProtocolError(
                    f"Write payload length mismatch: declared size {size}, got {len(mem_data)}"
                )
        elif len(mem_data) not in (0, size):
            raise ProtocolError(
                f"Read payload length mismatch: declared size {size}, got {len(mem_data)}"
            )
        return ParsedFrame(
            cmd=cmd,
            body=body,
            space=space,
            address=address,
            size=size,
            data=mem_data,
        )

    return ParsedFrame(cmd=cmd, body=body)


def is_ack_frame(frame: bytes) -> bool:
    """Return True iff frame matches the 8-byte ME-01 write ACK."""
    return bytes(frame) == ACK_FRAME


def build_identity_query() -> bytes:
    """Build the 0x11 device identity query frame."""
    return build_frame(CMD_IDENTITY, b"")


def build_read_request(space: int, addr: int, size: int) -> bytes:
    """Build a validated 0x23 memory read request frame."""
    space_val = _require_int(space, "space")
    if space_val not in (SPACE_PRESET, SPACE_NAMES):
        raise ProtocolError(f"Unsupported memory space: 0x{space_val:02x}")
    addr_val = _require_range(addr, 0, 0xFFFFFFFF, "addr")
    size_val = _require_range(size, 1, 0xFFFFFF, "size")
    if space_val == SPACE_PRESET and addr_val < ADDR_RAM_BASE:
        if addr_val + size_val > TOTAL_PRESET_SLOTS * PRESET_SIZE:
            raise ProtocolError(
                f"Flash read out of bounds: addr=0x{addr_val:08x}, size={size_val}"
            )
    body = bytes([space_val]) + addr_val.to_bytes(4, "little") + size_val.to_bytes(3, "little")
    return build_frame(CMD_READ, body)


def _build_write(addr: int, data: bytes) -> bytes:
    body = (
        bytes([SPACE_PRESET])
        + addr.to_bytes(4, "little")
        + len(data).to_bytes(3, "little")
        + data
    )
    return build_frame(CMD_WRITE, body)


def build_load_preset(preset_id: int) -> bytes:
    """Build a 0x22 command to load flash preset slot 0..79 into live RAM."""
    slot = _require_range(preset_id, 0, TOTAL_PRESET_SLOTS - 1, "preset_id")
    return _build_write(ADDR_LOAD_PRESET_BASE + slot, b"\x01")


def build_toggle_block(block_id: int, enabled: bool) -> bytes:
    """Build a 0x22 command to bypass or enable a block (0..5) in live RAM."""
    blk = _require_range(block_id, 0, 5, "block_id")
    if not isinstance(enabled, bool):
        raise ProtocolError(f"enabled must be a bool, got {type(enabled).__name__}")
    return _build_write(ADDR_RAM_BASE + 0x08 + blk, bytes([1 if enabled else 0]))


def build_change_model(block_id: int, model_id: int) -> bytes:
    """Build a 0x22 command to select a model within a block in live RAM."""
    blk = _require_range(block_id, 0, 5, "block_id")
    mdl = _require_int(model_id, "model_id")
    if mdl not in BLOCKS[blk].models:
        raise ProtocolError(f"Invalid model_id {mdl} for block {BLOCKS[blk].name}")
    return _build_write(ADDR_RAM_BASE + 0x0E + blk, bytes([mdl]))


def build_change_knob(addr: int, value: int) -> bytes:
    """Build a 0x22 allowlisted knob/volume write (addr 0 or even 0x14..0x5A)."""
    offset = _require_int(addr, "addr")
    if not (offset == 0 or (0x14 <= offset <= 0x5A and offset % 2 == 0)):
        raise ProtocolError(f"Knob address 0x{offset:02x} is not allowlisted")
    val = _require_range(value, 0, 100, "value")
    return _build_write(ADDR_RAM_BASE + offset, val.to_bytes(2, "little"))


def build_change_routing(order: Sequence[int]) -> bytes:
    """Build a 0x22 command to set the 6-block signal chain permutation."""
    seq = _require_sequence(order, 6, "order")
    normalized = [_require_range(item, 0, 5, "order element") for item in seq]
    if sorted(normalized) != list(BLOCK_IDS):
        raise ProtocolError(f"order must be a permutation of 0..5, got {normalized}")
    return _build_write(ADDR_RAM_ROUTING, bytes(normalized))


def build_save_flash(preset_id: int, raw92: bytes, *, allow_factory: bool = False) -> bytes:
    """Build a 0x22 flash slot write, enforcing the factory slot soft-lock."""
    if not isinstance(allow_factory, bool):
        raise ProtocolError("allow_factory must be a boolean")
    slot = _require_range(preset_id, 0, TOTAL_PRESET_SLOTS - 1, "preset_id")
    if slot < FACTORY_SLOT_COUNT and not allow_factory:
        raise FactorySlotLockedError(
            f"Factory slot P{slot + 1:02d} (index {slot}) is locked; pass allow_factory=True to overwrite"
        )
    if not isinstance(raw92, (bytes, bytearray, memoryview)):
        raise ProtocolError("raw92 must be bytes-like")
    payload = bytes(raw92)
    if len(payload) != PRESET_SIZE:
        raise ProtocolError(f"raw92 must be exactly {PRESET_SIZE} bytes, got {len(payload)}")
    return _build_write(slot * PRESET_SIZE, payload)


def decode_name_table(data280: bytes) -> list[str]:
    """Decode a 280-byte (20 x 14-byte NUL-padded) AMP or CAB name table."""
    data = bytes(data280)
    if len(data) != NAME_TABLE_SIZE:
        raise ProtocolError(
            f"Name table must be {NAME_TABLE_SIZE} bytes, got {len(data)}"
        )
    names: list[str] = []
    for idx in range(NAME_RECORD_COUNT):
        record = data[idx * NAME_RECORD_LEN : (idx + 1) * NAME_RECORD_LEN]
        text = record.split(b"\x00", 1)[0].decode("ascii", errors="replace")
        prefix = str(idx + 1)
        # Strip slot-number prefix only when followed by a non-digit ASCII char
        # so real numeric names like "412 Mesa Stan" or "04E_Vox 5 AC3" stay intact.
        if len(text) > len(prefix) and text.startswith(prefix):
            next_ch = text[len(prefix)]
            if next_ch.isascii() and not next_ch.isdigit():
                text = text[len(prefix) :]
        names.append(text.strip())
    return names


def encode_name_record(name: str) -> bytes:
    """Encode a string into a 14-byte NUL-padded ASCII record (max 13 chars + NUL)."""
    if not isinstance(name, str):
        raise ProtocolError(f"name must be str, got {type(name).__name__}")
    clean = name.strip().encode("ascii", errors="replace")[: NAME_RECORD_LEN - 1]
    return clean.ljust(NAME_RECORD_LEN, b"\x00")


def build_rename_slot(category: str, slot: int, name: str) -> bytes:
    """Build a 0x22 command to rename an AMP (0x90000000) or CAB (0x80000000) slot in flash."""
    cat = str(category).lower().strip()
    if cat not in ("amp", "cab"):
        raise ProtocolError(f"category must be 'amp' or 'cab', got {category!r}")
    slot_idx = _require_range(slot, 0, NAME_RECORD_COUNT - 1, "slot")
    base_addr = ADDR_AMP_NAMES if cat == "amp" else ADDR_CAB_NAMES
    addr = base_addr + slot_idx * NAME_RECORD_LEN
    data = encode_name_record(name)
    body = (
        bytes([SPACE_NAMES])
        + addr.to_bytes(4, "little")
        + len(data).to_bytes(3, "little")
        + data
    )
    return build_frame(CMD_WRITE, body)


def parse_capture_header(data: bytes) -> dict[str, Any]:
    """Parse and validate an AM4, AM3, AM2, or CAB capture file header."""
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise ProtocolError("Capture data must be bytes-like")
    raw = bytes(data)
    if len(raw) < 18:
        raise ProtocolError(f"Capture payload too short: {len(raw)} bytes (min 18)")
    magic = raw[:4]
    if magic not in (b"AM4\x00", b"AM3\x00", b"AM2\x00", b"CAB\x00"):
        raise ProtocolError(f"Invalid capture magic: {magic!r}")
    magic_str = magic[:3].decode("ascii")
    name = raw[4:18].split(b"\x00", 1)[0].decode("ascii", errors="replace").strip()
    kind = "cab" if magic == b"CAB\x00" else "amp"
    return {
        "valid": True,
        "magic": magic_str,
        "kind": kind,
        "name": name,
        "size": len(raw),
    }


def parse_wav_header(data: bytes) -> dict[str, Any]:
    """Parse and validate a standard RIFF/WAVE impulse response (IR) header."""
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise ProtocolError("WAV data must be bytes-like")
    raw = bytes(data)
    if len(raw) < 44:
        raise ProtocolError(f"WAV payload too short: {len(raw)} bytes (min 44)")
    if raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
        raise ProtocolError("Invalid RIFF/WAVE header")

    import struct

    idx = 12
    fmt_found = False
    data_found = False
    channels = 1
    sample_rate = 48000
    bits_per_sample = 24
    num_samples = 0

    while idx + 8 <= len(raw):
        chunk_id = raw[idx : idx + 4]
        chunk_size = struct.unpack_from("<I", raw, idx + 4)[0]
        idx += 8
        if chunk_id == b"fmt ":
            if chunk_size < 16:
                raise ProtocolError(f"Malformed fmt chunk size: {chunk_size}")
            fmt_found = True
            audio_format, channels, sample_rate, byte_rate, block_align, bits_per_sample = (
                struct.unpack_from("<HHIIHH", raw, idx)
            )
            if audio_format not in (1, 3):
                raise ProtocolError(f"Unsupported WAV audio format: {audio_format}")
        elif chunk_id == b"data":
            data_found = True
            bytes_per_sample = bits_per_sample // 8 if bits_per_sample else 2
            channel_count = channels if channels else 1
            num_samples = (
                chunk_size // (bytes_per_sample * channel_count)
                if (bytes_per_sample * channel_count)
                else 0
            )
            break
        idx += chunk_size

    if not fmt_found or not data_found:
        raise ProtocolError("WAV file missing required fmt or data chunks")

    return {
        "valid": True,
        "channels": channels,
        "sample_rate": sample_rate,
        "bits_per_sample": bits_per_sample,
        "samples": num_samples,
        "size": len(raw),
    }


def format_knob_display(block_id: int, model_id: int, slot: int, raw_value: int) -> str:
    """Format a raw 0..100 knob value into human-readable physical units."""
    blk = _require_range(block_id, 0, 5, "block_id")
    mdl = _require_int(model_id, "model_id")
    if mdl not in BLOCKS[blk].models:
        raise ProtocolError(f"Invalid model_id {mdl} for block {BLOCKS[blk].name}")
    slot_idx = _require_range(slot, 0, 5, "slot")
    raw = _require_range(raw_value, 0, 100, "raw_value")

    model_spec = BLOCKS[blk].models[mdl]
    if slot_idx >= len(model_spec.knobs):
        return ""

    if blk == 5:  # CAB
        if slot_idx == 1:  # Low Cut
            return f"{int(20 + raw * 2.8)} Hz"
        if slot_idx == 2:  # High Cut (0 = 5.0 kHz .. 100 = 18.0 kHz)
            return f"{5.0 + raw * 0.13:.1f} kHz"

    if blk == 3 and slot_idx == 0:  # DLY Time
        ms = round(50 + raw * 4.5) if mdl == 3 else round(100 + raw * 9.0)
        return f"{ms} ms"

    return str(raw)


def bpm_to_delay_raw(bpm: float, delay_model_id: int) -> int:
    """Convert a tempo in BPM to a clamped 0..100 DLY Time parameter value."""
    mdl = _require_int(delay_model_id, "delay_model_id")
    if mdl not in BLOCKS[3].models:
        raise ProtocolError(f"Invalid DLY model_id: {mdl}")
    if not isinstance(bpm, (int, float)) or isinstance(bpm, bool):
        raise ProtocolError(f"bpm must be numeric, got {type(bpm).__name__}")
    bpm_val = float(bpm)
    if not math.isfinite(bpm_val) or bpm_val <= 0:
        raise ProtocolError(f"bpm must be positive and finite, got {bpm}")

    ms = 60000.0 / bpm_val
    raw = round((ms - 50.0) / 4.5) if mdl == 3 else round((ms - 100.0) / 9.0)
    return max(0, min(100, int(raw)))


@dataclass
class PresetImage:
    """Parsed representation of a 92-byte ME-01 preset image."""

    volume: int
    order: list[int]
    states: list[int]
    models: list[int]
    knobs: list[list[int]]

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        self.volume = _require_range(self.volume, 0, 100, "volume")

        order_seq = _require_sequence(self.order, 6, "order")
        self.order = [_require_range(x, 0, 5, "order element") for x in order_seq]
        if sorted(self.order) != list(BLOCK_IDS):
            raise ProtocolError(f"order must be a permutation of 0..5, got {self.order}")

        states_seq = _require_sequence(self.states, 6, "states")
        self.states = [
            (1 if s else 0) if isinstance(s, bool) else _require_range(s, 0, 1, "state")
            for s in states_seq
        ]

        models_seq = _require_sequence(self.models, 6, "models")
        validated_models: list[int] = []
        for blk, mdl in enumerate(models_seq):
            mdl_int = _require_int(mdl, f"models[{blk}]")
            if mdl_int not in BLOCKS[blk].models:
                raise ProtocolError(f"Invalid model {mdl_int} for block {BLOCKS[blk].name}")
            validated_models.append(mdl_int)
        self.models = validated_models

        knobs_seq = _require_sequence(self.knobs, 6, "knobs")
        validated_knobs: list[list[int]] = []
        for blk, row in enumerate(knobs_seq):
            row_seq = _require_sequence(row, 6, f"knobs[{blk}]")
            validated_knobs.append(
                [_require_range(v, 0, 100, f"knobs[{blk}][{slot}]") for slot, v in enumerate(row_seq)]
            )
        self.knobs = validated_knobs

    @staticmethod
    def knob_addr(block_id: int, slot: int) -> int:
        """Return the RAM byte offset for (block_id, slot)."""
        blk = _require_range(block_id, 0, 5, "block_id")
        slot_idx = _require_range(slot, 0, 5, "slot")
        return BLOCKS[blk].base_addr + slot_idx * 2

    @classmethod
    def from_bytes(cls, raw92: bytes) -> PresetImage:
        """Parse a 92-byte preset buffer into a validated PresetImage."""
        if not isinstance(raw92, (bytes, bytearray, memoryview)):
            raise ProtocolError("raw92 must be bytes-like")
        raw = bytes(raw92)
        if len(raw) != PRESET_SIZE:
            raise ProtocolError(f"Preset image must be {PRESET_SIZE} bytes, got {len(raw)}")

        volume = int.from_bytes(raw[0:2], "little")
        order = list(raw[2:8])
        states = list(raw[8:14])
        models = list(raw[14:20])
        knobs = [
            [
                int.from_bytes(raw[0x14 + blk * 12 + slot * 2 : 0x14 + blk * 12 + slot * 2 + 2], "little")
                for slot in range(6)
            ]
            for blk in range(6)
        ]
        return cls(volume=volume, order=order, states=states, models=models, knobs=knobs)

    def to_bytes(self) -> bytes:
        """Serialize this PresetImage back to an exact 92-byte hardware buffer."""
        self._validate()
        buf = bytearray(PRESET_SIZE)
        buf[0:2] = self.volume.to_bytes(2, "little")
        buf[2:8] = bytes(self.order)
        buf[8:14] = bytes(self.states)
        buf[14:20] = bytes(self.models)
        for blk in range(6):
            base = BLOCKS[blk].base_addr
            for slot in range(6):
                buf[base + slot * 2 : base + slot * 2 + 2] = self.knobs[blk][slot].to_bytes(2, "little")
        return bytes(buf)

    def to_dict(
        self,
        amps: Sequence[str] | None = None,
        cabs: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        """Convert to a JSON-serializable dict, optionally resolving live AMP/CAB names."""
        self._validate()
        blocks_payload: list[dict[str, Any]] = []
        for blk in BLOCK_IDS:
            spec = BLOCKS[blk]
            mdl_id = self.models[blk]
            mdl_spec = spec.models[mdl_id]
            model_name = mdl_spec.name
            if blk == 1 and amps is not None and 0 <= mdl_id < len(amps):
                model_name = amps[mdl_id]
            elif blk == 5 and cabs is not None and 0 <= mdl_id < len(cabs):
                model_name = cabs[mdl_id]

            active_knobs = [
                {
                    "slot": slot,
                    "addr": spec.base_addr + slot * 2,
                    "label": label,
                    "raw": self.knobs[blk][slot],
                    "display": format_knob_display(blk, mdl_id, slot, self.knobs[blk][slot]),
                }
                for slot, label in enumerate(mdl_spec.knobs)
            ]
            blocks_payload.append(
                {
                    "block_id": blk,
                    "name": spec.name,
                    "enabled": bool(self.states[blk]),
                    "model_id": mdl_id,
                    "model_name": model_name,
                    "min_fw": mdl_spec.min_fw,
                    "knobs": active_knobs,
                }
            )

        return {
            "volume": self.volume,
            "order": list(self.order),
            "states": list(self.states),
            "models": list(self.models),
            "knobs": [list(row) for row in self.knobs],
            "raw_hex": self.to_bytes().hex(),
            "blocks": blocks_payload,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PresetImage:
        """Reconstruct a PresetImage from a dict produced by to_dict()."""
        if not isinstance(d, dict):
            raise ProtocolError("Preset dict must be a mapping")
        required = ("volume", "order", "states", "models", "knobs")
        if all(key in d for key in required):
            return cls(
                volume=d["volume"],
                order=d["order"],
                states=d["states"],
                models=d["models"],
                knobs=d["knobs"],
            )
        if "raw_hex" in d and isinstance(d["raw_hex"], str):
            try:
                return cls.from_bytes(bytes.fromhex(d["raw_hex"]))
            except ValueError as exc:
                raise ProtocolError(f"Invalid raw_hex in preset dict: {exc}") from exc
        raise ProtocolError("Preset dict missing required fields")

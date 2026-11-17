"""Windows WinMM (winmm.dll) USB-MIDI SysEx transport with CALLBACK_EVENT ring."""

from __future__ import annotations

import ctypes
import math
import re
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass
from typing import Any

CALLBACK_EVENT = 0x00050000
MHDR_DONE = 0x00000001
MHDR_PREPARED = 0x00000002
MHDR_INQUEUE = 0x00000004

MMSYSERR_NOERROR = 0
MIDIERR_STILLPLAYING = 65

WAIT_OBJECT_0 = 0x00000000
WAIT_TIMEOUT = 0x00000102

MAXPNAMELEN = 32

_SYNTH_PENALTY_KEYWORDS = ("wavetable", "synth", "microsoft", "mapper")
_PREFIX_NUM_RE = re.compile(r"^\d+-\s*")
_TOKEN_RE = re.compile(r"[a-z0-9]+")


class MidiTransportError(RuntimeError):
    """Raised when WinMM port discovery, I/O, or SysEx waiting fails."""


@dataclass(frozen=True)
class MidiPortPair:
    """Candidate WinMM input/output port pair with heuristic match score."""

    in_id: int
    in_name: str
    out_id: int
    out_name: str
    match_score: int


class MIDIINCAPSW(ctypes.Structure):
    _fields_ = [
        ("wMid", wintypes.WORD),
        ("wPid", wintypes.WORD),
        ("vDriverVersion", wintypes.UINT),
        ("szPname", wintypes.WCHAR * MAXPNAMELEN),
        ("dwSupport", wintypes.DWORD),
    ]


class MIDIOUTCAPSW(ctypes.Structure):
    _fields_ = [
        ("wMid", wintypes.WORD),
        ("wPid", wintypes.WORD),
        ("vDriverVersion", wintypes.UINT),
        ("szPname", wintypes.WCHAR * MAXPNAMELEN),
        ("wTechnology", wintypes.WORD),
        ("wVoices", wintypes.WORD),
        ("wNotes", wintypes.WORD),
        ("wChannelMask", wintypes.WORD),
        ("dwSupport", wintypes.DWORD),
    ]


class MIDIHDR(ctypes.Structure):
    _fields_ = [
        ("lpData", ctypes.c_void_p),
        ("dwBufferLength", wintypes.DWORD),
        ("dwBytesRecorded", wintypes.DWORD),
        ("dwUser", ctypes.c_size_t),
        ("dwFlags", wintypes.DWORD),
        ("lpNext", ctypes.c_void_p),
        ("reserved", ctypes.c_size_t),
        ("dwOffset", wintypes.DWORD),
        ("dwReserved", ctypes.c_size_t * 8),
    ]


@dataclass
class _InputBufferEntry:
    buf: ctypes.Array[ctypes.c_ubyte]
    hdr: MIDIHDR
    hdr_ptr: Any
    prepared: bool = False


_DEFAULT_WINMM: Any = None
_DEFAULT_KERNEL32: Any = None


def _get_default_winmm() -> Any:
    global _DEFAULT_WINMM
    if _DEFAULT_WINMM is not None:
        return _DEFAULT_WINMM
    if not hasattr(ctypes, "WinDLL"):
        raise MidiTransportError("ctypes.WinDLL is only available on Windows")
    lib = ctypes.WinDLL("winmm")

    lib.midiInGetNumDevs.argtypes = []
    lib.midiInGetNumDevs.restype = wintypes.UINT
    lib.midiOutGetNumDevs.argtypes = []
    lib.midiOutGetNumDevs.restype = wintypes.UINT

    lib.midiInGetDevCapsW.argtypes = [ctypes.c_size_t, ctypes.POINTER(MIDIINCAPSW), wintypes.UINT]
    lib.midiInGetDevCapsW.restype = wintypes.UINT
    lib.midiOutGetDevCapsW.argtypes = [ctypes.c_size_t, ctypes.POINTER(MIDIOUTCAPSW), wintypes.UINT]
    lib.midiOutGetDevCapsW.restype = wintypes.UINT

    lib.midiInOpen.argtypes = [
        ctypes.POINTER(ctypes.c_void_p),
        wintypes.UINT,
        ctypes.c_size_t,
        ctypes.c_size_t,
        wintypes.DWORD,
    ]
    lib.midiInOpen.restype = wintypes.UINT
    lib.midiOutOpen.argtypes = [
        ctypes.POINTER(ctypes.c_void_p),
        wintypes.UINT,
        ctypes.c_size_t,
        ctypes.c_size_t,
        wintypes.DWORD,
    ]
    lib.midiOutOpen.restype = wintypes.UINT

    lib.midiInPrepareHeader.argtypes = [ctypes.c_void_p, ctypes.POINTER(MIDIHDR), wintypes.UINT]
    lib.midiInPrepareHeader.restype = wintypes.UINT
    lib.midiInAddBuffer.argtypes = [ctypes.c_void_p, ctypes.POINTER(MIDIHDR), wintypes.UINT]
    lib.midiInAddBuffer.restype = wintypes.UINT
    lib.midiInStart.argtypes = [ctypes.c_void_p]
    lib.midiInStart.restype = wintypes.UINT
    lib.midiInStop.argtypes = [ctypes.c_void_p]
    lib.midiInStop.restype = wintypes.UINT
    lib.midiInReset.argtypes = [ctypes.c_void_p]
    lib.midiInReset.restype = wintypes.UINT
    lib.midiInUnprepareHeader.argtypes = [ctypes.c_void_p, ctypes.POINTER(MIDIHDR), wintypes.UINT]
    lib.midiInUnprepareHeader.restype = wintypes.UINT
    lib.midiInClose.argtypes = [ctypes.c_void_p]
    lib.midiInClose.restype = wintypes.UINT

    lib.midiOutPrepareHeader.argtypes = [ctypes.c_void_p, ctypes.POINTER(MIDIHDR), wintypes.UINT]
    lib.midiOutPrepareHeader.restype = wintypes.UINT
    lib.midiOutLongMsg.argtypes = [ctypes.c_void_p, ctypes.POINTER(MIDIHDR), wintypes.UINT]
    lib.midiOutLongMsg.restype = wintypes.UINT
    lib.midiOutUnprepareHeader.argtypes = [ctypes.c_void_p, ctypes.POINTER(MIDIHDR), wintypes.UINT]
    lib.midiOutUnprepareHeader.restype = wintypes.UINT
    lib.midiOutReset.argtypes = [ctypes.c_void_p]
    lib.midiOutReset.restype = wintypes.UINT
    lib.midiOutClose.argtypes = [ctypes.c_void_p]
    lib.midiOutClose.restype = wintypes.UINT

    lib.midiInGetErrorTextW.argtypes = [wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]
    lib.midiInGetErrorTextW.restype = wintypes.UINT
    lib.midiOutGetErrorTextW.argtypes = [wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]
    lib.midiOutGetErrorTextW.restype = wintypes.UINT

    _DEFAULT_WINMM = lib
    return lib


def _get_default_kernel32() -> Any:
    global _DEFAULT_KERNEL32
    if _DEFAULT_KERNEL32 is not None:
        return _DEFAULT_KERNEL32
    if not hasattr(ctypes, "WinDLL"):
        raise MidiTransportError("ctypes.WinDLL is only available on Windows")
    lib = ctypes.WinDLL("kernel32", use_last_error=True)

    lib.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    lib.CreateEventW.restype = ctypes.c_void_p
    lib.WaitForSingleObject.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    lib.WaitForSingleObject.restype = wintypes.DWORD
    lib.ResetEvent.argtypes = [ctypes.c_void_p]
    lib.ResetEvent.restype = wintypes.BOOL
    lib.CloseHandle.argtypes = [ctypes.c_void_p]
    lib.CloseHandle.restype = wintypes.BOOL

    _DEFAULT_KERNEL32 = lib
    return lib


def _format_mm_error(winmm: Any, err_code: int, *, is_input: bool) -> str:
    buf = ctypes.create_unicode_buffer(256)
    getter = winmm.midiInGetErrorTextW if is_input else winmm.midiOutGetErrorTextW
    if getter(err_code, buf, len(buf)) == MMSYSERR_NOERROR and buf.value:
        return f"WinMM error {err_code}: {buf.value}"
    return f"WinMM error {err_code}"


def _check_mm(winmm: Any, err_code: int, context: str, *, is_input: bool) -> None:
    if err_code != MMSYSERR_NOERROR:
        raise MidiTransportError(f"{context} failed ({_format_mm_error(winmm, err_code, is_input=is_input)})")


def enumerate_midi_ports(
    winmm_lib: Any = None,
) -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
    """Return ``(inputs, outputs)`` as lists of ``(device_id, device_name)``."""
    winmm = winmm_lib if winmm_lib is not None else _get_default_winmm()

    inputs: list[tuple[int, str]] = []
    in_count = int(winmm.midiInGetNumDevs())
    for idx in range(in_count):
        caps = MIDIINCAPSW()
        res = winmm.midiInGetDevCapsW(idx, ctypes.pointer(caps), ctypes.sizeof(MIDIINCAPSW))
        if res == MMSYSERR_NOERROR:
            inputs.append((idx, str(caps.szPname)))

    outputs: list[tuple[int, str]] = []
    out_count = int(winmm.midiOutGetNumDevs())
    for idx in range(out_count):
        caps = MIDIOUTCAPSW()
        res = winmm.midiOutGetDevCapsW(idx, ctypes.pointer(caps), ctypes.sizeof(MIDIOUTCAPSW))
        if res == MMSYSERR_NOERROR:
            outputs.append((idx, str(caps.szPname)))

    return inputs, outputs


def _score_port_pair(in_name: str, out_name: str) -> int:
    in_lower = in_name.strip().lower()
    out_lower = out_name.strip().lower()
    in_norm = _PREFIX_NUM_RE.sub("", in_lower)
    out_norm = _PREFIX_NUM_RE.sub("", out_lower)

    score = 0
    if in_lower == out_lower:
        score += 100
    elif in_norm == out_norm:
        score += 90
    elif in_norm and out_norm and (in_norm in out_norm or out_norm in in_norm):
        score += 50

    if "usb-midi" in in_lower and "usb-midi" in out_lower:
        score += 40
    elif "me-01" in in_lower and "me-01" in out_lower:
        score += 40

    in_tokens = set(_TOKEN_RE.findall(in_norm))
    out_tokens = set(_TOKEN_RE.findall(out_norm))
    score += 10 * len(in_tokens & out_tokens)

    if any(kw in out_lower for kw in _SYNTH_PENALTY_KEYWORDS) and not any(
        kw in in_lower for kw in _SYNTH_PENALTY_KEYWORDS
    ):
        score -= 80

    return score


def find_candidate_pairs(winmm_lib: Any = None) -> list[MidiPortPair]:
    """Enumerate WinMM ports and return input/output pairs ranked by match score."""
    inputs, outputs = enumerate_midi_ports(winmm_lib=winmm_lib)
    pairs = [
        MidiPortPair(
            in_id=in_id,
            in_name=in_name,
            out_id=out_id,
            out_name=out_name,
            match_score=_score_port_pair(in_name, out_name),
        )
        for in_id, in_name in inputs
        for out_id, out_name in outputs
    ]
    pairs.sort(key=lambda pair: (-pair.match_score, pair.in_id, pair.out_id))
    return pairs


class WinMMTransport:
    """Thread-safe Windows WinMM USB-MIDI SysEx transport using CALLBACK_EVENT."""

    def __init__(
        self,
        in_id: int,
        out_id: int,
        buffer_count: int = 8,
        buffer_size: int = 8192,
        winmm_lib: Any = None,
        kernel32_lib: Any = None,
    ) -> None:
        if buffer_count < 1:
            raise ValueError("buffer_count must be >= 1")
        if buffer_size < 64:
            raise ValueError("buffer_size must be >= 64")
        self.in_id = int(in_id)
        self.out_id = int(out_id)
        self.buffer_count = int(buffer_count)
        self.buffer_size = int(buffer_size)
        self._winmm = winmm_lib if winmm_lib is not None else _get_default_winmm()
        self._kernel32 = kernel32_lib if kernel32_lib is not None else _get_default_kernel32()
        self._lock = threading.Lock()
        self._h_in: int | None = None
        self._h_out: int | None = None
        self._event: int | None = None
        self._in_ring: list[_InputBufferEntry] = []
        self._next_idx = 0
        self._is_open = False

    @property
    def is_open(self) -> bool:
        return self._is_open

    def __enter__(self) -> WinMMTransport:
        self.open()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def open(self) -> None:
        with self._lock:
            if self._is_open:
                return
            try:
                event = self._kernel32.CreateEventW(None, False, False, None)
                if not event:
                    raise MidiTransportError("CreateEventW failed while opening WinMMTransport")
                self._event = int(event)

                h_out = ctypes.c_void_p()
                res = self._winmm.midiOutOpen(ctypes.pointer(h_out), self.out_id, 0, 0, 0)
                _check_mm(self._winmm, res, f"midiOutOpen({self.out_id})", is_input=False)
                self._h_out = int(h_out.value)

                h_in = ctypes.c_void_p()
                res = self._winmm.midiInOpen(
                    ctypes.pointer(h_in),
                    self.in_id,
                    self._event,
                    0,
                    CALLBACK_EVENT,
                )
                _check_mm(self._winmm, res, f"midiInOpen({self.in_id})", is_input=True)
                self._h_in = int(h_in.value)

                self._in_ring = []
                self._next_idx = 0
                hdr_size = ctypes.sizeof(MIDIHDR)
                for _ in range(self.buffer_count):
                    buf = (ctypes.c_ubyte * self.buffer_size)()
                    hdr = MIDIHDR()
                    hdr.lpData = ctypes.addressof(buf)
                    hdr.dwBufferLength = self.buffer_size
                    hdr_ptr = ctypes.pointer(hdr)
                    entry = _InputBufferEntry(buf=buf, hdr=hdr, hdr_ptr=hdr_ptr)
                    self._in_ring.append(entry)

                    res = self._winmm.midiInPrepareHeader(self._h_in, hdr_ptr, hdr_size)
                    _check_mm(self._winmm, res, "midiInPrepareHeader", is_input=True)
                    entry.prepared = True

                    res = self._winmm.midiInAddBuffer(self._h_in, hdr_ptr, hdr_size)
                    _check_mm(self._winmm, res, "midiInAddBuffer", is_input=True)

                res = self._winmm.midiInStart(self._h_in)
                _check_mm(self._winmm, res, "midiInStart", is_input=True)
                self._is_open = True
            except Exception:
                self._close_locked()
                raise

    def close(self) -> None:
        with self._lock:
            self._close_locked()

    def _close_locked(self) -> None:
        hdr_size = ctypes.sizeof(MIDIHDR)
        if self._h_in is not None:
            try:
                self._winmm.midiInStop(self._h_in)
            finally:
                self._winmm.midiInReset(self._h_in)
                for entry in self._in_ring:
                    if entry.prepared:
                        self._winmm.midiInUnprepareHeader(self._h_in, entry.hdr_ptr, hdr_size)
                        entry.prepared = False
                self._winmm.midiInClose(self._h_in)
            self._h_in = None

        if self._h_out is not None:
            self._winmm.midiOutReset(self._h_out)
            self._winmm.midiOutClose(self._h_out)
            self._h_out = None

        if self._event is not None:
            self._kernel32.CloseHandle(self._event)
            self._event = None

        self._in_ring.clear()
        self._next_idx = 0
        self._is_open = False

    def _requeue_entry(self, entry: _InputBufferEntry) -> None:
        entry.hdr.dwBytesRecorded = 0
        res = self._winmm.midiInAddBuffer(self._h_in, entry.hdr_ptr, ctypes.sizeof(MIDIHDR))
        _check_mm(self._winmm, res, "midiInAddBuffer", is_input=True)

    def _drain_stale_buffers(self) -> None:
        # First advance through any contiguous completed buffers in FIFO order.
        for _ in range(self.buffer_count):
            entry = self._in_ring[self._next_idx]
            if not (entry.hdr.dwFlags & MHDR_DONE):
                break
            self._requeue_entry(entry)
            self._next_idx = (self._next_idx + 1) % self.buffer_count

    def _collect_ready_chunks(self) -> list[bytes]:
        chunks: list[bytes] = []
        for _ in range(self.buffer_count):
            entry = self._in_ring[self._next_idx]
            if not (entry.hdr.dwFlags & MHDR_DONE):
                break
            recorded = min(int(entry.hdr.dwBytesRecorded), self.buffer_size)
            if recorded > 0:
                chunks.append(bytes(entry.buf[:recorded]))
            self._requeue_entry(entry)
            self._next_idx = (self._next_idx + 1) % self.buffer_count
        return chunks

    def _consume_ready_sysex(
        self, frame_buf: bytearray, in_sysex: bool
    ) -> tuple[bytes | None, bool]:
        """Consume ready input chunks and return a completed SysEx frame if found."""
        for chunk in self._collect_ready_chunks():
            if not in_sysex:
                start_idx = chunk.find(0xF0)
                if start_idx == -1:
                    continue
                frame_buf.extend(chunk[start_idx:])
                in_sysex = True
            else:
                frame_buf.extend(chunk)

            end_idx = frame_buf.find(0xF7, 1)
            if end_idx != -1:
                return bytes(frame_buf[: end_idx + 1]), True
        return None, in_sysex

    def _send_sysex_locked(self, sysex_out: bytes) -> None:
        out_buf = (ctypes.c_ubyte * len(sysex_out)).from_buffer_copy(sysex_out)
        out_hdr = MIDIHDR()
        out_hdr.lpData = ctypes.addressof(out_buf)
        out_hdr.dwBufferLength = len(sysex_out)
        out_hdr.dwBytesRecorded = len(sysex_out)
        out_hdr_ptr = ctypes.pointer(out_hdr)
        hdr_size = ctypes.sizeof(MIDIHDR)

        res = self._winmm.midiOutPrepareHeader(self._h_out, out_hdr_ptr, hdr_size)
        _check_mm(self._winmm, res, "midiOutPrepareHeader", is_input=False)
        try:
            res = self._winmm.midiOutLongMsg(self._h_out, out_hdr_ptr, hdr_size)
            _check_mm(self._winmm, res, "midiOutLongMsg", is_input=False)
        finally:
            unprep_deadline = time.monotonic() + 0.2
            while True:
                unprep_res = self._winmm.midiOutUnprepareHeader(self._h_out, out_hdr_ptr, hdr_size)
                if unprep_res == MMSYSERR_NOERROR:
                    break
                if unprep_res != MIDIERR_STILLPLAYING or time.monotonic() >= unprep_deadline:
                    self._winmm.midiOutReset(self._h_out)
                    self._winmm.midiOutUnprepareHeader(self._h_out, out_hdr_ptr, hdr_size)
                    break
                time.sleep(0.001)

    def transact(self, sysex_out: bytes, timeout_ms: int = 800) -> bytes:
        """Send a SysEx frame and wait for the single SysEx reply under a mutex."""
        if not isinstance(sysex_out, (bytes, bytearray)):
            raise MidiTransportError("Outbound SysEx payload must be bytes")
        payload = bytes(sysex_out)
        if len(payload) < 2 or payload[0] != 0xF0 or payload[-1] != 0xF7:
            raise MidiTransportError("Outbound SysEx frame must begin with 0xF0 and end with 0xF7")
        if timeout_ms < 0:
            raise ValueError("timeout_ms must be >= 0")

        with self._lock:
            if not self._is_open or self._h_in is None or self._h_out is None or self._event is None:
                raise MidiTransportError("WinMMTransport is not open")

            self._drain_stale_buffers()
            self._kernel32.ResetEvent(self._event)
            self._send_sysex_locked(payload)

            deadline = time.monotonic() + (timeout_ms / 1000.0)
            frame_buf = bytearray()
            in_sysex = False

            while True:
                complete, in_sysex = self._consume_ready_sysex(frame_buf, in_sysex)
                if complete is not None:
                    return complete

                remaining_s = deadline - time.monotonic()
                if remaining_s <= 0:
                    raise MidiTransportError(f"Timed out waiting for MIDI SysEx reply after {timeout_ms} ms")
                remaining_ms = max(1, math.ceil(remaining_s * 1000.0))

                wait_res = self._kernel32.WaitForSingleObject(self._event, remaining_ms)
                if wait_res == WAIT_OBJECT_0:
                    continue
                if wait_res == WAIT_TIMEOUT:
                    complete, in_sysex = self._consume_ready_sysex(frame_buf, in_sysex)
                    if complete is not None:
                        return complete
                    raise MidiTransportError(f"Timed out waiting for MIDI SysEx reply after {timeout_ms} ms")
                raise MidiTransportError(f"WaitForSingleObject failed with status 0x{wait_res:08x}")

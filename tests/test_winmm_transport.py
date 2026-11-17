import ctypes
import unittest

from me01_rig.protocol import build_identity_query, parse_frame, unwrap_sysex, wrap_sysex
from me01_rig.winmm_midi import (
    CALLBACK_EVENT,
    MHDR_DONE,
    MHDR_INQUEUE,
    MHDR_PREPARED,
    MidiPortPair,
    MidiTransportError,
    WinMMTransport,
    enumerate_midi_ports,
    find_candidate_pairs,
)

WAIT_OBJECT_0 = 0x00000000
WAIT_TIMEOUT = 0x00000102


class FakeKernel32:
    """In-memory stub of kernel32 event APIs for deterministic WinMMTransport tests."""

    def __init__(self) -> None:
        self._next_handle = 0x3000
        self.events: dict[int, bool] = {}
        self.closed_handles: list[int] = []

    def CreateEventW(self, attrs, manual_reset: bool, initial_state: bool, name) -> int:
        self._next_handle += 1
        handle = self._next_handle
        self.events[handle] = bool(initial_state)
        return handle

    def SetEvent(self, handle: int) -> int:
        if handle in self.events:
            self.events[handle] = True
            return 1
        return 0

    def ResetEvent(self, handle: int) -> int:
        if handle in self.events:
            self.events[handle] = False
            return 1
        return 0

    def WaitForSingleObject(self, handle: int, timeout_ms: int) -> int:
        if self.events.get(handle, False):
            self.events[handle] = False
            return WAIT_OBJECT_0
        return WAIT_TIMEOUT

    def CloseHandle(self, handle: int) -> int:
        self.closed_handles.append(handle)
        self.events.pop(handle, None)
        return 1


class FakeWinMM:
    """In-memory stub of winmm.dll MIDI APIs for deterministic offline tests."""

    def __init__(
        self,
        kernel32: FakeKernel32,
        in_ports: list[str] | None = None,
        out_ports: list[str] | None = None,
    ) -> None:
        self.kernel32 = kernel32
        self.in_ports = ["USB-Midi"] if in_ports is None else list(in_ports)
        self.out_ports = ["USB-Midi"] if out_ports is None else list(out_ports)
        self.in_open = False
        self.out_open = False
        self.in_started = False
        self.event_handle: int | None = None
        self.prepared_in_headers: set[int] = set()
        self.queued_in_headers: list = []
        self.sent_messages: list[bytes] = []
        self.add_buffer_calls = 0
        self.calls: list[str] = []
        self.on_out_sysex = None

    def midiInGetNumDevs(self) -> int:
        return len(self.in_ports)

    def midiOutGetNumDevs(self) -> int:
        return len(self.out_ports)

    def midiInGetDevCapsW(self, dev_id: int, caps_ptr, cb_size: int) -> int:
        if dev_id < 0 or dev_id >= len(self.in_ports):
            return 2  # MMSYSERR_BADDEVICEID
        caps_ptr.contents.szPname = self.in_ports[dev_id]
        return 0

    def midiOutGetDevCapsW(self, dev_id: int, caps_ptr, cb_size: int) -> int:
        if dev_id < 0 or dev_id >= len(self.out_ports):
            return 2
        caps_ptr.contents.szPname = self.out_ports[dev_id]
        return 0

    def midiInOpen(self, h_in_ptr, dev_id: int, callback: int, instance: int, flags: int) -> int:
        self.calls.append("midiInOpen")
        if flags != CALLBACK_EVENT:
            return 11  # MMSYSERR_INVALPARAM
        if dev_id < 0 or dev_id >= len(self.in_ports):
            return 2
        self.in_open = True
        self.event_handle = int(callback)
        h_in_ptr.contents.value = 0x1001
        return 0

    def midiOutOpen(self, h_out_ptr, dev_id: int, callback: int, instance: int, flags: int) -> int:
        self.calls.append("midiOutOpen")
        if dev_id < 0 or dev_id >= len(self.out_ports):
            return 2
        self.out_open = True
        h_out_ptr.contents.value = 0x2001
        return 0

    def midiInPrepareHeader(self, h_in: int, hdr_ptr, cb_size: int) -> int:
        self.calls.append("midiInPrepareHeader")
        hdr = hdr_ptr.contents
        hdr.dwFlags |= MHDR_PREPARED
        self.prepared_in_headers.add(ctypes.addressof(hdr))
        return 0

    def midiInAddBuffer(self, h_in: int, hdr_ptr, cb_size: int) -> int:
        self.calls.append("midiInAddBuffer")
        self.add_buffer_calls += 1
        hdr = hdr_ptr.contents
        hdr.dwFlags &= ~MHDR_DONE
        hdr.dwFlags |= MHDR_INQUEUE
        hdr.dwBytesRecorded = 0
        self.queued_in_headers.append(hdr_ptr)
        return 0

    def midiInStart(self, h_in: int) -> int:
        self.calls.append("midiInStart")
        self.in_started = True
        return 0

    def midiInStop(self, h_in: int) -> int:
        self.calls.append("midiInStop")
        self.in_started = False
        return 0

    def midiInReset(self, h_in: int) -> int:
        self.calls.append("midiInReset")
        for hdr_ptr in self.queued_in_headers:
            hdr_ptr.contents.dwFlags &= ~MHDR_INQUEUE
            hdr_ptr.contents.dwFlags |= MHDR_DONE
        self.queued_in_headers.clear()
        return 0

    def midiInUnprepareHeader(self, h_in: int, hdr_ptr, cb_size: int) -> int:
        self.calls.append("midiInUnprepareHeader")
        hdr = hdr_ptr.contents
        hdr.dwFlags &= ~MHDR_PREPARED
        self.prepared_in_headers.discard(ctypes.addressof(hdr))
        return 0

    def midiInClose(self, h_in: int) -> int:
        self.calls.append("midiInClose")
        self.in_open = False
        return 0

    def midiOutPrepareHeader(self, h_out: int, hdr_ptr, cb_size: int) -> int:
        self.calls.append("midiOutPrepareHeader")
        hdr_ptr.contents.dwFlags |= MHDR_PREPARED
        return 0

    def midiOutLongMsg(self, h_out: int, hdr_ptr, cb_size: int) -> int:
        self.calls.append("midiOutLongMsg")
        hdr = hdr_ptr.contents
        payload = ctypes.string_at(hdr.lpData, hdr.dwBufferLength)
        self.sent_messages.append(payload)
        hdr.dwFlags |= MHDR_DONE
        if self.on_out_sysex is not None:
            reply = self.on_out_sysex(payload)
            if reply is not None:
                self.push_incoming_sysex(reply)
        return 0

    def midiOutUnprepareHeader(self, h_out: int, hdr_ptr, cb_size: int) -> int:
        self.calls.append("midiOutUnprepareHeader")
        hdr_ptr.contents.dwFlags &= ~MHDR_PREPARED
        return 0

    def midiOutReset(self, h_out: int) -> int:
        self.calls.append("midiOutReset")
        return 0

    def midiOutClose(self, h_out: int) -> int:
        self.calls.append("midiOutClose")
        self.out_open = False
        return 0

    def midiInGetErrorTextW(self, err: int, buf, cch: int) -> int:
        buf.value = f"InError({err})"
        return 0

    def midiOutGetErrorTextW(self, err: int, buf, cch: int) -> int:
        buf.value = f"OutError({err})"
        return 0

    def push_incoming_sysex(self, data: bytes) -> None:
        if not self.queued_in_headers:
            raise AssertionError("No queued MIDIHDR buffers available in fake ring!")
        hdr_ptr = self.queued_in_headers.pop(0)
        hdr = hdr_ptr.contents
        if len(data) > hdr.dwBufferLength:
            raise AssertionError("Incoming test packet exceeds buffer length")
        ctypes.memmove(hdr.lpData, data, len(data))
        hdr.dwBytesRecorded = len(data)
        hdr.dwFlags &= ~MHDR_INQUEUE
        hdr.dwFlags |= MHDR_DONE
        if self.event_handle is not None:
            self.kernel32.SetEvent(self.event_handle)


class WinMMTransportTests(unittest.TestCase):
    def test_port_enumeration_and_pair_matching(self) -> None:
        kernel32 = FakeKernel32()
        winmm = FakeWinMM(
            kernel32,
            in_ports=["LoopBe Internal MIDI", "USB-Midi"],
            out_ports=["Microsoft GS Wavetable Synth", "USB-Midi", "LoopBe Internal MIDI"],
        )

        inputs, outputs = enumerate_midi_ports(winmm_lib=winmm)
        self.assertEqual(inputs, [(0, "LoopBe Internal MIDI"), (1, "USB-Midi")])
        self.assertEqual(
            outputs,
            [(0, "Microsoft GS Wavetable Synth"), (1, "USB-Midi"), (2, "LoopBe Internal MIDI")],
        )

        pairs = find_candidate_pairs(winmm_lib=winmm)
        self.assertGreaterEqual(len(pairs), 2)
        self.assertIsInstance(pairs[0], MidiPortPair)
        self.assertEqual((pairs[0].in_id, pairs[0].in_name), (1, "USB-Midi"))
        self.assertEqual((pairs[0].out_id, pairs[0].out_name), (1, "USB-Midi"))

        synth_pairs = [p for p in pairs if p.out_name == "Microsoft GS Wavetable Synth"]
        self.assertTrue(synth_pairs)
        self.assertGreater(pairs[0].match_score, synth_pairs[0].match_score)

    def test_transact_drains_stale_buffer_before_sending(self) -> None:
        kernel32 = FakeKernel32()
        winmm = FakeWinMM(kernel32)
        stale_reply = b"\xf0\x00\x01\x02\x03\xf7"
        fresh_reply = b"\xf0\x00\x32\x45\x11\x22\x33\xf7"
        outbound = wrap_sysex(build_identity_query())

        with WinMMTransport(
            in_id=0,
            out_id=0,
            buffer_count=4,
            buffer_size=1024,
            winmm_lib=winmm,
            kernel32_lib=kernel32,
        ) as transport:
            self.assertTrue(transport.is_open)
            # Inject a stale packet already waiting in the input ring before transact() runs.
            winmm.push_incoming_sysex(stale_reply)
            winmm.on_out_sysex = lambda _sent: fresh_reply

            received = transport.transact(outbound, timeout_ms=500)
            self.assertEqual(received, fresh_reply)
            self.assertEqual(winmm.sent_messages, [outbound])
            # Initial 4 buffers + 1 drained stale buffer + 1 fresh reply buffer = 6 add calls.
            self.assertEqual(winmm.add_buffer_calls, 6)
            self.assertEqual(len(winmm.queued_in_headers), 4)

        self.assertFalse(transport.is_open)

    def test_transact_timeout_and_requeue(self) -> None:
        kernel32 = FakeKernel32()
        winmm = FakeWinMM(kernel32)
        outbound = wrap_sysex(build_identity_query())

        with WinMMTransport(
            in_id=0,
            out_id=0,
            buffer_count=8,
            buffer_size=8192,
            winmm_lib=winmm,
            kernel32_lib=kernel32,
        ) as transport:
            # First verify >16 consecutive calls all re-queue MIDIHDR buffers cleanly.
            def reply_with_tag(sent: bytes) -> bytes:
                idx = len(winmm.sent_messages)
                return bytes([0xF0, 0x00, 0x32, 0x45, idx & 0x7F, 0xF7])

            winmm.on_out_sysex = reply_with_tag
            for i in range(1, 21):
                reply = transport.transact(outbound, timeout_ms=200)
                self.assertEqual(reply, bytes([0xF0, 0x00, 0x32, 0x45, i & 0x7F, 0xF7]))
                self.assertEqual(len(winmm.queued_in_headers), 8)
            self.assertEqual(winmm.add_buffer_calls, 8 + 20)

            # Now simulate timeout (device sends no reply) and verify clean error + lock release.
            winmm.on_out_sysex = None
            with self.assertRaises(MidiTransportError):
                transport.transact(outbound, timeout_ms=20)

            # Mutex must be unlocked so subsequent transact() succeeds without deadlock.
            expected_after_timeout = b"\xf0\x00\x32\x45\x7e\xf7"
            winmm.on_out_sysex = lambda _sent: expected_after_timeout
            self.assertEqual(transport.transact(outbound, timeout_ms=200), expected_after_timeout)

        self.assertIn("midiInStop", winmm.calls)
        self.assertIn("midiInReset", winmm.calls)
        self.assertIn("midiInUnprepareHeader", winmm.calls)
        self.assertEqual(len(winmm.prepared_in_headers), 0)

    def test_nul_bytes_multibuffer_and_open_failure_cleanup(self) -> None:
        kernel32 = FakeKernel32()
        winmm = FakeWinMM(kernel32)
        outbound = b"\xf0\x00\x32\x45\x00\x00\x7f\xf7"
        reply_part1 = b"\xf0\x00\x32\x45\x00\x11"
        reply_part2 = b"\x00\x22\x00\xf7"

        transport = WinMMTransport(
            in_id=0,
            out_id=0,
            buffer_count=4,
            buffer_size=128,
            winmm_lib=winmm,
            kernel32_lib=kernel32,
        )
        with self.assertRaises(MidiTransportError):
            transport.transact(outbound, timeout_ms=50)

        with transport:
            def send_split(sent: bytes) -> None:
                self.assertEqual(sent, outbound)
                winmm.push_incoming_sysex(reply_part1)
                winmm.push_incoming_sysex(reply_part2)
                return None

            winmm.on_out_sysex = send_split
            received = transport.transact(outbound, timeout_ms=200)
            self.assertEqual(received, reply_part1 + reply_part2)

        # Verify open() cleans up midiOut and event handle if midiInOpen fails.
        failing_winmm = FakeWinMM(kernel32, in_ports=[], out_ports=["USB-Midi"])
        bad_transport = WinMMTransport(
            in_id=0,
            out_id=0,
            winmm_lib=failing_winmm,
            kernel32_lib=kernel32,
        )
        with self.assertRaises(MidiTransportError):
            bad_transport.open()
        self.assertFalse(bad_transport.is_open)
        self.assertFalse(failing_winmm.out_open)
        self.assertEqual(len(kernel32.events), 0)

    def test_live_me01_readonly_if_connected(self) -> None:
        pairs = find_candidate_pairs()
        usb_pairs = [
            p
            for p in pairs
            if "usb-midi" in p.in_name.lower() and "usb-midi" in p.out_name.lower()
        ]
        if not usb_pairs:
            self.skipTest("No live USB-Midi input/output pair connected")

        pair = usb_pairs[0]
        with WinMMTransport(pair.in_id, pair.out_id) as transport:
            reply_sysex = transport.transact(wrap_sysex(build_identity_query()), timeout_ms=1000)

        frame = parse_frame(unwrap_sysex(reply_sysex))
        self.assertEqual(frame.cmd, 0x11)
        identity = frame.body.split(b"\x00", 1)[0].decode("ascii", errors="replace")
        self.assertTrue(
            identity.startswith("ME-01_"),
            f"Expected ME-01_ identity string, got {identity!r}",
        )


if __name__ == "__main__":
    unittest.main()

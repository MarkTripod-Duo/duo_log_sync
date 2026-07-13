"""
Unit tests for the network Writer.write dispatch and its error handling:
- UDP: OSError on sendto is caught and the payload spilled to a backlog file.
- TCP/TCPSSL: OSError on write/drain is logged and re-raised to the consumer.

Writer.__new__ is used with stub underlying writers so no real sockets are
opened (Writer.__init__ synchronously connects, which is unsuitable here).
"""

import asyncio
import tempfile
from pathlib import Path
from unittest import TestCase

from duologsync.config import Config
from duologsync.program import Program
from duologsync.writer import Writer


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _FakeUdpSocket:
    def __init__(self, error=None):
        self.error = error
        self.sent = []

    def sendto(self, data, addr):
        if self.error:
            raise self.error
        self.sent.append((data, addr))


class _FakeStream:
    def __init__(self, drain_error=None):
        self.drain_error = drain_error
        self.written = []
        self.drained = False

    def write(self, data):
        self.written.append(data)

    async def drain(self):
        if self.drain_error:
            raise self.drain_error
        self.drained = True


def _writer(protocol, underlying, hostname="127.0.0.1", port=8888):
    writer = Writer.__new__(Writer)
    writer.protocol = protocol
    writer.hostname = hostname
    writer.port = port
    writer.writer = underlying
    return writer


class TestUdpWrite(TestCase):
    def tearDown(self):
        Config._config = None
        Config._config_is_set = False
        Program._running = True

    def test_udp_success_calls_sendto(self):
        sock = _FakeUdpSocket()
        writer = _writer("UDP", sock)
        run(writer.write(b"payload\n", "auth"))
        self.assertEqual(sock.sent, [(b"payload\n", ("127.0.0.1", 8888))])

    def test_udp_oserror_spills_to_backlog(self):
        with tempfile.TemporaryDirectory() as directory:
            Config.set_config({"dls_settings": {"checkpointing": {"directory": directory}}})
            sock = _FakeUdpSocket(error=OSError(90, "Message too long"))
            writer = _writer("UDP", sock)

            # Must not raise — UDP failures are spilled, not propagated.
            run(writer.write(b"lost-log\n", "auth"))

            backlog = Path(directory) / "auth_udp_failed_ingestion_logs.txt"
            self.assertTrue(backlog.exists())
            self.assertEqual(backlog.read_text(), "lost-log\n")


class TestTcpWrite(TestCase):
    def tearDown(self):
        Program._running = True

    def test_tcp_success_writes_and_drains(self):
        stream = _FakeStream()
        writer = _writer("TCP", stream)
        run(writer.write(b"payload\n", "auth"))
        self.assertEqual(stream.written, [b"payload\n"])
        self.assertTrue(stream.drained)

    def test_tcp_oserror_is_reraised(self):
        stream = _FakeStream(drain_error=OSError(32, "Broken pipe"))
        writer = _writer("TCP", stream)
        with self.assertRaises(OSError):
            run(writer.write(b"payload\n", "auth"))

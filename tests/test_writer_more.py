"""
Coverage for the remaining writer.py surface: DatagramProtocol, the network
Writer factory/connection/shutdown paths, the FILE/inject wrappers, and the
LocalFileWriter worker/replay/rotation edge branches. No real network is used
(asyncio.open_connection / ssl are patched; UDP uses an unconnected socket).
"""

import asyncio
import socket
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import AsyncMock, MagicMock, patch

from duologsync.config import Config
from duologsync.program import Program
from duologsync.writer import DatagramProtocol, LocalFileWriter, Writer


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _writer_config(directory):
    return {
        "config_file_path": "cfg.yml",
        "dls_settings": {
            "checkpointing": {"directory": directory, "enabled": True},
            "file_output": {
                "queue_max_size": 100,
                "max_retries": 1,
                "retry_backoff_seconds": 0,
                "enable_test_input": False,
                "rotation": "none",
                "max_bytes": 1000,
                "rotation_interval": "daily",
                "backup_count": 3,
            },
        },
    }


def _net_writer(protocol):
    writer = Writer.__new__(Writer)
    writer.protocol = protocol
    writer.hostname = "127.0.0.1"
    writer.port = 8888
    writer.writer = None
    return writer


def _file_writer(directory, **overrides):
    params = {
        "filepath": str(Path(directory) / "out.log"),
        "checkpoint_directory": directory,
        "queue_max_size": 100,
        "max_retries": 1,
        "retry_backoff_seconds": 0,
        "enable_test_input": False,
        "rotation": "none",
    }
    params.update(overrides)
    return LocalFileWriter(**params)


class TestDatagramProtocol(TestCase):
    def tearDown(self):
        Program._running = True

    def test_connection_made_sets_transport(self):
        proto = DatagramProtocol("h", 5)
        sentinel = object()
        proto.connection_made(sentinel)
        self.assertIs(proto.transport, sentinel)

    def test_connection_lost_without_exc_shuts_down(self):
        DatagramProtocol("h", 5).connection_lost(None)
        self.assertFalse(Program._running)

    def test_connection_lost_with_exc_shuts_down(self):
        DatagramProtocol("h", 5).connection_lost(Exception("boom"))
        self.assertFalse(Program._running)


class TestCreateWriter(TestCase):
    def tearDown(self):
        Config._config = None
        Config._config_is_set = False
        Program._running = True

    def _set_config(self, directory):
        Config.set_config(_writer_config(directory))

    def test_udp_returns_socket(self):
        with tempfile.TemporaryDirectory() as directory:
            self._set_config(directory)
            writer = _net_writer("UDP")
            result = run(writer.create_writer("127.0.0.1", 8888, None))
            self.assertIsInstance(result, socket.socket)
            result.close()

    @patch("duologsync.writer.asyncio.open_connection")
    def test_tcp_success(self, open_conn):
        open_conn.return_value = (MagicMock(), "STREAM")
        with tempfile.TemporaryDirectory() as directory:
            self._set_config(directory)
            writer = _net_writer("TCP")
            result = run(writer.create_writer("127.0.0.1", 8888, None))
            self.assertEqual(result, "STREAM")

    @patch("duologsync.writer.ssl.create_default_context")
    @patch("duologsync.writer.asyncio.open_connection")
    def test_tcpssl_success(self, open_conn, _ctx):
        open_conn.return_value = (MagicMock(), "SSL_STREAM")
        with tempfile.TemporaryDirectory() as directory:
            self._set_config(directory)
            writer = _net_writer("TCPSSL")
            result = run(writer.create_writer("h", 8888, "cert.pem"))
            self.assertEqual(result, "SSL_STREAM")

    @patch("duologsync.writer.ssl.create_default_context", side_effect=FileNotFoundError(2, "no cert", "cert.pem"))
    def test_tcpssl_missing_cert_shuts_down(self, _ctx):
        with tempfile.TemporaryDirectory() as directory:
            self._set_config(directory)
            writer = _net_writer("TCPSSL")
            result = run(writer.create_writer("h", 8888, "cert.pem"))
            self.assertIsNone(result)
            self.assertFalse(Program._running)

    @patch("duologsync.writer.asyncio.open_connection", side_effect=asyncio.TimeoutError)
    def test_tcp_timeout_shuts_down(self, _open):
        with tempfile.TemporaryDirectory() as directory:
            self._set_config(directory)
            writer = _net_writer("TCP")
            result = run(writer.create_writer("h", 8888, None))
            self.assertIsNone(result)
            self.assertFalse(Program._running)

    @patch("duologsync.writer.asyncio.open_connection", side_effect=OSError(111, "refused"))
    def test_tcp_connect_error_shuts_down(self, _open):
        with tempfile.TemporaryDirectory() as directory:
            self._set_config(directory)
            writer = _net_writer("TCP")
            result = run(writer.create_writer("h", 8888, None))
            self.assertIsNone(result)
            self.assertFalse(Program._running)

    def test_file_success_returns_localfilewriter(self):
        with tempfile.TemporaryDirectory() as directory:
            self._set_config(directory)
            writer = _net_writer("FILE")
            result = run(writer.create_writer(None, None, None, str(Path(directory) / "out.log")))
            self.assertIsInstance(result, LocalFileWriter)

    def test_file_invalid_path_shuts_down(self):
        with tempfile.TemporaryDirectory() as directory:
            self._set_config(directory)
            writer = _net_writer("FILE")
            # Pointing at the directory itself -> IsADirectoryError -> shutdown.
            result = run(writer.create_writer(None, None, None, directory))
            self.assertIsNone(result)
            self.assertFalse(Program._running)


class TestCreateTcpWriter(TestCase):
    @patch("duologsync.writer.asyncio.open_connection")
    def test_returns_writer_half(self, open_conn):
        open_conn.return_value = (MagicMock(), "STREAM")
        self.assertEqual(run(Writer.create_tcp_writer("h", 1)), "STREAM")


class TestCreateWriters(TestCase):
    @patch.object(Writer, "create_writer", new=AsyncMock(return_value="STUB"))
    def test_maps_server_id_to_writer(self):
        writers = Writer.create_writers([{"id": "s1", "protocol": "TCP", "hostname": "h", "port": 1}])
        self.assertIn("s1", writers)
        self.assertEqual(writers["s1"].writer, "STUB")


class TestWriterShutdown(TestCase):
    def tearDown(self):
        Program._running = True

    def test_no_writer_returns(self):
        writer = _net_writer("TCP")
        writer.writer = None
        run(writer.shutdown())  # no error

    def test_udp_close_swallows_oserror(self):
        writer = _net_writer("UDP")
        writer.writer = MagicMock()
        writer.writer.close.side_effect = OSError("boom")
        run(writer.shutdown())
        writer.writer.close.assert_called_once()

    def test_file_delegates_shutdown(self):
        writer = _net_writer("FILE")
        writer.writer = AsyncMock()
        run(writer.shutdown())
        writer.writer.shutdown.assert_awaited_once()

    def test_tcp_closes_and_waits(self):
        writer = _net_writer("TCP")
        writer.writer = MagicMock()
        writer.writer.wait_closed = AsyncMock()
        run(writer.shutdown())
        writer.writer.close.assert_called_once()
        writer.writer.wait_closed.assert_awaited_once()

    @patch("duologsync.writer.asyncio.wait_for", side_effect=asyncio.TimeoutError)
    def test_tcp_close_timeout_is_logged(self, _wait):
        writer = _net_writer("TCP")
        writer.writer = MagicMock()
        writer.writer.wait_closed = AsyncMock()
        run(writer.shutdown())  # TimeoutError swallowed with a warning

    def test_tcp_close_oserror_is_logged(self):
        writer = _net_writer("TCP")
        writer.writer = MagicMock()
        writer.writer.close.side_effect = OSError(9, "bad fd")
        run(writer.shutdown())  # OSError swallowed with a warning

    def test_shutdown_writers_awaits_all(self):
        w1, w2 = AsyncMock(), AsyncMock()
        run(Writer.shutdown_writers({"a": w1, "b": w2}))
        w1.shutdown.assert_awaited_once()
        w2.shutdown.assert_awaited_once()


class TestWriterFileWrappers(TestCase):
    def test_write_file_delegates(self):
        writer = _net_writer("FILE")
        writer.writer = AsyncMock()
        run(writer.write(b"x", "auth"))
        writer.writer.write.assert_awaited_once_with(b"x", "auth")

    def test_write_file_none_is_noop(self):
        writer = _net_writer("FILE")
        writer.writer = None
        run(writer.write(b"x", "auth"))  # no error

    def test_register_log_type_file_delegates(self):
        writer = _net_writer("FILE")
        writer.writer = MagicMock()
        writer.register_log_type("auth")
        writer.writer.register_log_type.assert_called_once_with("auth")

    def test_inject_test_data_non_file_raises(self):
        writer = _net_writer("TCP")
        with self.assertRaises(RuntimeError):
            run(writer.inject_test_data("auth", [b"x"]))

    def test_inject_test_data_no_writer_raises(self):
        writer = _net_writer("FILE")
        writer.writer = None
        with self.assertRaises(RuntimeError):
            run(writer.inject_test_data("auth", [b"x"]))

    def test_inject_test_data_file_delegates(self):
        writer = _net_writer("FILE")
        writer.writer = AsyncMock()
        run(writer.inject_test_data("auth", [b"x"]))
        writer.writer.inject_test_data.assert_awaited_once()


class TestLocalFileWriterInject(TestCase):
    def test_disabled_raises(self):
        with tempfile.TemporaryDirectory() as directory:
            writer = _file_writer(directory, enable_test_input=False)
            with self.assertRaises(RuntimeError):
                run(writer.inject_test_data("auth", ["x"]))

    def test_enabled_appends_newline_and_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            writer = _file_writer(directory, enable_test_input=True)
            writer.write = AsyncMock()

            async def scenario():
                await writer.inject_test_data("auth", ["hello"])

            run(scenario())
            writer.write.assert_awaited_once_with(b"hello\n", "auth")


class TestLocalFileWriterWorkerAndReplay(TestCase):
    def tearDown(self):
        Program._running = True

    def test_initialize_log_type_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            writer = _file_writer(directory)
            writer._replay_backlog = AsyncMock()

            async def scenario():
                await writer._initialize_log_type("auth")
                await writer._initialize_log_type("auth")

            run(scenario())
            writer._replay_backlog.assert_awaited_once()

    def test_process_queue_backlogs_failed_write(self):
        with tempfile.TemporaryDirectory() as directory:
            writer = _file_writer(directory)
            writer._write_with_retries = AsyncMock(return_value=(False, True))
            writer._append_backlog = AsyncMock()

            async def scenario():
                writer.queue.put_nowait(("auth", b"x\n"))
                writer.queue.put_nowait(writer._STOP)
                await writer._process_queue()

            run(scenario())
            writer._append_backlog.assert_awaited_once()

    def test_process_queue_logs_item_exception(self):
        with tempfile.TemporaryDirectory() as directory:
            writer = _file_writer(directory)
            writer._write_with_retries = AsyncMock(side_effect=RuntimeError("boom"))

            async def scenario():
                writer.queue.put_nowait(("auth", b"x\n"))
                writer.queue.put_nowait(writer._STOP)
                await writer._process_queue()

            run(scenario())  # exception logged, loop reaches STOP without crashing

    def test_process_queue_outer_crash_shuts_down(self):
        with tempfile.TemporaryDirectory() as directory:
            writer = _file_writer(directory)
            crashing = MagicMock()
            crashing.get = AsyncMock(side_effect=RuntimeError("queue broke"))
            writer.queue = crashing
            run(writer._process_queue())
            self.assertFalse(Program._running)

    def test_replay_backlog_file_partial_failure_preserves_remaining(self):
        with tempfile.TemporaryDirectory() as directory:
            writer = _file_writer(directory)
            replay = Path(directory) / "auth_file_failed_ingestion_logs.txt.replay"
            replay.write_bytes(b"line-1\nline-2\n")
            # First write "fails" so replay pauses and re-appends remaining lines.
            writer._write_with_retries = AsyncMock(return_value=(False, True))

            result = run(writer._replay_backlog_file("auth", replay))
            self.assertFalse(result)
            backlog = writer._backlog_path("auth")
            self.assertTrue(backlog.exists())

    def test_replay_backlog_file_read_error_returns_false(self):
        with tempfile.TemporaryDirectory() as directory:
            writer = _file_writer(directory)
            # Passing a directory as the replay path makes open() raise OSError.
            result = run(writer._replay_backlog_file("auth", Path(directory)))
            self.assertFalse(result)


class TestLocalFileWriterRotationEdges(TestCase):
    def test_empty_file_is_not_rotated(self):
        with tempfile.TemporaryDirectory() as directory:
            writer = _file_writer(directory, rotation="size", max_bytes=1)
            writer.filepath.write_bytes(b"")  # zero bytes
            writer._maybe_rotate(10)  # returns early, no exception
            self.assertEqual(list(writer.filepath.parent.glob("out.log.*")), [])

    def test_rotation_check_failure_is_swallowed(self):
        with tempfile.TemporaryDirectory() as directory:
            writer = _file_writer(directory, rotation="size", max_bytes=1)
            writer.filepath.write_bytes(b"data")
            with patch.object(type(writer.filepath), "stat", side_effect=OSError("stat failed")):
                writer._maybe_rotate(10)  # WARNING logged, swallowed

    def test_prune_backups_none_count_returns(self):
        with tempfile.TemporaryDirectory() as directory:
            writer = _file_writer(directory)
            writer.backup_count = None
            writer._prune_backups()  # no error

    def test_prune_backups_swallows_unlink_error(self):
        with tempfile.TemporaryDirectory() as directory:
            writer = _file_writer(directory, backup_count=0)
            for i in range(2):
                (writer.filepath.parent / f"out.log.2020-01-0{i}_000000").write_bytes(b"old")
            with patch.object(Path, "unlink", side_effect=OSError("nope")):
                writer._prune_backups()  # swallowed

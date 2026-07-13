"""
Tests for the asynchronous LocalFileWriter pipeline: end-to-end write via the
queue/worker, the retry-with-backoff path, disk-full detection triggering
shutdown, and crash-safe backlog replay on startup.

Async is driven with a fresh event loop per test (no pytest-asyncio needed);
the writer is constructed inside the coroutine so its Queue/Locks bind to the
running loop across Python 3.8-3.13.
"""

import asyncio
import errno
import tempfile
from pathlib import Path
from unittest import TestCase

from duologsync.program import Program
from duologsync.writer import LocalFileWriter


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _writer(directory, **overrides):
    params = {
        "filepath": str(Path(directory) / "out.log"),
        "checkpoint_directory": directory,
        "queue_max_size": 100,
        "max_retries": 3,
        "retry_backoff_seconds": 0,
        "enable_test_input": False,
        "rotation": "none",
    }
    params.update(overrides)
    return LocalFileWriter(**params)


class TestLocalFileWriterAsync(TestCase):
    def tearDown(self):
        Program._running = True

    def test_end_to_end_write_and_shutdown(self):
        with tempfile.TemporaryDirectory() as directory:

            async def scenario():
                writer = _writer(directory)
                writer.register_log_type("auth")
                await writer.start()
                for index in range(5):
                    await writer.write(f"log-{index}\n".encode("utf-8"), "auth")
                await writer.shutdown()
                return writer.filepath

            filepath = run(scenario())
            self.assertEqual(filepath.read_bytes().count(b"\n"), 5)

    def test_write_retries_then_succeeds(self):
        with tempfile.TemporaryDirectory() as directory:

            async def scenario():
                writer = _writer(directory, max_retries=3)
                state = {"attempts": 0}

                def flaky(data):
                    state["attempts"] += 1
                    if state["attempts"] < 3:
                        raise OSError(errno.EIO, "I/O error")
                    with open(writer.filepath, "ab") as handle:
                        handle.write(data)

                writer._write_to_file = flaky
                ok, should_backlog = await writer._write_with_retries(b"x\n", "auth")
                return ok, should_backlog, state["attempts"], writer.filepath.read_bytes()

            ok, should_backlog, attempts, contents = run(scenario())
            self.assertTrue(ok)
            self.assertFalse(should_backlog)
            self.assertEqual(attempts, 3)
            self.assertEqual(contents, b"x\n")

    def test_write_exhausts_retries_and_requests_backlog(self):
        with tempfile.TemporaryDirectory() as directory:

            async def scenario():
                writer = _writer(directory, max_retries=2)

                def always_fail(data):
                    raise OSError(errno.EIO, "I/O error")

                writer._write_to_file = always_fail
                return await writer._write_with_retries(b"x\n", "auth")

            ok, should_backlog = run(scenario())
            self.assertFalse(ok)
            # Non-disk-full failures should be spilled to the backlog.
            self.assertTrue(should_backlog)

    def test_disk_full_triggers_shutdown(self):
        with tempfile.TemporaryDirectory() as directory:

            async def scenario():
                writer = _writer(directory)

                def no_space(data):
                    raise OSError(errno.ENOSPC, "No space left on device")

                writer._write_to_file = no_space
                return await writer._write_with_retries(b"x\n", "auth")

            ok, should_backlog = run(scenario())
            self.assertFalse(ok)
            # Disk-full must NOT backlog (there's no space) — it shuts down.
            self.assertFalse(should_backlog)
            self.assertFalse(Program.is_running())

    def test_backlog_is_replayed_on_startup(self):
        with tempfile.TemporaryDirectory() as directory:
            backlog = Path(directory) / "auth_file_failed_ingestion_logs.txt"
            backlog.write_bytes(b"replayed-1\nreplayed-2\n")

            async def scenario():
                writer = _writer(directory)
                await writer._replay_backlog("auth")
                return writer.filepath, backlog

            filepath, backlog_path = run(scenario())
            self.assertEqual(filepath.read_bytes(), b"replayed-1\nreplayed-2\n")
            self.assertFalse(backlog_path.exists())
            self.assertFalse(Path(f"{backlog_path}.replay").exists())

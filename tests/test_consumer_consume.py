"""
Unit tests for Consumer.consume() (the queue→write→checkpoint loop and its
error/branch paths) and the update_log_checkpoint file writer.
"""

import asyncio
import json
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import AsyncMock, patch

from duologsync.config import Config
from duologsync.consumer.consumer import Consumer
from duologsync.program import Program


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _FakeQueue:
    def __init__(self, items):
        self._items = items
        self.get_calls = 0

    async def get(self):
        self.get_calls += 1
        return self._items


def _consumer(items, writer):
    consumer = Consumer(Config.JSON, _FakeQueue(items), writer)
    consumer.log_type = "auth"
    return consumer


class TestConsume(TestCase):
    def tearDown(self):
        Program._running = True

    @patch("duologsync.consumer.consumer.Consumer.update_log_checkpoint")
    @patch("duologsync.consumer.consumer.Producer.get_log_offset", return_value="off")
    @patch("duologsync.consumer.consumer.Program.is_running", side_effect=[True, True, False])
    def test_happy_path_writes_and_checkpoints(self, _running, _offset, checkpoint):
        writer = AsyncMock()
        consumer = _consumer([{"a": 1}, {"b": 2}], writer)
        run(consumer.consume())
        self.assertEqual(writer.write.await_count, 2)
        checkpoint.assert_called_once_with("auth", "off", None)

    @patch("duologsync.consumer.consumer.Consumer.update_log_checkpoint")
    @patch("duologsync.consumer.consumer.Producer.get_log_offset", return_value="off")
    @patch("duologsync.consumer.consumer.Program.is_running", side_effect=[True, True, False])
    def test_empty_logs_skips_write_and_checkpoint(self, _running, _offset, checkpoint):
        writer = AsyncMock()
        consumer = _consumer([], writer)
        run(consumer.consume())
        writer.write.assert_not_awaited()
        checkpoint.assert_not_called()

    @patch("duologsync.consumer.consumer.Consumer.update_log_checkpoint")
    @patch("duologsync.consumer.consumer.Producer.get_log_offset", return_value="off")
    @patch("duologsync.consumer.consumer.Program.is_running", side_effect=[True, True, False])
    def test_oserror_triggers_shutdown(self, _running, _offset, _checkpoint):
        writer = AsyncMock()
        writer.write.side_effect = OSError(32, "Broken pipe")
        consumer = _consumer([{"a": 1}], writer)
        run(consumer.consume())
        # The real Program.initiate_shutdown flips the class-level running flag.
        self.assertFalse(Program._running)
        # The write was attempted once before the OSError propagated.
        self.assertEqual(writer.write.await_count, 1)

    @patch("duologsync.consumer.consumer.Program.is_running", side_effect=[True, False, False])
    def test_shutdown_after_get_continues(self, _running):
        writer = AsyncMock()
        consumer = _consumer([{"a": 1}], writer)
        run(consumer.consume())
        writer.write.assert_not_awaited()


class TestUpdateLogCheckpoint(TestCase):
    def test_writes_offset_without_child_account(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch(
                "duologsync.consumer.consumer.Config.get_checkpoint_dir",
                return_value=directory,
            ):
                Consumer.update_log_checkpoint("auth", 12345, None)
                # Second call exercises the os.path.exists()==True log branch.
                Consumer.update_log_checkpoint("auth", 67890, None)

            checkpoint = Path(directory) / "auth_checkpoint_data.txt"
            self.assertEqual(checkpoint.read_text(), json.dumps(67890) + "\n")

    def test_writes_offset_with_child_account(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch(
                "duologsync.consumer.consumer.Config.get_checkpoint_dir",
                return_value=directory,
            ):
                Consumer.update_log_checkpoint("auth", 999, "child7")

            checkpoint = Path(directory) / "auth_checkpoint_data_child7.txt"
            self.assertEqual(checkpoint.read_text(), json.dumps(999) + "\n")

"""
Tests for LocalFileWriter log rotation (size, time, retention, and the
no-rotation fast path). These exercise the synchronous rotation helpers
directly, without spinning up the asyncio pipeline.
"""

import os
import tempfile
import time
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

from duologsync.writer import LocalFileWriter


def _make_writer(directory, **overrides):
    params = {
        "filepath": str(Path(directory) / "out.log"),
        "checkpoint_directory": str(directory),
        "queue_max_size": 100,
        "max_retries": 0,
        "retry_backoff_seconds": 0,
        "enable_test_input": False,
    }
    params.update(overrides)
    return LocalFileWriter(**params)


def _record(index):
    # 21 bytes per record including the trailing newline.
    return f"log-entry-{index:08d}\n".encode("utf-8")


def _rotated_files(writer):
    pattern = f"{writer.filepath.name}.*"
    return sorted(path for path in writer.filepath.parent.glob(pattern) if path.is_file())


class TestLocalFileWriterRotation(unittest.TestCase):
    def test_no_rotation_keeps_single_file(self):
        with tempfile.TemporaryDirectory() as directory:
            writer = _make_writer(directory, rotation="none", max_bytes=10)
            for index in range(20):
                writer._write_to_file(_record(index))

            self.assertTrue(writer.filepath.exists())
            self.assertEqual(_rotated_files(writer), [])
            self.assertEqual(writer.filepath.read_bytes().count(b"\n"), 20)

    def test_size_rotation_preserves_all_data(self):
        with tempfile.TemporaryDirectory() as directory:
            # Large backup_count so nothing is pruned -> all data retained.
            writer = _make_writer(directory, rotation="size", max_bytes=10, backup_count=100)
            total = 25
            for index in range(total):
                writer._write_to_file(_record(index))

            self.assertTrue(writer.filepath.exists())
            self.assertGreater(len(_rotated_files(writer)), 0)

            # Sum of newlines across the active file + every rotated file must
            # equal the number of records written (no loss across rotations).
            newlines = writer.filepath.read_bytes().count(b"\n")
            for rotated in _rotated_files(writer):
                newlines += rotated.read_bytes().count(b"\n")
            self.assertEqual(newlines, total)

    def test_backup_count_prunes_oldest(self):
        with tempfile.TemporaryDirectory() as directory:
            writer = _make_writer(directory, rotation="size", max_bytes=10, backup_count=3)
            for index in range(30):
                writer._write_to_file(_record(index))

            rotated = _rotated_files(writer)
            # Never retain more than backup_count rotated files.
            self.assertLessEqual(len(rotated), 3)
            self.assertEqual(len(rotated), 3)

    def test_backup_count_zero_deletes_all_rotated(self):
        with tempfile.TemporaryDirectory() as directory:
            writer = _make_writer(directory, rotation="size", max_bytes=10, backup_count=0)
            for index in range(10):
                writer._write_to_file(_record(index))

            self.assertEqual(_rotated_files(writer), [])
            self.assertTrue(writer.filepath.exists())

    def test_empty_file_is_not_rotated(self):
        with tempfile.TemporaryDirectory() as directory:
            writer = _make_writer(directory, rotation="size", max_bytes=1, backup_count=5)
            # First write into an empty/absent file must not rotate.
            writer._write_to_file(_record(0))
            self.assertEqual(_rotated_files(writer), [])

    def test_time_rotation_on_day_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            writer = _make_writer(directory, rotation="time", backup_count=5)
            # Seed a non-empty file dated yesterday.
            writer._append_bytes(_record(0))
            yesterday = datetime.now() - timedelta(days=1)
            past = time.mktime(yesterday.timetuple())
            os.utime(writer.filepath, (past, past))

            # Next write should trigger a time-based rotation.
            writer._write_to_file(_record(1))

            rotated = _rotated_files(writer)
            self.assertEqual(len(rotated), 1)
            # Yesterday's single record rotated out; today's record is active.
            self.assertEqual(rotated[0].read_bytes().count(b"\n"), 1)
            self.assertEqual(writer.filepath.read_bytes().count(b"\n"), 1)

    def test_time_rotation_same_day_does_not_rotate(self):
        with tempfile.TemporaryDirectory() as directory:
            writer = _make_writer(directory, rotation="time", backup_count=5)
            writer._write_to_file(_record(0))
            writer._write_to_file(_record(1))
            # Same-day writes stay in one file.
            self.assertEqual(_rotated_files(writer), [])
            self.assertEqual(writer.filepath.read_bytes().count(b"\n"), 2)


if __name__ == "__main__":
    unittest.main()

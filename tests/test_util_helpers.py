"""
Unit tests for the remaining duologsync.util helpers: restless_sleep,
run_in_executor, create_admin, normalize_params, and the get_log_offset
checkpoint-success path.
"""

import asyncio
import json
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from duologsync.config import Config
from duologsync.program import Program, ProgramShutdownError
from duologsync.util import (
    create_admin,
    get_log_offset,
    normalize_params,
    restless_sleep,
    run_in_executor,
)


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestRestlessSleep(TestCase):
    def tearDown(self):
        Program._running = True

    def test_completes_while_running(self):
        Program._running = True
        with patch("duologsync.util.asyncio.sleep", new=_async_noop):
            # duration=1 -> one mocked sleep, still running, returns None.
            self.assertIsNone(run(restless_sleep(1)))

    def test_raises_when_shutting_down(self):
        Program._running = False
        with patch("duologsync.util.asyncio.sleep", new=_async_noop):
            with self.assertRaises(ProgramShutdownError):
                run(restless_sleep(5))


async def _async_noop(*_args, **_kwargs):
    return None


class TestRunInExecutor(TestCase):
    def test_runs_callable_and_returns_result(self):
        self.assertEqual(run(run_in_executor(lambda: 42)), 42)


class TestCreateAdmin(TestCase):
    @patch("duologsync.util.duo_client.Accounts")
    @patch("duologsync.util.duo_client.Admin")
    def test_non_msp_uses_admin(self, admin_cls, accounts_cls):
        create_admin("ikey", "skey", "api.example.com")
        admin_cls.assert_called_once()
        accounts_cls.assert_not_called()
        _, kwargs = admin_cls.call_args
        self.assertEqual(kwargs["ikey"], "ikey")
        self.assertEqual(kwargs["host"], "api.example.com")

    @patch("duologsync.util.duo_client.Accounts")
    @patch("duologsync.util.duo_client.Admin")
    def test_msp_uses_accounts(self, admin_cls, accounts_cls):
        create_admin("ikey", "skey", "api.example.com", is_msp=True)
        accounts_cls.assert_called_once()
        admin_cls.assert_not_called()

    @patch("duologsync.util.duo_client.Admin")
    def test_proxy_is_configured_when_both_set(self, admin_cls):
        admin = create_admin("i", "s", "h", proxy_server="proxy", proxy_port=8080)
        admin.set_proxy.assert_called_once_with(host="proxy", port=8080)

    @patch("duologsync.util.duo_client.Admin")
    def test_proxy_not_configured_when_missing(self, admin_cls):
        admin = create_admin("i", "s", "h", proxy_server="proxy", proxy_port=None)
        admin.set_proxy.assert_not_called()


class TestNormalizeParams(TestCase):
    def test_string_value_becomes_encoded_list(self):
        self.assertEqual(normalize_params({"a": "x"}), {b"a": [b"x"]})

    def test_none_value_becomes_single_none_list(self):
        self.assertEqual(normalize_params({"b": None}), {b"b": [None]})

    def test_list_values_are_encoded_elementwise(self):
        self.assertEqual(normalize_params({"c": ["y", "z"]}), {b"c": [b"y", b"z"]})


class TestGetLogOffsetSuccess(TestCase):
    def tearDown(self):
        Config._config = None
        Config._config_is_set = False
        Program._running = True

    def setUp(self):
        Config.set_config({"dls_settings": {"api": {"offset": 1000}}})

    def test_reads_offset_from_checkpoint_file(self):
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "auth_checkpoint_data.txt"
            checkpoint.write_text(json.dumps(123456789))
            offset = get_log_offset("auth", recover_log_offset=True, checkpoint_directory=directory)
            self.assertEqual(offset, 123456789)

    def test_reads_child_account_checkpoint_file(self):
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "auth_checkpoint_data_child42.txt"
            checkpoint.write_text(json.dumps([1000, "txid"]))
            offset = get_log_offset(
                "auth",
                recover_log_offset=True,
                checkpoint_directory=directory,
                child_account_id="child42",
            )
            self.assertEqual(offset, [1000, "txid"])

    def test_missing_checkpoint_falls_back_to_api_offset(self):
        with tempfile.TemporaryDirectory() as directory:
            # No file present -> OSError path -> returns the (scaled) api offset.
            offset = get_log_offset("auth", recover_log_offset=True, checkpoint_directory=directory)
            # auth is millisecond-based: 1000 * 1000.
            self.assertEqual(offset, 1000 * 1000)

    def test_non_recover_returns_scaled_offset(self):
        offset = get_log_offset("auth", recover_log_offset=False, checkpoint_directory="/nonexistent")
        self.assertEqual(offset, 1000 * 1000)

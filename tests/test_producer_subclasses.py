"""
Unit tests for the producer subclasses: offset handling in __init__ and the
parameters each call_log_api builds. run_in_executor is patched to invoke the
functools.partial synchronously so the recorded api_call kwargs can be asserted
without touching a real Duo Admin client or thread pool.
"""

import asyncio
from unittest import TestCase
from unittest.mock import MagicMock, patch

from duologsync.config import Config
from duologsync.producer.activity_producer import ActivityProducer
from duologsync.producer.authlog_producer import AuthlogProducer
from duologsync.producer.telephony_producer import TelephonyProducer
from duologsync.producer.trustmonitor_producer import TrustMonitorProducer


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _invoke(partial):
    # Stand-in for run_in_executor: call the partial synchronously.
    return partial()


class _ProducerTestBase(TestCase):
    def setUp(self):
        Config.set_config(
            {
                "dls_settings": {
                    "checkpointing": {"enabled": False, "directory": "/tmp"},
                    "api": {"offset": 100},
                },
                "account": {"is_msp": False},
            }
        )

    def tearDown(self):
        Config._config = None
        Config._config_is_set = False


class TestAuthlogProducer(_ProducerTestBase):
    def test_int_offset_sets_mintime(self):
        producer = AuthlogProducer(MagicMock(), None)
        # api offset 100 * 1000 (auth is millisecond-based) -> int -> mintime.
        self.assertEqual(producer.mintime, 100000)
        self.assertIsNone(producer.log_offset)

    @patch("duologsync.producer.producer.get_log_offset", return_value=(1, 2))
    def test_tuple_offset_keeps_log_offset(self, _offset):
        producer = AuthlogProducer(MagicMock(), None)
        self.assertIsNone(producer.mintime)
        self.assertEqual(producer.log_offset, (1, 2))

    @patch("duologsync.producer.authlog_producer.run_in_executor", _invoke)
    def test_call_log_api_non_msp(self):
        api_call = MagicMock(return_value="RESULT")
        producer = AuthlogProducer(api_call, None)
        result = run(producer.call_log_api())
        self.assertEqual(result, "RESULT")
        kwargs = api_call.call_args.kwargs
        self.assertEqual(kwargs["api_version"], 2)
        self.assertEqual(kwargs["sort"], "ts:asc")
        self.assertEqual(kwargs["limit"], "1000")

    @patch("duologsync.producer.authlog_producer.run_in_executor", _invoke)
    @patch("duologsync.producer.authlog_producer.Config.account_is_msp", return_value=True)
    def test_call_log_api_msp(self, _msp):
        api_call = MagicMock(return_value="RESULT")
        producer = AuthlogProducer(api_call, None, child_account_id="child9", url_path="/admin/v2/logs/authentication")
        run(producer.call_log_api())
        kwargs = api_call.call_args.kwargs
        self.assertEqual(kwargs["method"], "GET")
        self.assertEqual(kwargs["path"], "/admin/v2/logs/authentication")
        self.assertIn(b"account_id", kwargs["params"])


class TestTelephonyProducer(_ProducerTestBase):
    @patch("duologsync.producer.producer.get_log_offset", return_value="500,txid")
    def test_string_offset_splits_mintime(self, _offset):
        producer = TelephonyProducer(MagicMock(), None)
        self.assertEqual(producer.mintime, 500)
        self.assertIsNone(producer.log_offset)

    @patch("duologsync.producer.telephony_producer.run_in_executor", _invoke)
    def test_call_log_api_builds_params(self):
        api_call = MagicMock(return_value="RESULT")
        producer = TelephonyProducer(api_call, None, url_path="/admin/v2/logs/telephony")
        producer.log_offset = "9999"  # exercise the next_offset branch
        run(producer.call_log_api())
        params = api_call.call_args.kwargs["params"]
        self.assertIn(b"mintime", params)
        self.assertIn(b"maxtime", params)
        # next_offset is added after normalize_params, so it is a plain str key.
        self.assertIn("next_offset", params)


class TestActivityProducer(_ProducerTestBase):
    @patch("duologsync.producer.activity_producer.run_in_executor", _invoke)
    def test_call_log_api_builds_params(self):
        api_call = MagicMock(return_value="RESULT")
        producer = ActivityProducer(api_call, None, url_path="/admin/v2/logs/activity")
        run(producer.call_log_api())
        params = api_call.call_args.kwargs["params"]
        self.assertIn(b"mintime", params)
        self.assertIn(b"maxtime", params)
        self.assertTrue(producer.first_pass)  # activity does not consume first_pass


class TestTrustMonitorProducer(_ProducerTestBase):
    @patch("duologsync.producer.trustmonitor_producer.run_in_executor", _invoke)
    def test_first_pass_forces_null_offset(self):
        api_call = MagicMock(return_value="RESULT")
        producer = TrustMonitorProducer(api_call, None)
        self.assertTrue(producer.first_pass)
        run(producer.call_log_api())
        self.assertFalse(producer.first_pass)
        kwargs = api_call.call_args.kwargs
        self.assertIsNone(kwargs["offset"])
        self.assertIn("mintime", kwargs)
        self.assertIn("maxtime", kwargs)

    @patch("duologsync.producer.trustmonitor_producer.run_in_executor", _invoke)
    def test_advance_promotes_offset_to_mintime(self):
        api_call = MagicMock(return_value="RESULT")
        producer = TrustMonitorProducer(api_call, None)
        producer.first_pass = False
        producer.mintime = 100
        producer.log_offset = 200  # greater than mintime -> promote
        run(producer.call_log_api())
        self.assertEqual(producer.mintime, 200)
        self.assertIsNone(producer.log_offset)

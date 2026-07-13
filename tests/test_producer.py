"""
Unit tests for the base Producer: the produce() loop and its exception arms,
add_logs_to_queue unwrapping, the base call_log_api, and the remaining
get_log_offset branches.
"""

import asyncio
import socket
from unittest import TestCase
from unittest.mock import AsyncMock, MagicMock, patch

from duologsync.config import Config
from duologsync.producer.producer import Producer
from duologsync.program import Program, ProgramShutdownError


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _async_noop(*_args, **_kwargs):
    return None


async def _invoke(partial):
    return partial()


def _bare_producer(**attrs):
    producer = Producer.__new__(Producer)
    producer.api_call = attrs.get("api_call", MagicMock())
    producer.log_queue = attrs.get("log_queue", asyncio.Queue())
    producer.log_type = attrs.get("log_type", "auth")
    producer.account_id = attrs.get("account_id", None)
    producer.url_path = attrs.get("url_path", None)
    producer.log_offset = attrs.get("log_offset", 0)
    # produce() logs `self.log_offset or self.mintime`; only subclasses set mintime.
    producer.mintime = attrs.get("mintime", None)
    return producer


class TestProduceLoop(TestCase):
    def tearDown(self):
        Program._running = True

    @patch("duologsync.producer.producer.restless_sleep", new=_async_noop)
    @patch("duologsync.producer.producer.Config.get_api_timeout", return_value=120)
    @patch("duologsync.producer.producer.Program.is_running", side_effect=[True, False])
    def test_happy_iteration_enqueues_logs(self, _running, _timeout):
        producer = _bare_producer()
        producer.call_log_api = AsyncMock(return_value=["log1"])
        producer.get_logs = MagicMock(return_value=["log1"])
        producer.add_logs_to_queue = AsyncMock()
        run(producer.produce())
        producer.add_logs_to_queue.assert_awaited_once_with(["log1"])
        # Terminal sentinel put to unblock the consumer.
        self.assertEqual(producer.log_queue.get_nowait(), [])

    @patch("duologsync.producer.producer.restless_sleep", new=_async_noop)
    @patch("duologsync.producer.producer.Config.get_api_timeout", return_value=120)
    @patch("duologsync.producer.producer.Program.is_running", side_effect=[True, False])
    def test_no_logs_available(self, _running, _timeout):
        producer = _bare_producer()
        producer.call_log_api = AsyncMock(return_value=None)
        producer.add_logs_to_queue = AsyncMock()
        run(producer.produce())
        producer.add_logs_to_queue.assert_not_awaited()

    @patch("duologsync.producer.producer.restless_sleep", new=_async_noop)
    @patch("duologsync.producer.producer.Config.get_api_timeout", return_value=120)
    @patch("duologsync.producer.producer.Program.is_running", side_effect=[True, False])
    def test_gaierror_arm_triggers_shutdown(self, _running, _timeout):
        producer = _bare_producer()
        producer.call_log_api = AsyncMock(side_effect=socket.gaierror(8, "bad host"))
        producer.handle_address_info_error = MagicMock(return_value="reason")
        run(producer.produce())
        producer.handle_address_info_error.assert_called_once()
        self.assertFalse(Program._running)

    @patch("duologsync.producer.producer.restless_sleep", new=_async_noop)
    @patch("duologsync.producer.producer.Config.get_api_timeout", return_value=120)
    @patch("duologsync.producer.producer.Program.is_running", side_effect=[True, False])
    def test_oserror_arm_triggers_shutdown(self, _running, _timeout):
        producer = _bare_producer()
        producer.call_log_api = AsyncMock(side_effect=OSError(5, "io"))
        producer.handle_os_error = MagicMock(return_value="reason")
        run(producer.produce())
        producer.handle_os_error.assert_called_once()
        self.assertFalse(Program._running)

    @patch("duologsync.producer.producer.restless_sleep", new=_async_noop)
    @patch("duologsync.producer.producer.Config.get_api_timeout", return_value=120)
    @patch("duologsync.producer.producer.Program.is_running", side_effect=[True, False])
    def test_runtime_error_arm(self, _running, _timeout):
        producer = _bare_producer()
        producer.call_log_api = AsyncMock(side_effect=RuntimeError("boom"))
        producer.handle_runtime_error_gracefully = MagicMock(return_value="reason")
        run(producer.produce())
        producer.handle_runtime_error_gracefully.assert_called_once()
        self.assertFalse(Program._running)

    @patch("duologsync.producer.producer.Config.get_api_timeout", return_value=120)
    @patch("duologsync.producer.producer.Program.is_running", side_effect=[True, True])
    def test_program_shutdown_error_breaks(self, _running, _timeout):
        producer = _bare_producer()
        with patch(
            "duologsync.producer.producer.restless_sleep",
            side_effect=ProgramShutdownError,
        ):
            run(producer.produce())
        # Loop broke out; terminal sentinel still enqueued.
        self.assertEqual(producer.log_queue.get_nowait(), [])


class TestAddLogsToQueue(TestCase):
    @patch("duologsync.producer.producer.Producer.get_log_offset", return_value="off")
    def test_unwraps_authlogs(self, _offset):
        producer = _bare_producer(log_queue=asyncio.Queue())
        run(producer.add_logs_to_queue({"authlogs": [1, 2]}))
        self.assertEqual(producer.log_queue.get_nowait(), [1, 2])

    @patch("duologsync.producer.producer.Producer.get_log_offset", return_value="off")
    def test_unwraps_events(self, _offset):
        producer = _bare_producer(log_queue=asyncio.Queue())
        run(producer.add_logs_to_queue({"events": [3]}))
        self.assertEqual(producer.log_queue.get_nowait(), [3])

    @patch("duologsync.producer.producer.Producer.get_log_offset", return_value="off")
    def test_unwraps_items(self, _offset):
        producer = _bare_producer(log_queue=asyncio.Queue())
        run(producer.add_logs_to_queue({"items": [4]}))
        self.assertEqual(producer.log_queue.get_nowait(), [4])

    @patch("duologsync.producer.producer.Producer.get_log_offset", return_value="off")
    def test_empty_logs_enqueues_nothing(self, _offset):
        producer = _bare_producer(log_queue=asyncio.Queue())
        run(producer.add_logs_to_queue([]))
        self.assertTrue(producer.log_queue.empty())


class TestCallLogApiBase(TestCase):
    def tearDown(self):
        Config._config = None
        Config._config_is_set = False

    @patch("duologsync.producer.producer.run_in_executor", _invoke)
    @patch("duologsync.producer.producer.Config.account_is_msp", return_value=False)
    def test_non_msp(self, _msp):
        api_call = MagicMock(return_value="R")
        producer = _bare_producer(api_call=api_call, log_offset=123)
        self.assertEqual(run(producer.call_log_api()), "R")
        self.assertEqual(api_call.call_args.kwargs["mintime"], 123)

    @patch("duologsync.producer.producer.run_in_executor", _invoke)
    @patch("duologsync.producer.producer.Config.account_is_msp", return_value=True)
    def test_msp(self, _msp):
        api_call = MagicMock(return_value="R")
        producer = _bare_producer(api_call=api_call, log_offset=5, account_id="acc", url_path="/p")
        run(producer.call_log_api())
        kwargs = api_call.call_args.kwargs
        self.assertEqual(kwargs["method"], "GET")
        self.assertEqual(kwargs["path"], "/p")
        self.assertEqual(kwargs["params"]["account_id"], "acc")


class TestGetLogOffsetBranches(TestCase):
    def test_get_logs_passthrough(self):
        self.assertEqual(Producer.get_logs("x"), "x")

    def test_activity_response_with_next_offset(self):
        log = {"items": [1], "metadata": {"next_offset": "abc"}}
        self.assertEqual(Producer.get_log_offset(log, log_type=Config.ACTIVITY), "abc")

    def test_trustmonitor_events_list_uses_last_surfaced(self):
        log = {"events": [{"surfaced": 100}, {"surfaced": 200}], "metadata": {}}
        self.assertEqual(Producer.get_log_offset(log, log_type=Config.TRUST_MONITOR), 201)

    def test_dict_timestamp_plus_one(self):
        self.assertEqual(Producer.get_log_offset({"timestamp": 50}), 51)

    def test_dict_no_match_returns_current(self):
        self.assertEqual(Producer.get_log_offset({}, current_log_offset="X"), "X")

    def test_non_dict_uses_last_timestamp(self):
        self.assertEqual(Producer.get_log_offset([{"timestamp": 9}]), 10)

"""
Coverage for app.py: signal_handler, main() dispatch, run() branches, and
create_consumer_producer_pair for every endpoint. Producer/consumer classes,
asyncio, and Config are patched so nothing touches a real event loop or API.
"""

import signal
import sys
from unittest import TestCase
from unittest.mock import MagicMock, patch

from duologsync import app
from duologsync.app import create_consumer_producer_pair, main, run, signal_handler
from duologsync.config import Config
from duologsync.program import Program


class TestSignalHandler(TestCase):
    def tearDown(self):
        Program._running = True

    @patch("duologsync.app.Program")
    def test_sigint(self, program):
        signal_handler(signal.SIGINT, None)
        reason = program.initiate_shutdown.call_args.args[0]
        self.assertIn("Ctrl-C", reason)
        program.log.assert_not_called()

    @patch("duologsync.app.Program")
    def test_sigterm_with_stack_frame(self, program):
        signal_handler(signal.SIGTERM, "frame")
        program.initiate_shutdown.assert_called_once()
        program.log.assert_called_once()


class TestMain(TestCase):
    @patch("duologsync.app._validate_and_exit")
    def test_validate_branch(self, validate):
        with patch.object(sys, "argv", ["duologsync", "cfg.yml", "--validate"]):
            main()
        validate.assert_called_once_with("cfg.yml")

    @patch("duologsync.app.run")
    @patch("duologsync.app.signal.signal")
    def test_normal_branch(self, _signal, run_mock):
        with patch.object(sys, "argv", ["duologsync", "cfg.yml"]):
            main()
        run_mock.assert_called_once_with("cfg.yml")


class TestValidateAndExit(TestCase):
    @patch("duologsync.app.Config.validate_config", return_value=([], ["low timeout"]))
    def test_warnings_only_exits_zero(self, _validate):
        with self.assertRaises(SystemExit) as ctx:
            app._validate_and_exit("cfg.yml")
        self.assertEqual(ctx.exception.code, 0)


class TestRun(TestCase):
    @patch("duologsync.app.Writer")
    @patch("duologsync.app.Program")
    @patch("duologsync.app.check_for_specific_endpoint", return_value=True)
    @patch("duologsync.app.Config")
    def test_dtm_non_json_early_return(self, config, _dtm, _program, writer):
        config.create_config.return_value = {}
        config.get_log_format.return_value = "CEF"
        config.account_is_msp.return_value = False
        run("cfg.yml")
        writer.create_writers.assert_not_called()

    @patch("duologsync.app.Writer")
    @patch("duologsync.app.Program")
    @patch("duologsync.app.check_for_specific_endpoint", return_value=True)
    @patch("duologsync.app.Config")
    def test_dtm_msp_early_return(self, config, _dtm, _program, writer):
        config.create_config.return_value = {}
        config.get_log_format.return_value = "JSON"
        config.account_is_msp.return_value = True
        run("cfg.yml")
        writer.create_writers.assert_not_called()

    @patch("duologsync.app.asyncio")
    @patch("duologsync.app.create_tasks", return_value=[])
    @patch("duologsync.app.Writer")
    @patch("duologsync.app.Program")
    @patch("duologsync.app.check_for_specific_endpoint", return_value=False)
    @patch("duologsync.app.Config")
    def test_full_path_runs_event_loop(self, config, _dtm, program, writer, create_tasks, _asyncio):
        config.create_config.return_value = {}
        config.get_log_format.return_value = "JSON"
        config.account_is_msp.return_value = False
        config.get_servers.return_value = []
        program.is_logging_set.return_value = False
        run("cfg.yml")
        writer.create_writers.assert_called_once()
        create_tasks.assert_called_once()
        _asyncio.get_event_loop.return_value.run_until_complete.assert_called()


class TestCreateConsumerProducerPair(TestCase):
    def setUp(self):
        Config.set_config({"dls_settings": {"log_format": "JSON"}, "account": {"is_msp": False}})

    def tearDown(self):
        Config._config = None
        Config._config_is_set = False

    @patch("duologsync.app.asyncio.ensure_future", return_value="TASK")
    @patch("duologsync.app.AuthlogConsumer")
    @patch("duologsync.app.AuthlogProducer")
    def test_auth_non_msp(self, producer, consumer, _ensure):
        writer = MagicMock()
        tasks = create_consumer_producer_pair(Config.AUTH, writer, MagicMock())
        producer.assert_called_once()
        consumer.assert_called_once()
        self.assertEqual(tasks, ["TASK", "TASK"])
        writer.register_log_type.assert_called_once_with(Config.AUTH)

    @patch("duologsync.app.asyncio.ensure_future", return_value="TASK")
    @patch("duologsync.app.AuthlogConsumer")
    @patch("duologsync.app.AuthlogProducer")
    @patch("duologsync.app.Config.account_is_msp", return_value=True)
    def test_auth_msp_uses_json_api(self, _msp, producer, _consumer, _ensure):
        create_consumer_producer_pair(Config.AUTH, MagicMock(), MagicMock(), child_account="c1")
        self.assertEqual(producer.call_args.kwargs["url_path"], "/admin/v2/logs/authentication")

    @patch("duologsync.app.asyncio.ensure_future", return_value="TASK")
    @patch("duologsync.app.TelephonyConsumer")
    @patch("duologsync.app.TelephonyProducer")
    def test_telephony(self, producer, consumer, _ensure):
        tasks = create_consumer_producer_pair(Config.TELEPHONY, MagicMock(), MagicMock())
        producer.assert_called_once()
        self.assertEqual(len(tasks), 2)

    @patch("duologsync.app.asyncio.ensure_future", return_value="TASK")
    @patch("duologsync.app.TrustMonitorConsumer")
    @patch("duologsync.app.TrustMonitorProducer")
    def test_trustmonitor(self, producer, _consumer, _ensure):
        tasks = create_consumer_producer_pair(Config.TRUST_MONITOR, MagicMock(), MagicMock())
        producer.assert_called_once()
        self.assertEqual(len(tasks), 2)

    @patch("duologsync.app.asyncio.ensure_future", return_value="TASK")
    @patch("duologsync.app.ActivityConsumer")
    @patch("duologsync.app.ActivityProducer")
    def test_activity(self, producer, _consumer, _ensure):
        tasks = create_consumer_producer_pair(Config.ACTIVITY, MagicMock(), MagicMock())
        producer.assert_called_once()
        self.assertEqual(len(tasks), 2)

    def test_unrecognized_endpoint_returns_empty(self):
        tasks = create_consumer_producer_pair("bogus", MagicMock(), MagicMock())
        self.assertEqual(tasks, [])

    @patch("duologsync.app.asyncio.ensure_future", return_value="TASK")
    @patch("duologsync.app.TelephonyConsumer")
    @patch("duologsync.app.TelephonyProducer")
    def test_writer_without_register_log_type(self, _producer, _consumer, _ensure):
        # A plain object has no register_log_type attribute -> hasattr False branch.
        tasks = create_consumer_producer_pair(Config.TELEPHONY, object(), MagicMock())
        self.assertEqual(len(tasks), 2)

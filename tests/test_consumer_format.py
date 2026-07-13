"""
Unit tests for Consumer.format_log — the JSON / CEF formatting and the
unsupported-format guard. These are pure formatting paths that require no
network, queue, or Config singleton.
"""

from unittest import TestCase

from duologsync.config import Config
from duologsync.consumer.consumer import Consumer


def _consumer(log_format):
    return Consumer(log_format=log_format, log_queue=None, writer=None)


class TestFormatLog(TestCase):
    def test_json_format_returns_encoded_newline_terminated_bytes(self):
        consumer = _consumer(Config.JSON)
        result = consumer.format_log({"event": 1, "type": "auth"})
        self.assertIsInstance(result, bytes)
        self.assertTrue(result.endswith(b"\n"))
        self.assertEqual(result, b'{"event": 1, "type": "auth"}\n')

    def test_cef_format_produces_cef_header(self):
        consumer = _consumer(Config.CEF)
        consumer.log_type = Config.AUTH
        consumer.keys_to_labels = {("eventtype",): {"name": "cat", "is_custom": False}}

        result = consumer.format_log({"eventtype": "login"}).decode("utf-8")
        self.assertIn("CEF:0|Duo Security|DuoLogSync|", result)
        # signature_id and name both derive from eventtype for non-activity logs.
        self.assertIn("|login|login|", result)
        self.assertIn("cat=login", result)

    def test_cef_bytes_are_newline_terminated(self):
        consumer = _consumer(Config.CEF)
        consumer.log_type = Config.AUTH
        result = consumer.format_log({"eventtype": "login"})
        self.assertTrue(result.endswith(b"\n"))

    def test_unsupported_format_raises_value_error(self):
        consumer = _consumer("XML")
        with self.assertRaises(ValueError):
            consumer.format_log({"event": 1})

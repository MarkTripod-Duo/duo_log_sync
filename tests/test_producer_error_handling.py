"""
Unit tests for Producer error/retry helpers: eligible_for_retry (the
retry-on-429 gate), handle_os_error, handle_address_info_error, and
handle_runtime_error_gracefully. Producer.__new__ is used to exercise these
pure methods without the network-touching __init__.
"""

import socket
from unittest import TestCase

from duologsync.config import Config
from duologsync.producer.producer import Producer
from duologsync.program import Program


def _producer(log_type="auth"):
    producer = Producer.__new__(Producer)
    producer.log_type = log_type
    return producer


class TestEligibleForRetry(TestCase):
    def test_429_is_eligible(self):
        # GRACEFUL_RETRY_STATUS_CODES contains 429 (TOO_MANY_REQUESTS).
        self.assertTrue(Producer.eligible_for_retry(429))

    def test_other_codes_not_eligible(self):
        self.assertFalse(Producer.eligible_for_retry(500))
        self.assertFalse(Producer.eligible_for_retry(200))

    def test_none_not_eligible(self):
        self.assertFalse(Producer.eligible_for_retry(None))


class TestHandleOsError(TestCase):
    def test_includes_message_code_and_filename(self):
        producer = _producer("auth")
        message = producer.handle_os_error(FileNotFoundError(28, "No space left on device", "/var/log/x"))
        self.assertIn("No space left on device", message)
        self.assertIn("error_code: 28", message)
        self.assertIn("file_name: /var/log/x", message)
        self.assertTrue(message.startswith("auth producer:"))


class TestHandleAddressInfoError(TestCase):
    def setUp(self):
        Config.set_config({"config_file_path": "/etc/duologsync/config.yml"})

    def tearDown(self):
        Config._config = None
        Config._config_is_set = False

    def test_returns_message_with_code(self):
        producer = _producer("telephony")
        message = producer.handle_address_info_error(socket.gaierror(8, "nodename nor servname provided"))
        self.assertIn("nodename nor servname provided", message)
        self.assertIn("error_code: 8", message)
        self.assertTrue(message.startswith("telephony producer:"))


class TestHandleRuntimeErrorGracefully(TestCase):
    def tearDown(self):
        Program._running = True

    def _runtime_error(self, status, code=40000):
        error = RuntimeError("api failure")
        error.status = status
        error.data = {"code": code}
        return error

    def test_retryable_status_returns_none(self):
        producer = _producer("auth")
        result = producer.handle_runtime_error_gracefully(self._runtime_error(429))
        # None signals "retry", not "shut down".
        self.assertIsNone(result)

    def test_non_retryable_status_returns_shutdown_reason(self):
        producer = _producer("auth")
        result = producer.handle_runtime_error_gracefully(self._runtime_error(500))
        self.assertIsNotNone(result)
        self.assertIn("http_status_code: 500", result)
        self.assertIn("error_code: 40000", result)

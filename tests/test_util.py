"""
Unit tests for duologsync.util helpers: extract_error_info (the shared error
helper used across writer/consumer/producer), check_for_specific_endpoint,
and store_failed_udp_ingestion_logs.
"""

import socket
import tempfile
from pathlib import Path
from unittest import TestCase

from duologsync.util import (
    check_for_specific_endpoint,
    extract_error_info,
    store_failed_udp_ingestion_logs,
)


class TestExtractErrorInfo(TestCase):
    def test_oserror_with_errno_and_strerror(self):
        info = extract_error_info(OSError(32, "Broken pipe"))
        self.assertEqual(info["error_code"], 32)
        self.assertEqual(info["error_message"], "Broken pipe")

    def test_gaierror_is_supported(self):
        # socket.gaierror is an OSError subclass carrying errno/strerror.
        info = extract_error_info(socket.gaierror(8, "nodename nor servname provided"))
        self.assertEqual(info["error_code"], 8)
        self.assertEqual(info["error_message"], "nodename nor servname provided")

    def test_falls_back_to_two_arg_tuple(self):
        # A bare Exception has no errno/strerror; two args map to code+message.
        info = extract_error_info(Exception(42, "custom failure"))
        self.assertEqual(info["error_code"], 42)
        self.assertEqual(info["error_message"], "custom failure")

    def test_falls_back_to_single_arg_message(self):
        info = extract_error_info(Exception("just a message"))
        self.assertIsNone(info["error_code"])
        self.assertEqual(info["error_message"], "just a message")

    def test_no_args_yields_none(self):
        info = extract_error_info(Exception())
        self.assertIsNone(info["error_code"])
        self.assertIsNone(info["error_message"])

    def test_extra_attrs_are_included(self):
        # OSError(errno, strerror, filename) populates the .filename attribute.
        error = FileNotFoundError(2, "No such file or directory", "/tmp/missing.pem")
        info = extract_error_info(error, "filename")
        self.assertEqual(info["error_code"], 2)
        self.assertEqual(info["error_message"], "No such file or directory")
        self.assertEqual(info["filename"], "/tmp/missing.pem")

    def test_missing_extra_attr_is_none(self):
        info = extract_error_info(OSError(1, "op not permitted"), "filename")
        self.assertIsNone(info["filename"])


class TestCheckForSpecificEndpoint(TestCase):
    @staticmethod
    def _config(*endpoint_lists):
        return {"account": {"endpoint_server_mappings": [{"endpoints": list(e)} for e in endpoint_lists]}}

    def test_endpoint_present(self):
        config = self._config(["auth", "telephony"], ["activity"])
        self.assertTrue(check_for_specific_endpoint("auth", config))
        self.assertTrue(check_for_specific_endpoint("activity", config))

    def test_endpoint_absent(self):
        config = self._config(["auth"])
        self.assertFalse(check_for_specific_endpoint("trustmonitor", config))

    def test_no_mappings(self):
        self.assertFalse(check_for_specific_endpoint("auth", {"account": {}}))
        self.assertFalse(check_for_specific_endpoint("auth", {}))


class TestStoreFailedUdpIngestionLogs(TestCase):
    def test_appends_decoded_payload_to_backlog_file(self):
        with tempfile.TemporaryDirectory() as directory:
            store_failed_udp_ingestion_logs("auth", directory, b'{"event": 1}\n')
            store_failed_udp_ingestion_logs("auth", directory, b'{"event": 2}\n')

            backlog = Path(directory) / "auth_udp_failed_ingestion_logs.txt"
            self.assertTrue(backlog.exists())
            self.assertEqual(
                backlog.read_text(),
                '{"event": 1}\n{"event": 2}\n',
            )

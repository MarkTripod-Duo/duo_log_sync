from unittest import TestCase

from duologsync.config import Config
from duologsync.consumer.cef import _construct_extension, log_to_cef


class TestLogToCef(TestCase):
    def test_auth_log_header_and_extension(self):
        keys_to_labels = {
            ("eventtype",): {"name": "cat", "is_custom": False},
            ("username",): {"name": "suser", "is_custom": False},
        }
        log = {"eventtype": "authentication", "username": "alice"}

        cef = log_to_cef(log, keys_to_labels, Config.AUTH)

        # Prefix fields are pipe-delimited; the CEF message contains the header.
        self.assertIn("CEF:0|Duo Security|DuoLogSync|", cef)
        # signature_id and name both come from eventtype for non-activity logs.
        self.assertIn("|authentication|authentication|5|", cef)
        self.assertIn("cat=authentication", cef)
        self.assertIn("suser=alice", cef)

    def test_administrator_event_uses_action_as_name(self):
        keys_to_labels = {("eventtype",): {"name": "cat", "is_custom": False}}
        log = {"eventtype": "administrator", "action": "admin_login"}
        cef = log_to_cef(log, keys_to_labels, Config.AUTH)
        # For 'administrator' eventtype, the CEF name field is the action.
        self.assertIn("|administrator|admin_login|5|", cef)

    def test_activity_log_uses_action_and_actor(self):
        keys_to_labels = {("result",): {"name": "outcome", "is_custom": False}}
        log = {
            "action": {"name": "create_user"},
            "actor": {"type": "admin"},
            "result": "success",
        }
        cef = log_to_cef(log, keys_to_labels, Config.ACTIVITY)
        self.assertIn("|create_user|admin|5|", cef)
        self.assertIn("outcome=success", cef)

    def test_custom_label_emits_label_pair(self):
        keys_to_labels = {
            ("application", "name"): {"name": "integration_name", "is_custom": True},
        }
        log = {"application": {"name": "MyApp"}, "eventtype": "authentication"}
        cef = log_to_cef(log, keys_to_labels, Config.AUTH)
        # Custom fields emit a csNLabel=<name> pair plus csN=<value>.
        self.assertIn("cs1Label=integration_name", cef)
        self.assertIn("cs1=MyApp", cef)


class TestCef(TestCase):
    def test_construct_extension_always_returns_rt_as_milliseconds(self):

        ts_test_params = [(1631542762, "rt=1631542762000"), (1631542762123, "rt=1631542762123")]

        for param1, param2 in ts_test_params:
            with self.subTest():
                keys_to_label = {("ts",): {"name": "rt", "is_custom": False}}
                mock_log = {"ts": param1}

                response = _construct_extension(mock_log, keys_to_label)

                self.assertEqual(param2, response)

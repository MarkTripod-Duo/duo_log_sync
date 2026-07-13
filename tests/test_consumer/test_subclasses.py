"""
Unit tests for the consumer subclass constructors — each wires the right
log_type and keys-to-labels mapping and inherits the base Consumer attributes.
"""

from unittest import TestCase

from duologsync.config import Config
from duologsync.consumer.activity_consumer import ACTIVITY_KEYS_TO_LABELS, ActivityConsumer
from duologsync.consumer.authlog_consumer import AUTHLOG_KEYS_TO_LABELS, AuthlogConsumer
from duologsync.consumer.telephony_consumer import TELEPHONY_KEYS_TO_LABELS, TelephonyConsumer
from duologsync.consumer.trustmonitor_consumer import TrustMonitorConsumer


class TestConsumerSubclasses(TestCase):
    def test_authlog_consumer(self):
        consumer = AuthlogConsumer(Config.JSON, "queue", "writer", child_account_id="c1")
        self.assertEqual(consumer.log_type, Config.AUTH)
        self.assertIs(consumer.keys_to_labels, AUTHLOG_KEYS_TO_LABELS)
        self.assertEqual(consumer.log_format, Config.JSON)
        self.assertEqual(consumer.child_account_id, "c1")
        self.assertIsNone(consumer.log_offset)

    def test_telephony_consumer(self):
        consumer = TelephonyConsumer(Config.CEF, "queue", "writer")
        self.assertEqual(consumer.log_type, Config.TELEPHONY)
        self.assertIs(consumer.keys_to_labels, TELEPHONY_KEYS_TO_LABELS)

    def test_activity_consumer(self):
        consumer = ActivityConsumer(Config.JSON, "queue", "writer")
        self.assertEqual(consumer.log_type, Config.ACTIVITY)
        self.assertIs(consumer.keys_to_labels, ACTIVITY_KEYS_TO_LABELS)

    def test_trustmonitor_consumer_inherits_empty_labels(self):
        consumer = TrustMonitorConsumer(Config.JSON, "queue", "writer")
        self.assertEqual(consumer.log_type, Config.TRUST_MONITOR)
        self.assertEqual(consumer.keys_to_labels, {})

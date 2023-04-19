"""
Definition of the TelephonyConsumer class
"""

from duologsync.config import Config
from duologsync.consumer.consumer import Consumer

TELEPHONY_KEYS_TO_LABELS = {
    ('context',): {'name': 'context', 'is_custom': True},
    ('credits',): {'name': 'credits', 'is_custom': True},
    ('eventtype',): {'name': 'event_type', 'is_custom': True},
    ('phone',): {'name': 'phone', 'is_custom': True},
    ('timestamp',): {'name': 'rt', 'is_custom': False},
    ('type',): {'name': 'type', 'is_custom': True}
}


class TelephonyConsumer(Consumer):
    """
    An implementation of the Consumer class for telephony logs
    """

    def __init__(self, log_format, log_queue, writer):
        super().__init__(log_format, log_queue, writer)
        self.keys_to_labels = TELEPHONY_KEYS_TO_LABELS
        self.log_type = Config.TELEPHONY

"""
Definition of functions for creating CEF-type logs
"""

import socket
from datetime import datetime
from duologsync.config import Config
from duologsync.__version__ import __version__

# What follows are required prefix fields for every CEF message
CEF_VERSION = 'CEF:0'
DEVICE_VENDOR = 'Duo Security'
DEVICE_PRODUCT = 'DuoLogSync'
DEVICE_VERSION = __version__

# Values allowed: 0 - 10 where 10 indicates the most important event
SEVERITY = '5'


def log_to_cef(log, keys_to_labels):
    """
    Create and return a CEF-type log given a Duo log.

    @param log              The log to convert into a CEF-type log
    @param keys_to_labels   Dictionary of keys used for retrieving values and
                            the associated labels those values should be given

    @return a CEF-type log created from the given log
    """

    # Every cef formatted log should start with current date time and host from which logs
    # are sent
    syslog_date = datetime.now()
    syslog_date_time = syslog_date.strftime("%b %d %H:%M:%S")
    syslog_header = ' '.join([syslog_date_time, socket.gethostname()])

    # Additional required prefix fields
    signature_id = log.get('eventtype', '')
    if signature_id == 'administrator':
        name = log.get('action', '')
    else:
        name = log.get('eventtype', '')

    # Construct the beginning of the CEF message
    header = '|'.join([
        CEF_VERSION, DEVICE_VENDOR, DEVICE_PRODUCT, DEVICE_VERSION,
        signature_id, name, SEVERITY
    ])

    extension = _construct_extension(log, keys_to_labels)
    msg = header + '|' + extension
    cef_log = ' '.join([syslog_header, msg])

    return cef_log


def _construct_extension(log, keys_to_labels):
    """
    Create the extension for a CEF message using the given log and dictionary.

    @param log              The log to convert into a CEF message
    @param keys_to_labels   Dictionary of keys used for retrieving values and
                            the associated labels those values should be given

    @return the extension field for a CEF message
    """

    # List of additional fields to add to the CEF message beyond whats required
    extensions = []

    # Keep track of the number for the custom string being created
    custom_string = 1

    for keys, label in keys_to_labels.items():
        value = Config.get_value_from_keys(log, keys)
        label_name = label['name']

        # cef format expects timestamp to be in milliseconds and not seconds. if length is 10 the ts is in seconds.
        # this value should be an integer as that is what the cef's expectation is for the `rt` field
        if label_name == 'rt' and value and len(str(value)) == 10:
            value = value * 1000

        # Need to generate a custom label
        if label['is_custom']:
            custom_label = f"cs{custom_string}"
            custom_extension = custom_label + 'Label' + '=' + label_name
            extensions.append(custom_extension)
            custom_string += 1
            label_name = custom_label

        extension = label_name + '=' + str(value)
        extensions.append(extension)

    extensions = ' '.join(extensions)
    return extensions

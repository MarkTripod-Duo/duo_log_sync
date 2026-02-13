"""
Definition of the Config class
"""

from datetime import datetime, timedelta, timezone
from http import HTTPStatus

import yaml
from jsonschema import ValidationError, validate
from yaml import YAMLError

from duologsync.program import Program


class Config:
    """
    This class is unique in that no instances of it should be created. It is
    used as a wrapper around a Dictionary object named config that is contains
    important values used throughout DuoLogSync. The _config class variable
    should only be accessed through getter and setter methods and should only
    be set once. There are useful methods defined in this class for generating
    a config Dictionary from a YAML file, validating the config against a
    Schema and setting defaults for a config Dictionary when optional fields
    are not given values.
    """

    # Format type constants
    CEF = 'CEF'
    JSON = 'JSON'

    # Log type constants
    AUTH = 'auth'
    TELEPHONY = 'telephony'
    TRUST_MONITOR = 'trustmonitor'
    ACTIVITY = 'activity'

    DIRECTORY_DEFAULT = '/tmp'
    LOG_FILEPATH_DEFAULT = DIRECTORY_DEFAULT + '/' + 'duologsync.log'
    LOG_FORMAT_DEFAULT = 'JSON'
    API_OFFSET_DEFAULT = 180
    API_TIMEOUT_DEFAULT = 120
    CHECKPOINTING_ENABLED_DEFAULT = True
    CHECKPOINTING_DIRECTORY_DEFAULT = DIRECTORY_DEFAULT
    PROXY_SERVER_DEFAULT = ''
    PROXY_PORT_DEFAULT = 0
    FILE_OUTPUT_QUEUE_MAX_SIZE_DEFAULT = 5000
    FILE_OUTPUT_MAX_RETRIES_DEFAULT = 3
    FILE_OUTPUT_RETRY_BACKOFF_SECONDS_DEFAULT = 0.2
    FILE_OUTPUT_TEST_INPUT_ENABLED_DEFAULT = False

    GRACEFUL_RETRY_STATUS_CODES = (HTTPStatus.TOO_MANY_REQUESTS.value,)

    # JSON Schema for the endpoint_server_mapping items
    _ENDPOINT_SERVER_MAPPING_SCHEMA = {
        'type': 'object',
        'required': ['server', 'endpoints'],
        'additionalProperties': False,
        'properties': {
            'server': {
                'type': 'string',
                'minLength': 1,
            },
            'endpoints': {
                'type': 'array',
                'minItems': 1,
                'items': {
                    'type': 'string',
                    'enum': [AUTH, TELEPHONY, TRUST_MONITOR, ACTIVITY],
                },
            },
        },
    }

    # JSON Schema for a single server entry
    _SERVER_SCHEMA = {
        'type': 'object',
        'required': ['id', 'protocol'],
        'additionalProperties': False,
        'properties': {
            'id': {'type': 'string', 'minLength': 1},
            'hostname': {'type': 'string', 'minLength': 1},
            'port': {'type': 'integer', 'minimum': 0, 'maximum': 65535},
            'protocol': {
                'type': 'string',
                'enum': ['TCP', 'TCPSSL', 'UDP', 'FILE'],
            },
            'cert_filepath': {'type': 'string', 'minLength': 1},
            'filepath': {'type': 'string', 'minLength': 1},
        },
        'allOf': [
            {
                'if': {
                    'properties': {'protocol': {'const': 'TCPSSL'}},
                    'required': ['protocol'],
                },
                'then': {
                    'required': ['hostname', 'port', 'cert_filepath'],
                },
            },
            {
                'if': {
                    'properties': {
                        'protocol': {'enum': ['TCP', 'UDP']},
                    },
                    'required': ['protocol'],
                },
                'then': {
                    'required': ['hostname', 'port'],
                },
            },
            {
                'if': {
                    'properties': {'protocol': {'const': 'FILE'}},
                    'required': ['protocol'],
                },
                'then': {
                    'required': ['filepath'],
                },
            },
        ],
    }

    # Top-level JSON Schema
    SCHEMA = {
        'type': 'object',
        'required': ['version', 'servers', 'account'],
        'additionalProperties': False,
        'properties': {
            'version': {'type': 'string', 'minLength': 1},
            'dls_settings': {
                'type': 'object',
                'additionalProperties': False,
                'properties': {
                    'log_filepath': {'type': 'string', 'minLength': 1},
                    'log_format': {
                        'type': 'string',
                        'enum': [CEF, JSON],
                    },
                    'api': {
                        'type': 'object',
                        'additionalProperties': False,
                        'properties': {
                            'offset': {
                                'type': 'number',
                                'minimum': 0,
                                'maximum': 180,
                            },
                            'timeout': {'type': 'number'},
                        },
                    },
                    'checkpointing': {
                        'type': 'object',
                        'additionalProperties': False,
                        'properties': {
                            'enabled': {'type': 'boolean'},
                            'directory': {'type': 'string', 'minLength': 1},
                        },
                    },
                    'proxy': {
                        'type': 'object',
                        'additionalProperties': False,
                        'properties': {
                            'proxy_server': {'type': 'string'},
                            'proxy_port': {'type': 'number'},
                        },
                    },
                    'file_output': {
                        'type': 'object',
                        'additionalProperties': False,
                        'properties': {
                            'queue_max_size': {
                                'type': 'integer',
                                'minimum': 1,
                            },
                            'max_retries': {
                                'type': 'integer',
                                'minimum': 0,
                            },
                            'retry_backoff_seconds': {
                                'type': 'number',
                                'minimum': 0,
                            },
                            'enable_test_input': {'type': 'boolean'},
                        },
                    },
                },
            },
            'servers': {
                'type': 'array',
                'minItems': 1,
                'items': _SERVER_SCHEMA,
            },
            'account': {
                'type': 'object',
                'required': ['ikey', 'skey', 'hostname',
                             'endpoint_server_mappings'],
                'additionalProperties': False,
                'properties': {
                    'ikey': {'type': 'string', 'minLength': 1},
                    'skey': {'type': 'string', 'minLength': 1},
                    'hostname': {'type': 'string', 'minLength': 1},
                    'endpoint_server_mappings': {
                        'type': 'array',
                        'minItems': 1,
                        'items': _ENDPOINT_SERVER_MAPPING_SCHEMA,
                    },
                    'is_msp': {'type': 'boolean'},
                    'block_list': {'type': 'array'},
                },
            },
        },
    }

    # Default values applied during normalization. Structure mirrors the
    # config dict — nested dicts are recursed into, leaf values are used
    # as defaults for missing keys.
    _DEFAULTS = {
        'dls_settings': {
            'log_filepath': LOG_FILEPATH_DEFAULT,
            'log_format': LOG_FORMAT_DEFAULT,
            'api': {
                'offset': API_OFFSET_DEFAULT,
                'timeout': API_TIMEOUT_DEFAULT,
            },
            'checkpointing': {
                'enabled': CHECKPOINTING_ENABLED_DEFAULT,
                'directory': CHECKPOINTING_DIRECTORY_DEFAULT,
            },
            'proxy': {
                'proxy_server': PROXY_SERVER_DEFAULT,
                'proxy_port': PROXY_PORT_DEFAULT,
            },
            'file_output': {
                'queue_max_size': FILE_OUTPUT_QUEUE_MAX_SIZE_DEFAULT,
                'max_retries': FILE_OUTPUT_MAX_RETRIES_DEFAULT,
                'retry_backoff_seconds': FILE_OUTPUT_RETRY_BACKOFF_SECONDS_DEFAULT,
                'enable_test_input': FILE_OUTPUT_TEST_INPUT_ENABLED_DEFAULT,
            },
        },
        'account': {
            'is_msp': False,
            'block_list': [],
        },
    }

    # Private class variable, should not be accessed directly, only through
    # getter and setter methods
    _config = None

    # Used to ensure that the _config variable is set once and only once
    _config_is_set = False

    @classmethod
    def _check_config_is_set(cls):
        """
        Used to check that this Config object is set before trying to access
        or set values
        """
        if cls._config_is_set:
            return

        raise RuntimeError('Cannot access values of config before setting it')

    @classmethod
    def set_config(cls, config):
        """
        Function used to set the config of a Config object once and only once.

        @param config   Dictionary used to set a Config object's 'config'
                        instance variable
        """
        if cls._config_is_set:
            raise RuntimeError('Config object already set. Cannot set Config '
                               'object more than once')

        cls._config = config
        cls._config_is_set = True

    @classmethod
    def get_value(cls, keys):
        """
        Getter for a Config object's 'config' instance variable
        """

        cls._check_config_is_set()
        curr_value = cls._config
        if curr_value:
            for key in keys:
                curr_value = curr_value.get(key)

                if curr_value is None:
                    raise ValueError(f"{key} is an invalid key for this Config")

        return curr_value

    @classmethod
    def get_config_file_path(cls):
        """@return the filepath of the config file"""
        return cls.get_value(['config_file_path'])

    @classmethod
    def get_log_filepath(cls):
        """@return the filepath where DLS program messages should be saved"""
        return cls.get_value(['dls_settings', 'log_filepath'])

    @classmethod
    def get_log_format(cls):
        """@return how Duo logs should be formatted"""
        return cls.get_value(['dls_settings', 'log_format'])

    @classmethod
    def get_api_offset(cls):
        """@return the timestamp from which record retrieval should begin"""
        return cls.get_value(['dls_settings', 'api', 'offset'])

    @classmethod
    def get_api_timeout(cls):
        """@return the seconds to wait between API calls"""
        return cls.get_value(['dls_settings', 'api', 'timeout'])

    @classmethod
    def get_checkpointing_enabled(cls):
        """@return whether checkpoint files should be used to recover offsets"""
        return cls.get_value(['dls_settings', 'checkpointing', 'enabled'])

    @classmethod
    def get_checkpoint_dir(cls):
        """@return the directory where checkpoint files should be stored"""
        return cls.get_value(
            ['dls_settings', 'checkpointing', 'directory'])

    @classmethod
    def get_servers(cls):
        """@return the list of servers to which Duo logs will be written"""
        return cls.get_value(['servers'])

    @classmethod
    def get_account_ikey(cls):
        """@return the ikey of the account in config"""
        return cls.get_value(['account', 'ikey'])

    @classmethod
    def get_account_skey(cls):
        """@return the skey of the account in config"""
        return cls.get_value(['account', 'skey'])

    @classmethod
    def get_account_hostname(cls):
        """@return the hostname of the account in config"""
        return cls.get_value(['account', 'hostname'])

    @classmethod
    def get_account_endpoint_server_mappings(cls):
        """@return the endpoint_server_mappings of the account in config"""
        return cls.get_value(['account', 'endpoint_server_mappings'])

    @classmethod
    def get_account_block_list(cls):
        """@return the block_list of the account in config"""
        return cls.get_value(['account', 'block_list'])

    @classmethod
    def account_is_msp(cls):
        """@return whether the account in config is an MSP account"""
        return cls.get_value(['account', 'is_msp'])

    @classmethod
    def get_proxy_server(cls):
        """@return the proxy_server in config"""
        return cls.get_value(['dls_settings', 'proxy', 'proxy_server'])

    @classmethod
    def get_proxy_port(cls):
        """@return the proxy_port in config"""
        return cls.get_value(['dls_settings', 'proxy', 'proxy_port'])

    @classmethod
    def get_file_output_queue_max_size(cls):
        """@return max queue size for local file output"""
        return cls.get_value(['dls_settings', 'file_output', 'queue_max_size'])

    @classmethod
    def get_file_output_max_retries(cls):
        """@return max write retry attempts for local file output"""
        return cls.get_value(['dls_settings', 'file_output', 'max_retries'])

    @classmethod
    def get_file_output_retry_backoff_seconds(cls):
        """@return base backoff for local file output retries"""
        return cls.get_value(
            ['dls_settings', 'file_output', 'retry_backoff_seconds'])

    @classmethod
    def get_file_output_test_input_enabled(cls):
        """@return whether test-input injection is enabled"""
        return cls.get_value(
            ['dls_settings', 'file_output', 'enable_test_input'])

    @classmethod
    def validate_config(cls, config_filepath):
        """
        Validate a config file without side effects. Returns a list of error
        strings (empty list means the config is valid). Does not call
        Program.initiate_shutdown or Program.log — callers decide how to
        present errors.

        Checks performed:
        1. File can be opened and read
        2. File contains valid YAML
        3. YAML structure passes JSON Schema validation
        4. API timeout minimum is enforced (warning, not error)

        @param config_filepath  Path to the YAML config file
        @return (errors, warnings) — two lists of human-readable strings
        """
        errors = []
        warnings = []

        # 1. Read the file
        try:
            with open(config_filepath) as config_file:
                config_file_data = config_file.read()
        except OSError as os_error:
            errors.append(
                f"Failed to open config file: {os_error}"
            )
            return errors, warnings

        # 2. Parse YAML
        try:
            config = yaml.full_load(config_file_data)
        except YAMLError as yaml_error:
            errors.append(
                f"Failed to parse YAML: {yaml_error}"
            )
            return errors, warnings

        if not isinstance(config, dict):
            errors.append(
                "Config file must contain a YAML mapping (dictionary) at "
                "the top level"
            )
            return errors, warnings

        # 3. Validate against JSON Schema
        try:
            validate(instance=config, schema=cls.SCHEMA)
        except ValidationError as error:
            path = ' -> '.join(str(p) for p in error.absolute_path) if error.absolute_path else '(root)'
            errors.append(
                f"Schema validation error at '{path}': {error.message}"
            )
            return errors, warnings

        # 4. Apply defaults and check business rules
        cls._apply_defaults(config, cls._DEFAULTS)

        api_timeout = config.get('dls_settings', {}).get('api', {}).get('timeout')
        if api_timeout is not None and api_timeout < cls.API_TIMEOUT_DEFAULT:
            warnings.append(
                f"API timeout ({api_timeout}s) is below the minimum "
                f"({cls.API_TIMEOUT_DEFAULT}s) and will be raised to "
                f"{cls.API_TIMEOUT_DEFAULT}s at runtime"
            )

        return errors, warnings

    @classmethod
    def create_config(cls, config_filepath):
        """
        Attempt to read the file at config_filepath and generate a config
        Dictionary object based on a defined JSON schema

        @param config_filepath  File from which to generate a config object
        """

        shutdown_reason = None

        try:
            with open(config_filepath) as config_file:
                # PyYAML gives better error messages for streams than for files
                config_file_data = config_file.read()
                config = yaml.full_load(config_file_data)

                # Check config against a schema to ensure all the needed fields
                # and values are defined
                config = cls._validate_and_normalize_config(config)
                api_timeout = config.get('dls_settings', {}).get('api', {}).get('timeout')
                if api_timeout is not None and api_timeout < cls.API_TIMEOUT_DEFAULT:
                    config['dls_settings']['api']['timeout'] = cls.API_TIMEOUT_DEFAULT
                    Program.log(f'DuoLogSync: Setting default api timeout to {cls.API_TIMEOUT_DEFAULT} seconds.')
                config['config_file_path'] = config_filepath

        # Will occur when given a bad filepath or a bad file
        except OSError as os_error:
            shutdown_reason = f"{os_error}"
            Program.log('DuoLogSync: Failed to open the config file. Check '
                        'that the filename is correct')

        # Will occur if the config file does not contain valid YAML
        except YAMLError as yaml_error:
            shutdown_reason = f"{yaml_error}"
            Program.log('DuoLogSync: Failed to parse the config file. Check '
                        'that the config file has valid YAML.')

        # Validation of the config against a schema failed
        except ValueError as val_error:
            shutdown_reason = f"{val_error}"
            Program.log('DuoLogSync: Validation of the config file failed. '
                        'Check that required fields have proper values.')

        # No exception raised during the try block, return config
        else:
            # Calculate offset as a timestamp and rewrite its value in config
            offset = config.get('dls_settings', {}).get('api', {}).get('offset', cls.API_OFFSET_DEFAULT)
            offset = datetime.now(timezone.utc) - timedelta(days=offset)
            config['dls_settings']['api']['offset'] = int(offset.timestamp())
            return config

        # At this point, it is guaranteed that an exception was raised, which
        # means that it is shutdown time
        Program.initiate_shutdown(shutdown_reason)
        return None

    @classmethod
    def _validate_and_normalize_config(cls, config):
        """
        Validate config against the JSON schema, then apply defaults for
        any missing optional fields.

        @param config   Dictionary for which to validate the structure
        """
        try:
            validate(instance=config, schema=cls.SCHEMA)
        except ValidationError as error:
            raise ValueError(error.message) from error

        cls._apply_defaults(config, cls._DEFAULTS)
        return config

    @staticmethod
    def _apply_defaults(config, defaults):
        """
        Recursively apply default values to a config dict. For each key in
        defaults, if the key is missing from config, set it. If both config
        and defaults have a dict for that key, recurse into it.
        """
        for key, default_value in defaults.items():
            if key not in config:
                if isinstance(default_value, dict):
                    config[key] = {}
                    Config._apply_defaults(config[key], default_value)
                elif isinstance(default_value, list):
                    config[key] = list(default_value)
                else:
                    config[key] = default_value
            elif isinstance(default_value, dict) and isinstance(config.get(key), dict):
                Config._apply_defaults(config[key], default_value)

    @staticmethod
    def get_value_from_keys(dictionary, keys):
        """
        Drill down into dictionary to retrieve a value given a list of keys

        @param dictionary   dict to retrieve a value from
        @param keys         List of keys to follow to retrieve a value

        @return value from the log found after following the list of keys given
        """

        value = dictionary

        for key in keys:
            value = value.get(key)

            if value is None:
                break

        return value

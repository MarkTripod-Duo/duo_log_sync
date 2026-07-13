"""
Definition of the Writer class
"""

import asyncio
import errno
import logging
import os
import random
import socket
import ssl
import threading
import traceback
from datetime import date, datetime
from pathlib import Path
from socket import gaierror
from tempfile import NamedTemporaryFile

from duologsync import util
from duologsync.config import Config
from duologsync.program import Program


class DatagramProtocol(asyncio.DatagramProtocol):
    """
    DLS implementation of Asyncio's abstract DatagramProtocol class. This is
    required for creating a network connection over UDP.
    """

    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.transport = None
        super().__init__()

    def connection_made(self, transport):
        self.transport = transport

    def connection_lost(self, exc):
        shutdown_reason = None

        if exc:
            shutdown_reason = (
                f"UDP connection with host-{self.host} and port-{self.port} was closed for the following reason [{exc}]"
            )

        else:
            shutdown_reason = f"UDP connection with host-{self.host} and port-{self.port} was closed"

        Program.initiate_shutdown(shutdown_reason)


class LocalFileWriter:
    """
    Asynchronous local-file writer used when server protocol is FILE.
    """

    _STOP = object()

    # Rotation modes (mirror Config.FILE_OUTPUT_ROTATION_* constants).
    ROTATION_NONE = "none"
    ROTATION_SIZE = "size"
    ROTATION_TIME = "time"
    ROTATION_BOTH = "both"

    def __init__(
        self,
        filepath,
        checkpoint_directory,
        queue_max_size,
        max_retries,
        retry_backoff_seconds,
        enable_test_input,
        rotation=ROTATION_NONE,
        max_bytes=104857600,
        rotation_interval="daily",
        backup_count=7,
    ):
        self.filepath = self._validate_filepath(filepath)
        self.checkpoint_directory = Path(checkpoint_directory)
        self.queue = asyncio.Queue(maxsize=queue_max_size)
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self.enable_test_input = enable_test_input

        # Rotation configuration. Rotation is performed synchronously inside
        # the executor-backed write path and guarded by a threading lock so
        # concurrent writes (worker + backlog replay) never race on the
        # check-rename-reopen sequence.
        self.rotation = rotation
        self.max_bytes = max_bytes
        self.rotation_interval = rotation_interval
        self.backup_count = backup_count
        self._rotate_lock = threading.Lock()

        self._registered_log_types = set()
        self._initialized_log_types = set()
        self._start_lock = asyncio.Lock()
        self._init_lock = asyncio.Lock()
        self._worker_task = None
        self._started = False

    @staticmethod
    def _validate_filepath(filepath):
        if not filepath:
            raise ValueError("FILE protocol requires a valid filepath")

        normalized_path = Path(filepath).expanduser()
        if not normalized_path.is_absolute():
            normalized_path = Path.cwd() / normalized_path

        directory = normalized_path.parent
        if not directory.exists():
            try:
                directory.mkdir(parents=True, exist_ok=True)
            except OSError as error:
                raise OSError(
                    f"failed to create directory '{directory}' for FILE output "
                    f"error_message: {error.strerror} error_code: {error.errno}"
                ) from error

        if not directory.is_dir():
            raise FileNotFoundError(f"path '{directory}' is not a directory for FILE output")

        LocalFileWriter._validate_directory_writable(directory)

        if normalized_path.is_dir():
            raise IsADirectoryError(f"filepath '{normalized_path}' is a directory, expected a file")

        LocalFileWriter._validate_existing_file_writable(normalized_path)

        return normalized_path.resolve(strict=False)

    @staticmethod
    def _validate_directory_writable(directory):
        try:
            with NamedTemporaryFile(dir=str(directory), prefix=".dls_perm_", delete=True):
                pass
        except OSError as error:
            raise PermissionError(
                f"directory '{directory}' is not writable for FILE output "
                f"error_message: {error.strerror} error_code: {error.errno}"
            ) from error

    @staticmethod
    def _validate_existing_file_writable(filepath):
        if not filepath.exists():
            return

        try:
            with filepath.open("ab"):
                pass
        except OSError as error:
            raise PermissionError(
                f"filepath '{filepath}' is not writable for FILE output "
                f"error_message: {error.strerror} error_code: {error.errno}"
            ) from error

    def register_log_type(self, log_type):
        self._registered_log_types.add(log_type)

    async def start(self):
        if self._started:
            return

        async with self._start_lock:
            if self._started:
                return

            Program.log(
                f"DuoLogSync: local file writer starting for '{self.filepath}'",
                logging.INFO,
            )

            for log_type in sorted(self._registered_log_types):
                await self._initialize_log_type(log_type)

            self._worker_task = asyncio.ensure_future(self._process_queue())
            self._started = True
            Program.log(
                f"DuoLogSync: local file writer started for '{self.filepath}'",
                logging.INFO,
            )

    async def shutdown(self):
        if not self._started:
            return

        Program.log(
            f"DuoLogSync: local file writer shutting down for '{self.filepath}'",
            logging.INFO,
        )

        await self.queue.put(self._STOP)

        if self._worker_task:
            await self._worker_task

        Program.log(
            f"DuoLogSync: local file writer shutdown complete for '{self.filepath}'",
            logging.INFO,
        )

    async def write(self, data, log_type):
        await self.start()
        await self._initialize_log_type(log_type)

        try:
            self.queue.put_nowait((log_type, data))
        except asyncio.QueueFull:
            Program.log(
                f"{log_type} consumer: FILE writer queue is full, writing entry to backlog",
                logging.WARNING,
            )
            await self._append_backlog(log_type, data)

    async def inject_test_data(self, log_type, payloads):
        """
        Test-only helper for direct payload ingestion to simulate high load.
        """

        if not self.enable_test_input:
            raise RuntimeError("FILE test input injection is disabled")

        for payload in payloads:
            if isinstance(payload, str):
                payload_bytes = payload.encode("utf-8")
            else:
                payload_bytes = payload

            if not payload_bytes.endswith(b"\n"):
                payload_bytes += b"\n"

            await self.write(payload_bytes, log_type)

    async def _initialize_log_type(self, log_type):
        if log_type in self._initialized_log_types:
            return

        async with self._init_lock:
            if log_type in self._initialized_log_types:
                return

            await self._replay_backlog(log_type)
            self._initialized_log_types.add(log_type)

    async def _process_queue(self):
        try:
            while True:
                item = await self.queue.get()

                if item is self._STOP:
                    self.queue.task_done()
                    break

                log_type, data = item
                try:
                    write_success, should_backlog = await self._write_with_retries(data, log_type)
                    if not write_success and should_backlog:
                        await self._append_backlog(log_type, data)
                except Exception as error:
                    Program.log(
                        f"FILE writer: unexpected error processing queue item "
                        f"for '{self.filepath}' "
                        f"error_type: {type(error).__name__} "
                        f"error_message: {error}",
                        logging.ERROR,
                    )

                self.queue.task_done()
        except asyncio.CancelledError:
            Program.log(
                f"FILE writer: queue processor cancelled for '{self.filepath}'",
                logging.WARNING,
            )
        except Exception as error:
            Program.log(
                f"FILE writer: queue processor crashed for '{self.filepath}' "
                f"error_type: {type(error).__name__} "
                f"error_message: {error}",
                logging.ERROR,
            )
            Program.initiate_shutdown(f"FILE writer queue processor crashed: {error}")

    async def _write_with_retries(self, data, log_type):
        attempts = self.max_retries + 1
        for attempt in range(1, attempts + 1):
            try:
                await asyncio.get_event_loop().run_in_executor(None, self._write_to_file, data)
                return True, False
            except OSError as error:
                if self._is_disk_full_error(error):
                    self._shutdown_for_disk_full(log_type, error)
                    return False, False

                if attempt == attempts:
                    Program.log(
                        f"{log_type} consumer: exhausted FILE write retries for '{self.filepath}' error_message: "
                        f"{error.strerror} error_code: {error.errno}",
                        logging.ERROR,
                    )
                    return False, True

                Program.log(
                    f"{log_type} consumer: FILE write failed (attempt {attempt}/{attempts}) for '"
                    f"{self.filepath}', retrying error_message: {error.strerror} error_code: {error.errno}",
                    logging.WARNING,
                )
                backoff = (self.retry_backoff_seconds * (2 ** (attempt - 1))) + random.uniform(0, 0.1)
                await asyncio.sleep(backoff)

        # All retry attempts were handled inside the loop; this is unreachable
        # unless max_retries is misconfigured to a negative value.
        return False, True  # pragma: no cover

    def _write_to_file(self, data):
        # When rotation is disabled, preserve the original lock-free append
        # fast path. Otherwise serialize the rotate-check + append so parallel
        # writers cannot race on the rename/reopen.
        if self.rotation == self.ROTATION_NONE:
            self._append_bytes(data)
            return

        with self._rotate_lock:
            self._maybe_rotate(len(data))
            self._append_bytes(data)

    def _append_bytes(self, data):
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW

        descriptor = os.open(str(self.filepath), flags, 0o600)
        try:
            with os.fdopen(descriptor, "ab", buffering=0) as output_file:
                output_file.write(data)
                descriptor = None
        finally:
            # If fdopen fails before creating the file object, close descriptor.
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass

    def _maybe_rotate(self, incoming_len):
        """
        Rotate the active output file if the configured size and/or time
        trigger has been reached. A rotation failure is logged and swallowed
        so writing continues on the current file — rotation must never crash
        the writer or drop data.
        """
        try:
            if not self.filepath.exists():
                return

            current_size = self.filepath.stat().st_size

            # An empty active file never needs rotation.
            if current_size == 0:
                return

            should_rotate = False

            if self.rotation in (self.ROTATION_SIZE, self.ROTATION_BOTH):
                if current_size + incoming_len > self.max_bytes:
                    should_rotate = True

            if not should_rotate and self.rotation in (self.ROTATION_TIME, self.ROTATION_BOTH):
                file_date = date.fromtimestamp(self.filepath.stat().st_mtime)
                if file_date < date.today():
                    should_rotate = True

            if should_rotate:
                self._rotate_file()
        except OSError as error:
            Program.log(
                f"FILE writer: rotation check failed for '{self.filepath}', "
                f"continuing on current file "
                f"error_message: {getattr(error, 'strerror', error)} "
                f"error_code: {getattr(error, 'errno', None)}",
                logging.WARNING,
            )

    def _rotate_file(self):
        """Rename the active file to a timestamped backup and prune old ones."""
        timestamp = datetime.fromtimestamp(self.filepath.stat().st_mtime).strftime("%Y-%m-%d_%H%M%S")

        candidate = self.filepath.parent / f"{self.filepath.name}.{timestamp}"
        counter = 1
        # Guard against multiple rotations within the same second.
        while candidate.exists():
            candidate = self.filepath.parent / (f"{self.filepath.name}.{timestamp}.{counter}")
            counter += 1

        self.filepath.replace(candidate)
        Program.log(
            f"FILE writer: rotated '{self.filepath}' to '{candidate}'",
            logging.INFO,
        )
        self._prune_backups()

    def _prune_backups(self):
        """Delete the oldest rotated files beyond backup_count.

        Ordering is by modification time (oldest first) rather than by name:
        rotated filenames are timestamped, but in a burst of rotations within
        the same second the disambiguating suffix would break lexical ordering.
        mtime is preserved across the rename and is always chronological.
        """
        if self.backup_count is None:
            return

        pattern = f"{self.filepath.name}.*"

        def sort_key(path):
            try:
                return (path.stat().st_mtime, path.name)
            except OSError:
                # File vanished; sort it first so it is pruned/ignored.
                return (0.0, path.name)

        backups = sorted(
            (path for path in self.filepath.parent.glob(pattern) if path.is_file()),
            key=sort_key,
        )

        excess = len(backups) - self.backup_count
        for stale in backups[: max(0, excess)]:
            try:
                stale.unlink()
                Program.log(
                    f"FILE writer: pruned rotated file '{stale}'",
                    logging.INFO,
                )
            except OSError:
                # Best-effort cleanup; a failed unlink must not stop writing.
                pass

    async def _append_backlog(self, log_type, data):
        error = await asyncio.get_event_loop().run_in_executor(None, self._append_backlog_sync, log_type, data)
        if error is not None:
            if self._is_disk_full_error(error):
                self._shutdown_for_disk_full(log_type, error)
            else:
                Program.log(
                    f"{log_type} consumer: failed to write FILE backlog "
                    f"'{self._backlog_path(log_type)}' "
                    f"error_message: {error.strerror} error_code: {error.errno}",
                    logging.ERROR,
                )
        else:
            Program.log(
                f"{log_type} consumer: stored FILE write failure in backlog '{self._backlog_path(log_type)}'",
                logging.WARNING,
            )

    def _append_backlog_sync(self, log_type, data):
        """Write data to backlog file. Returns the OSError on failure, None on success."""
        backlog_path = self._backlog_path(log_type)
        try:
            with backlog_path.open("ab") as backlog_file:
                backlog_file.write(data)
        except OSError as error:
            return error

        return None

    async def _replay_backlog(self, log_type):
        backlog_path = self._backlog_path(log_type)
        replay_path = Path(f"{backlog_path}.replay")

        if replay_path.exists():
            Program.log(
                f"{log_type} consumer: found in-progress FILE backlog replay '{replay_path}'",
                logging.INFO,
            )
        elif backlog_path.exists() and backlog_path.stat().st_size > 0:
            backlog_path.replace(replay_path)
            Program.log(
                f"{log_type} consumer: detected startup FILE backlog '{backlog_path}', replay starting",
                logging.INFO,
            )

        if not replay_path.exists():
            return

        replay_success = await self._replay_backlog_file(log_type, replay_path)

        if replay_success:
            try:
                replay_path.unlink()
            except OSError:
                pass
            Program.log(
                f"{log_type} consumer: FILE backlog replay completed for '{self.filepath}'",
                logging.INFO,
            )

    async def _replay_backlog_file(self, log_type, replay_path):
        try:
            with replay_path.open("rb") as replay_file:
                while True:
                    line = replay_file.readline()
                    if not line:
                        return True

                    write_success, _ = await self._write_with_retries(line, log_type)
                    if write_success:
                        continue

                    remaining_lines = [line] + replay_file.readlines()
                    await asyncio.get_event_loop().run_in_executor(
                        None,
                        self._append_remaining_backlog,
                        self._backlog_path(log_type),
                        remaining_lines,
                    )
                    Program.log(
                        f"{log_type} consumer: FILE backlog replay paused after write failure, remaining entries "
                        f"preserved",
                        logging.WARNING,
                    )
                    return False

        except OSError as error:
            Program.log(
                f"{log_type} consumer: failed to read FILE backlog replay file '{replay_path}' error_message: "
                f"{error.strerror} error_code: {error.errno}",
                logging.ERROR,
            )
            return False

    @staticmethod
    def _is_disk_full_error(error):
        disk_full_codes = {errno.ENOSPC}
        if hasattr(errno, "EDQUOT"):
            disk_full_codes.add(errno.EDQUOT)

        return getattr(error, "errno", None) in disk_full_codes

    def _shutdown_for_disk_full(self, log_type, error):
        Program.log(
            f"{log_type} consumer: disk full detected for FILE output '{self.filepath}' error_message: "
            f"{error.strerror} error_code: {error.errno}",
            logging.ERROR,
        )
        Program.initiate_shutdown(
            f"{log_type} consumer: disk full for FILE output '{self.filepath}' "
            f"error_message: {error.strerror} error_code: {error.errno}"
        )

    @staticmethod
    def _append_remaining_backlog(backlog_path, remaining_lines):
        with backlog_path.open("ab") as backlog_file:
            for line in remaining_lines:
                backlog_file.write(line)

    def _backlog_path(self, log_type):
        return self.checkpoint_directory / (f"{log_type}_file_failed_ingestion_logs.txt")


class Writer:
    """
    Class for creating Writer objects which are a wrapper for Asyncio streams
    and open_connections objects for sending data over UDP, TCP and TCPSSL.
    """

    def __init__(self, server):
        # Needed to determine what type of writer to create and how to use it
        self.protocol = server["protocol"]
        self.hostname = server.get("hostname")
        self.port = server.get("port")

        # Create the actual writer
        self.writer = asyncio.get_event_loop().run_until_complete(
            self.create_writer(
                self.hostname,
                self.port,
                server.get("cert_filepath"),
                server.get("filepath"),
            )
        )

    @staticmethod
    def create_writers(servers):
        """
        For each server, create a writer object and add a dictionary entry mapping
        the server name to the writer object. Return the resulting dictionary.

        @param servers  List of servers for which to create writer objects

        @return a dictionary mapping server name to writer object
        """

        writers = {}

        for server in servers:
            server_id = server["id"]
            writer = Writer(server)
            writers[server_id] = writer

        return writers

    async def write(self, data, log_type):
        """
        Wrapper for writer functions. Makes it easy for parts of a program that
        uses a writer to forget what type of connection is being used (UDP vs
        TCP.)

        @param data The information to be written over a network connection
        """
        if self.protocol == "UDP":
            try:
                self.writer.sendto(data, (self.hostname, self.port))
            except OSError as error:
                # If the message is too long, the UDP socket will throw an error
                # and we need to handle it
                # Store the failed UDP ingestion logs in a file and log the error
                # message to the console
                err = util.extract_error_info(error)
                Program.log(
                    f"{log_type} consumer: UDP send failed to "
                    f"{self.hostname}:{self.port} "
                    f"error_message: {err['error_message']} error_code: {err['error_code']}",
                    logging.WARNING,
                )
                util.store_failed_udp_ingestion_logs(
                    log_type,
                    Config.get_checkpoint_dir(),
                    data,
                )
        elif self.protocol == "FILE":
            if not self.writer:
                return
            await self.writer.write(data, log_type)
        else:
            # TCP/TCPSSL — propagate connection errors to the consumer for
            # graceful shutdown handling. asyncio.TimeoutError is caught
            # explicitly because it is not an OSError subclass on Python < 3.11.
            try:
                self.writer.write(data)
                await self.writer.drain()
            except (OSError, asyncio.TimeoutError) as error:
                err = util.extract_error_info(error)
                Program.log(
                    f"{log_type} writer: {type(error).__name__} while sending data to {self.hostname}:{self.port} over {self.protocol} - error_message: {err['error_message']} error_code: {err['error_code']}\n{traceback.format_exc()}",
                    logging.ERROR,
                )
                raise

    def register_log_type(self, log_type):
        if self.protocol == "FILE" and self.writer:
            self.writer.register_log_type(log_type)

    async def inject_test_data(self, log_type, payloads):
        if self.protocol != "FILE":
            raise RuntimeError("test data injection is only supported for FILE writers")
        if not self.writer:
            raise RuntimeError("FILE writer could not be initialized")

        await self.writer.inject_test_data(log_type, payloads)

    async def shutdown(self):
        if not self.writer:
            return

        if self.protocol == "UDP":
            try:
                self.writer.close()
            except OSError:
                pass
            return

        if self.protocol == "FILE":
            await self.writer.shutdown()
            return

        # TCP/TCPSSL writer
        try:
            self.writer.close()
            wait_closed = getattr(self.writer, "wait_closed", None)
            if wait_closed:
                await asyncio.wait_for(wait_closed(), timeout=5.0)
        except asyncio.TimeoutError:
            Program.log(
                f"DuoLogSync: TCP close to {self.hostname}:{self.port} "
                f"timed out after 5 seconds, proceeding with shutdown",
                logging.WARNING,
            )
        except OSError as error:
            err = util.extract_error_info(error)
            Program.log(
                f"DuoLogSync: error closing TCP connection to "
                f"{self.hostname}:{self.port} "
                f"error_message: {err['error_message']} error_code: {err['error_code']}",
                logging.WARNING,
            )

    async def create_writer(self, host, port, cert_filepath, filepath=None):
        """
        Wrapper for functions to create TCP or UDP connections.

        @param host             Hostname of the network connection to establish
        @param port             Port of the network connection to establish
        @param cert_filepath    Path to file containing SSL certificate

        @return a 'writer' object for writing data over the connection made
        """

        if self.protocol == "FILE":
            Program.log(
                f"DuoLogSync: Preparing local file writer for '{filepath}'",
                logging.INFO,
            )
            try:
                return LocalFileWriter(
                    filepath=filepath,
                    checkpoint_directory=Config.get_checkpoint_dir(),
                    queue_max_size=Config.get_file_output_queue_max_size(),
                    max_retries=Config.get_file_output_max_retries(),
                    retry_backoff_seconds=Config.get_file_output_retry_backoff_seconds(),
                    enable_test_input=Config.get_file_output_test_input_enabled(),
                    rotation=Config.get_file_output_rotation(),
                    max_bytes=Config.get_file_output_max_bytes(),
                    rotation_interval=Config.get_file_output_rotation_interval(),
                    backup_count=Config.get_file_output_backup_count(),
                )
            except (
                FileNotFoundError,
                IsADirectoryError,
                PermissionError,
                ValueError,
                OSError,
            ) as error:
                Program.initiate_shutdown(str(error))
                Program.log(
                    "DuoLogSync: check FILE writer path configuration in config file",
                    logging.ERROR,
                )
                return None

        Program.log(f"DuoLogSync: Opening connection to {host}:{port} with protocol {self.protocol}", logging.INFO)

        # Message to be logged if an error occurs in this function
        help_message = f"DuoLogSync: check that host-{host} and port-{port} are correct in the configuration file '{Config.get_config_file_path()}'"
        writer = None

        try:
            if self.protocol == "UDP":
                writer = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

            elif self.protocol == "TCPSSL":
                ssl_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=cert_filepath)

                writer = await Writer.create_tcp_writer(host, port, ssl_context)

            elif self.protocol == "TCP":
                writer = await Writer.create_tcp_writer(host, port)

        # Failed to open the certificate file
        except FileNotFoundError as fnf_error:
            err = util.extract_error_info(fnf_error)
            shutdown_reason = f"certificate file '{cert_filepath}' could not be opened due to error: {err['error_message']} error_code: {err['error_code']}"
            help_message = f"make sure that certificate file '{cert_filepath}' to establish SSL connection is correct."

        # Couldn't establish a connection within 60 seconds
        except asyncio.TimeoutError:
            shutdown_reason = "connection to the destination server timed-out after 60 seconds"

        # If an invalid hostname or port number is given or simply failed to
        # connect using the host and port given
        except (gaierror, OSError) as error:
            err = util.extract_error_info(error)
            shutdown_reason = f"error while connecting to {host}:{port} error_message: {err['error_message']} error_code: {err['error_code']}"

        # An error did not occur and the writer was successfully created
        else:
            return writer

        Program.initiate_shutdown(shutdown_reason)
        Program.log(help_message, logging.ERROR)
        return None

    @staticmethod
    async def shutdown_writers(writers):
        for writer in writers.values():
            await writer.shutdown()

    @staticmethod
    async def create_tcp_writer(host, port, ssl_context=None):
        """
        Wrapper around the asyncio.open_connection function with exception
        handling for creating a network connection to host and port.

        @param host           Hostname of the network connection to establish
        @param port           Port of the network connection to establish
        @param ssl_context    Used for creating TCP over SSL connections

        @return an asyncio object used to write data over a network connection
                using TCP
        """

        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port, ssl=ssl_context), timeout=60)

        return writer

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
                f"UDP connection with host-{self.host} and port-{self.port}"
                f"was closed for the following reason [{exc}]"
            )

        else:
            shutdown_reason = (
                f"UDP connection with host-{self.host} and port-{self.port} "
                "was closed"
            )

        Program.initiate_shutdown(shutdown_reason)


class LocalFileWriter:
    """
    Asynchronous local-file writer used when server protocol is FILE.
    """

    _STOP = object()

    def __init__(
            self,
            filepath,
            checkpoint_directory,
            queue_max_size,
            max_retries,
            retry_backoff_seconds,
            enable_test_input,
            ):
        self.filepath = self._validate_filepath(filepath)
        self.checkpoint_directory = Path(checkpoint_directory)
        self.queue = asyncio.Queue(maxsize=queue_max_size)
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self.enable_test_input = enable_test_input

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
                error_code, error_message = getattr(error, "args", (None, error))
                raise OSError(
                        f"failed to create directory '{directory}' for FILE output "
                        f"error_message: {error_message} error_code: {error_code}"
                        ) from error

        if not directory.is_dir():
            raise FileNotFoundError(
                    f"path '{directory}' is not a directory for FILE output"
                    )

        LocalFileWriter._validate_directory_writable(directory)

        if normalized_path.is_symlink():
            raise ValueError(
                    f"filepath '{normalized_path}' cannot be a symlink for FILE output"
                    )

        if normalized_path.is_dir():
            raise IsADirectoryError(
                    f"filepath '{normalized_path}' is a directory, expected a file"
                    )

        LocalFileWriter._validate_existing_file_writable(normalized_path)

        return normalized_path.resolve(strict=False)

    @staticmethod
    def _validate_directory_writable(directory):
        try:
            with NamedTemporaryFile(dir=str(directory), prefix=".dls_perm_", delete=True):
                pass
        except OSError as error:
            error_code, error_message = getattr(error, "args", (None, error))
            raise PermissionError(
                    f"directory '{directory}' is not writable for FILE output "
                    f"error_message: {error_message} error_code: {error_code}"
                    ) from error

    @staticmethod
    def _validate_existing_file_writable(filepath):
        if not filepath.exists():
            return

        try:
            with filepath.open("ab"):
                pass
        except OSError as error:
            error_code, error_message = getattr(error, "args", (None, error))
            raise PermissionError(
                    f"filepath '{filepath}' is not writable for FILE output "
                    f"error_message: {error_message} error_code: {error_code}"
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
        while True:
            item = await self.queue.get()

            if item is self._STOP:
                self.queue.task_done()
                break

            log_type, data = item
            write_success, should_backlog = await self._write_with_retries(
                    data, log_type
                    )
            if not write_success and should_backlog:
                await self._append_backlog(log_type, data)

            self.queue.task_done()

    async def _write_with_retries(self, data, log_type):
        attempts = self.max_retries + 1
        for attempt in range(1, attempts + 1):
            try:
                await asyncio.get_event_loop().run_in_executor(
                        None, self._write_to_file, data
                        )
                return True, False
            except OSError as error:
                error_code, error_message = getattr(error, "args", (None, error))
                if self._is_disk_full_error(error):
                    self._shutdown_for_disk_full(log_type, error)
                    return False, False

                if attempt == attempts:
                    Program.log(
                            f"{log_type} consumer: exhausted FILE write retries for '{self.filepath}' error_message: "
                            f"{error_message} error_code: {error_code}",
                            logging.ERROR,
                            )
                    return False, True

                Program.log(
                        f"{log_type} consumer: FILE write failed (attempt {attempt}/{attempts}) for '"
                        f"{self.filepath}', retrying error_message: {error_message} error_code: {error_code}",
                        logging.WARNING,
                        )
                backoff = (self.retry_backoff_seconds * (2 ** (attempt - 1))) + random.uniform(0, 0.1)
                await asyncio.sleep(backoff)

        return False, True

    def _write_to_file(self, data):
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

        try:
            self.filepath.chmod(0o600)
        except OSError:
            # Best-effort on platforms/filesystems that don't support this mode.
            pass

    async def _append_backlog(self, log_type, data):
        await asyncio.get_event_loop().run_in_executor(
                None, self._append_backlog_sync, log_type, data
                )

    def _append_backlog_sync(self, log_type, data):
        backlog_path = self._backlog_path(log_type)
        try:
            with backlog_path.open("ab") as backlog_file:
                backlog_file.write(data)
        except OSError as error:
            error_code, error_message = getattr(error, "args", (None, error))
            if self._is_disk_full_error(error):
                self._shutdown_for_disk_full(log_type, error)
                return
            Program.log(
                    f"{log_type} consumer: failed to write FILE backlog '{backlog_path}' error_message: "
                    f"{error_message} error_code: {error_code}",
                    logging.ERROR,
                    )
            return

        Program.log(
                f"{log_type} consumer: stored FILE write failure in backlog '{backlog_path}'",
                logging.WARNING,
                )

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
            error_code, error_message = getattr(error, "args", (None, error))
            Program.log(
                    f"{log_type} consumer: failed to read FILE backlog replay file '{replay_path}' error_message: "
                    f"{error_message} error_code: {error_code}",
                    logging.ERROR,
                    )
            return False

    @staticmethod
    def _is_disk_full_error(error):
        disk_full_codes = {errno.ENOSPC}
        if hasattr(errno, "EDQUOT"):
            disk_full_codes.add(errno.EDQUOT)

        error_errno = getattr(error, "errno", None)
        if error_errno is None and getattr(error, "args", None):
            first_arg = error.args[0]
            if isinstance(first_arg, int):
                error_errno = first_arg

        return error_errno in disk_full_codes

    def _shutdown_for_disk_full(self, log_type, error):
        error_code = getattr(error, "errno", None)
        error_message = getattr(error, "strerror", None)
        if not error_message and getattr(error, "args", None):
            error_message = error.args[1] if len(error.args) > 1 else str(error)

        Program.log(
                f"{log_type} consumer: disk full detected for FILE output '{self.filepath}' error_message: "
                f"{error_message} error_code: {error_code}",
                logging.ERROR,
                )
        Program.initiate_shutdown(
                f"{log_type} consumer: disk full for FILE output '{self.filepath}' "
                f"error_message: {error_message} error_code: {error_code}"
                )

    @staticmethod
    def _append_remaining_backlog(backlog_path, remaining_lines):
        with backlog_path.open("ab") as backlog_file:
            for line in remaining_lines:
                backlog_file.write(line)

    def _backlog_path(self, log_type):
        return self.checkpoint_directory / (
                f"{log_type}_file_failed_ingestion_logs.txt"
        )


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
                error_code, error_message = getattr(error, "args")
                Program.log(f"{log_type} producer: error while sending data to {self.hostname}:{self.port} error_message: {error_message} error_code: {error_code}", logging.WARNING)
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
            self.writer.write(data)
            await self.writer.drain()

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
        self.writer.close()
        wait_closed = getattr(self.writer, "wait_closed", None)
        if wait_closed:
            await wait_closed()

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

        Program.log(f"DuoLogSync: Opening connection to {host}:{port} with protocol {self.protocol}",
                    logging.INFO)

        # Message to be logged if an error occurs in this function
        help_message = f"DuoLogSync: check that host-{host} and port-{port} are correct in the configuration file '{Config.get_config_file_path()}'"
        writer = None

        try:
            if self.protocol == "UDP":
                writer = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

            elif self.protocol == "TCPSSL":
                ssl_context = ssl.create_default_context(
                    ssl.Purpose.SERVER_AUTH, cafile=cert_filepath)

                writer = await Writer.create_tcp_writer(host, port, ssl_context)

            elif self.protocol == "TCP":
                writer = await Writer.create_tcp_writer(host, port)

        # Failed to open the certificate file
        except FileNotFoundError as fnf_error:
            error_code, error_message = getattr(fnf_error, "args")
            shutdown_reason = f"certificate file '{cert_filepath}' could not be opened due to error: {error_message} error_code: {error_code}"
            help_message = f"make sure that certificate file '{cert_filepath}' to establish SSL connection is correct."

        # Couldn't establish a connection within 60 seconds
        except asyncio.TimeoutError:
            shutdown_reason = "connection to the destination server timed-out after 60 seconds"

        # If an invalid hostname or port number is given or simply failed to
        # connect using the host and port given
        except (gaierror, OSError) as error:
            error_code, error_message = getattr(error, "args")
            shutdown_reason = f"error while connecting to {host}:{port} error_message: {error_message} error_code: {error_code}"

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

        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, ssl=ssl_context),
            timeout=60
        )

        return writer

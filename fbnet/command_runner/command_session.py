#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# pyre-unsafe

# Copyright (c) Facebook, Inc. and its affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import abc
import asyncio
import logging
import re
import sys
import time
import traceback
import typing
from collections import namedtuple
from dataclasses import dataclass
from functools import wraps
from typing import List

import asyncssh
from fbnet.command_runner.exceptions import (
    AssertionErrorException,
    CommandExecutionTimeoutErrorException,
    ConnectionErrorException,
    ConnectionTimeoutErrorException,
    FcrBaseException,
    LookupErrorException,
    RuntimeErrorException,
    StreamReaderErrorException,
)
from fbnet.command_runner_asyncio.CommandRunner import ttypes

from .base_service import PeriodicServiceTask, ServiceObj
from .device_info import IPInfo
from .options import Option

if typing.TYPE_CHECKING:
    from fbnet.command_runner.service import FcrServiceBase

    from .counters import Counters
    from .device_info import DeviceInfo

# Register additional key exchange algorithms
asyncssh.public_key.register_public_key_alg(
    b"rsa-sha2-256", asyncssh.rsa.RSAKey, default=False
)

log = logging.getLogger("fcr.CommandSession")

ResponseMatch = namedtuple("ResponseMatch", ["data", "matched", "groupdict", "match"])


class PeerInfoList(typing.NamedTuple):
    ip_list: typing.Optional[List[IPInfo]] = []
    port: typing.Optional[typing.Union[int, str]] = None

    def __str__(self) -> str:
        return f"({self.ip_list}, {self.port})"


class PeerInfo(typing.NamedTuple):
    ip: typing.Optional[str] = None
    ip_is_pingable: typing.Optional[bool] = True
    port: typing.Optional[typing.Union[int, str]] = None

    def __str__(self) -> str:
        return f"({self.ip}, {self.ip_is_pingable}, {self.port})"


@dataclass(frozen=False)
class CapturedTimeMS:
    """
    Class for capturing different types of communication and processing times (in ms)
    during an API call. Currently includes external communication time.
    Add additional types of captured time as fields as needed along with
    their relevant increment methods
    """

    # captures external communication time (e.g. establishing SSH connection,
    # waiting for device to feed bytes to the stream, etc.)
    external_communication_time_ms: float = 0.0

    def __add__(self, other):
        return CapturedTimeMS(
            external_communication_time_ms=self.external_communication_time_ms
            + other.external_communication_time_ms
        )

    def __radd__(self, other):
        raise RuntimeErrorException("Can only add CapturedTimeMS objects together")

    def reset_time(self) -> None:
        """
        Resets all captured time to 0.0. Any new added fields must be reset in this method.
        """
        self.external_communication_time_ms = 0.0

    def increment_external_communication_time_ms(self, time_ms: float) -> None:
        self.external_communication_time_ms += time_ms


class LogAdapter(logging.LoggerAdapter):
    def process(
        self, msg: str, kwargs: typing.MutableMapping[str, typing.Any]
    ) -> typing.Tuple[typing.Any, typing.MutableMapping[str, typing.Any]]:
        # pyre-fixme[16]: `object` has no attribute `id`.
        return f"[session_id={self.extra['session'].id}]: {msg}", kwargs


class SessionReaperTask(PeriodicServiceTask):
    SESSION_REAP_PERIOD_S = Option(
        "--session_reap_period",
        help="Interval (in seconds) to cleanup stale or long-idle sessions "
        "(default: %(default)s)",
        type=int,
        default=60,
    )

    MAX_SESSION_IDLE_TIMEOUT_S = Option(
        "--max_session_idle_timeout",
        help="Maximal accepted value (in seconds) for session idle timeout "
        "(default: %(default)s)",
        type=int,
        default=30 * 60,
    )

    MAX_SESSION_LAST_ACCESS_TIMEOUT_S = Option(
        "--max_session_last_access_timeout",
        help="Max time a session can live since last access" "(default: %(default)s)",
        type=int,
        default=60 * 60,
    )

    COUNTER_KEY_REAPED_ALL = "session_reaper.reaped.all"

    def __init__(
        self,
        service: ServiceObj,
        sessions: typing.Optional[
            typing.Dict[typing.Hashable, "CommandSession"]
        ] = None,
    ) -> None:
        super().__init__(
            service, name=self.__class__.__name__, period=self.SESSION_REAP_PERIOD_S
        )
        self._sessions = sessions or CommandSession._ALL_SESSIONS

    @classmethod
    def register_counters(cls, stats_mgr: "Counters") -> None:
        stats_mgr.add_stats_counter(cls.COUNTER_KEY_REAPED_ALL, ["count"])

    def _bump_counters_for_reaped_session(self, session: "CommandSession") -> None:
        self.inc_counter(self.COUNTER_KEY_REAPED_ALL)

    async def run(self) -> None:
        """
        A session is accessed when a command begins executing, and is accessed
        again at the end of execution when it is released. A session is freed if
        1) it's idle for 'idle_timeout' sec after the last command execution;
        OR 2) it exceeds the max session time out since last accessed (this could
        happend when a command get stuck). This would prevent the thrift service
        from holding up open/stale connections to network devices.
        """
        try:
            self.logger.info(
                f"Session reaper woke up: curr_time={time.time()}, "
                f"session_count={len(self._sessions)}"
            )
            for key in list(self._sessions.keys()):
                if key not in self._sessions:
                    # Since this is an async method, it's possible that the session
                    # is closed before being reaped
                    continue
                session = self._sessions[key]
                curr_time = time.time()
                time_since_last_access = curr_time - session.last_access_time
                idle_timeout = min(
                    session.idle_timeout, self.MAX_SESSION_IDLE_TIMEOUT_S
                )
                if time_since_last_access > self.MAX_SESSION_LAST_ACCESS_TIMEOUT_S or (
                    not session.in_use and time_since_last_access > idle_timeout
                ):
                    self.logger.info(
                        f"Reap session {key}, "
                        f"last_access_time={session.last_access_time}, "
                        f"curr_time={curr_time}"
                    )
                    await session.close()
                    if key in self._sessions:
                        del self._sessions[key]
                    self._bump_counters_for_reaped_session(session)
            self.logger.info(
                f"Session reaper finished: session_count={len(self._sessions)}"
            )
        except Exception as ex:
            self.logger.exception(f"Error when reaping session {ex!r}")


def _update_last_access_time_and_in_use(fn: typing.Callable) -> typing.Callable:
    """
    This is a decorator to update the last access time of the session before and
    after calling the wrapped function
    NOTE: This is for internal use only within CommandSession
    """

    @wraps(fn)
    async def wrapper(self, *args, **kwargs):
        self._in_use_count += 1
        self._last_access_time = time.time()
        try:
            return await fn(self, *args, **kwargs)
        finally:
            self._in_use_count -= 1
            self._last_access_time = time.time()

    return wrapper


class CommandSession(ServiceObj):
    """
    A session for running commands on devices. Before running a command a
    CommandSession needs to be created. The connection to the device is
    established asynchronously, The user should wait for the session to
    be connected before trying to send commands to the device.

    Once a session is established, a set of read and write streams will be
    associated with the session.
    """

    _ALL_SESSIONS: typing.Dict[typing.Hashable, "CommandSession"] = {}

    # the prompt is at the end of input. So rather then searching in the entire
    # buffer, we will only look in the trailing data
    _MAX_PROMPT_SIZE = 100

    def __init__(
        self,
        service: "FcrServiceBase",
        devinfo: "DeviceInfo",
        options: typing.Dict[str, typing.Any],
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        # Setup devinfo as this is needed to create the logger
        self._devinfo = devinfo

        super().__init__(service)

        self._opts = options

        self.device = self._opts.get("device")
        self._extra_options = (
            self.device
            and self.device.session_data
            and self.device.session_data.extra_options
        ) or {}

        self._hostname = devinfo.hostname
        self._pre_setup_commands: typing.List[str] = (
            (self.device.pre_setup_commands or []) if self.device else []
        )

        self._extra_info = {}
        self._exit_status = None

        # use the specified username/password passed in by user
        self._username = options.get("username")
        self._password = options.get("password")
        self._client_ip = options["client_ip"]
        self._client_port = options["client_port"]
        self._loop = loop

        # TODO: remove _cmd_stream from the base class CommandSession (some
        # session type, e.g., rpc base session, does not need this property)
        self._cmd_stream = None
        self._connected = False
        self.__event = None

        self.logger.info("Created key=%s", self.key)
        # Record the session in the cache
        self._ALL_SESSIONS[self.key] = self

        self._last_access_time: float = time.time()
        self._in_use_count: int = 0
        self._open_time_ms: int = 0

        # captures various types of communication and processing times
        # including external communication time
        self._captured_time_ms: CapturedTimeMS = CapturedTimeMS()

    @property
    def _event(self):
        if self.__event is None:
            self.__event = asyncio.Condition()
        return self.__event

    def get_session_name(self) -> str:
        return self.objname

    def get_peer_info(self) -> typing.Optional[PeerInfo]:
        return self._extra_info.get("peer")

    def get_peer_info_list(self) -> typing.Optional[PeerInfoList]:
        return self._extra_info.get("peer_list")

    def create_logger(self) -> LogAdapter:
        logger = logging.getLogger(
            "fcr.{klass}.{dev.vendor_name}.{dev.hostname}".format(
                klass=self.__class__.__name__, dev=self._devinfo
            )
        )

        return LogAdapter(logger, {"session": self})

    def build_result(
        self, output: str, status: str, command: str
    ) -> ttypes.CommandResult:
        return ttypes.CommandResult(output=output, status=status, command=command)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__} [{self._devinfo.hostname}] [{self.id}]"

    @classmethod
    def register_counters(cls, stats_mgr: "Counters") -> None:
        stats_mgr.register_counter(f"{cls.__name__}.setup")
        stats_mgr.register_counter(f"{cls.__name__}.connected")
        stats_mgr.register_counter(f"{cls.__name__}.failed")
        stats_mgr.register_counter(f"{cls.__name__}.closed")

    @classmethod
    def get_session_count(cls) -> int:
        return len(cls._ALL_SESSIONS)

    @classmethod
    async def wait_sessions(cls, req_name: str, service: ServiceObj) -> None:
        session_count = cls.get_session_count()

        while session_count != 0:
            await asyncio.sleep(1, loop=service.loop)
            session_count = cls.get_session_count()
            service.logger.info(f"{req_name}: pending sessions: {session_count}")

        service.logger.info(f"{req_name}: no pending sesison")

    async def __aenter__(self) -> "CommandSession":
        try:
            open_connection_time = time.perf_counter()
            await self.setup()
        except Exception as e:
            await self.close()
            raise self._build_session_exc(e) from e
        finally:
            self._open_time_ms = int(
                (time.perf_counter() - open_connection_time) * 1000
            )

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()
        if exc_val:
            raise self._build_session_exc(exc_val) from exc_val

    def _build_session_exc(self, exc: Exception) -> Exception:
        """
        Builds a new exception of the same type as exc
        Contains original exception's message plus additional messages.
        """
        peer_info = self.get_peer_info()
        msg = f"Failed (session: {self.get_session_name()}, peer: {peer_info})"

        if isinstance(peer_info, PeerInfo) and not peer_info.ip_is_pingable:
            msg += ", IP used in this connection is not pingable according to NetSonar"

        # Append message as new arg instead of constructing new exception
        # to account for exceptions having different required args
        exc.args = exc.args + (msg,)

        return exc

    @classmethod
    def get(cls, session_id: int, client_ip: str, client_port: int) -> "CommandSession":
        key = (session_id, client_ip, client_port)
        try:
            return cls._ALL_SESSIONS[key]
        except KeyError as ke:
            raise LookupErrorException("Session not found", key) from ke

    @property
    def hostname(self) -> str:
        return self._hostname

    @property
    def username(self) -> str:
        return self._username

    @property
    def devinfo(self):
        return self._devinfo

    @property
    def id(self) -> int:
        return id(self)

    @property
    def key(self) -> typing.Tuple[int, str, int]:
        return (self.id, self._client_ip, self._client_port)

    @property
    def open_timeout(self) -> int:
        return self._opts.get("open_timeout")

    @property
    def open_time_ms(self) -> int:
        return self._open_time_ms

    @property
    def use_mgmt_ip(self) -> bool:
        return self._opts.get("mgmt_ip")

    @property
    def idle_timeout(self) -> int:
        return self._opts.get("idle_timeout")

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def last_access_time(self) -> float:
        return self._last_access_time

    @property
    def in_use(self) -> bool:
        return self._in_use_count > 0

    @property
    def exit_status(self) -> int:
        return self._exit_status

    @property
    def captured_time_ms(self) -> CapturedTimeMS:
        return self._captured_time_ms

    async def _create_connection(self) -> None:
        await self.connect()

    @_update_last_access_time_and_in_use
    async def setup(self) -> "CommandSession":
        self.inc_counter(f"{self.objname}.setup")
        try:
            await asyncio.wait_for(self._create_connection(), self.open_timeout)
        except asyncio.TimeoutError:
            self.logger.exception("Timeout during connection setup")
            data = []
            # TODO(mzheng): Move the _steam_reader check to subclasses that
            # define it
            # pyre-fixme
            if hasattr(self, "_stream_reader") and self._stream_reader:
                data = await self._stream_reader.drain()
            raise ConnectionTimeoutErrorException(
                "Timeout during connection setup. Currently received data "
                f"(last 200 char): {data[-200:]}"
            )
        return self

    async def connect(self) -> None:
        """
        Initiates a connection on the session
        """
        try:
            self._cmd_stream = await self._connect()
            self.inc_counter(f"{self.objname}.connected")
            self.logger.info(f"Connected: {self._extra_info}")
        except Exception as e:
            self.logger.error(f"Connect Failed {e!r}")
            self.inc_counter(f"{self.objname}.failed")
            if isinstance(e, FcrBaseException):
                raise
            raise ConnectionErrorException(repr(e)) from e

    async def close(self) -> None:
        """
        Close the session. This removes the session from the cache. Also
        invokes the session specific _close method
        """
        try:
            self.logger.debug("Closing session")
            if self.key in self._ALL_SESSIONS:
                del self._ALL_SESSIONS[self.key]
        finally:
            await self._close()
            if self._cmd_stream is not None:
                self._cmd_stream.close()
            self._connected = False
            self.inc_counter(f"{self.objname}.closed")

    @_update_last_access_time_and_in_use
    async def run_command(
        self,
        command: bytes,
        timeout: typing.Optional[int] = None,
        prompt_re: typing.Optional[typing.Pattern] = None,
    ) -> bytes:
        return await self._run_command(
            command=command, timeout=timeout, prompt_re=prompt_re
        )

    @abc.abstractmethod
    async def _connect(self) -> None:
        """
        This needs to be implemented by the actual session classes
        """
        pass

    @abc.abstractmethod
    async def _close(self) -> None:
        """
        This needs to be implemented by the actual session classes
        """
        pass

    @abc.abstractmethod
    async def _run_command(
        self,
        command: bytes,
        timeout: typing.Optional[int] = None,
        prompt_re: typing.Optional[typing.Pattern] = None,
    ) -> bytes:
        """
        This needs to be implemented by the actual session classes
        """
        pass

    async def wait_until_connected(self, timeout: typing.Optional[int] = None) -> None:
        """
        Wait until the session is marked as connected
        """
        try:
            await self.wait_for(lambda _: self._connected, timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise ConnectionTimeoutErrorException(
                "Timed out before session marked as connected"
            ) from exc

    async def _notify(self) -> None:
        """
        notify a change in stream state
        """
        await self._event.acquire()
        self._event.notify_all()
        self._event.release()

    async def wait_for(
        self, predicate: typing.Callable, timeout: typing.Optional[int] = None
    ) -> None:
        """
        Wait for condition to become true on the session
        """
        await self._event.acquire()
        await asyncio.wait_for(
            self._event.wait_for(lambda: predicate(self)),
            timeout=timeout,
        )
        self._event.release()


class CommandStreamReader(asyncio.StreamReader):
    """
    A Reader for commmand responses

    Extends the asyncio.StreamReader and adds support for waiting for regex
    match on received data
    """

    QUICK_COMMAND_RUNTIME = 1
    COMMAND_DATA_TIMEOUT = 1

    def __init__(self, session: CommandSession, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._session = session
        self._last_feed_data_call_time_s: float = 0.0

    @property
    def logger(self) -> LogAdapter:
        return self._session.logger

    def feed_data(self, data: bytes) -> None:
        feed_data_call_time_s = time.perf_counter()

        # only increment external time if there was a last call time & session's cmd_stream not None
        # (i.e. _connect done, so not simultaneously capturing session connection time in _connect)
        if self._last_feed_data_call_time_s and self._session._cmd_stream:
            self._session.captured_time_ms.increment_external_communication_time_ms(
                (feed_data_call_time_s - self._last_feed_data_call_time_s) * 1000
            )

        # Only update last call time if cmd_stream not None (i.e. _connect done)
        # to prevent overlapping captured time with _connect (which may also call feed_data).
        # If feed_data is called for the first time without going through wait_for,
        # this will also start capturing the time for those non-wait_for feed_data calls.
        if self._session._cmd_stream:
            self._last_feed_data_call_time_s = feed_data_call_time_s

        return super().feed_data(data)

    async def wait_for(
        self, predicate: typing.Callable, timeout: typing.Optional[int] = None
    ) -> typing.Match:
        """
        Wait for the predicate to become true on the stream. As and when new
        data is available, the predicate will be re-evaluated.
        """

        if self._exception is not None:  # pyre-ignore
            raise StreamReaderErrorException(repr(self._exception)) from self._exception

        res = predicate(self._buffer)  # pyre-ignore

        start_ts = time.time()
        # Set an initial time so that first call to feed_data has a
        # reference from which to capture how much time has passed
        self._last_feed_data_call_time_s = time.perf_counter()

        while res is None:
            now = time.time()

            # Here we add a protection to avoid this function from doing infinite regex matching
            # This will ensure that we will eventually break out from the while loop if timeout
            # is set
            if timeout and now - start_ts >= timeout:
                raise CommandExecutionTimeoutErrorException(
                    "FCR timeout during matching regex against current buffer output from device."
                )

            self.logger.debug(
                f"match failed in: {len(self._buffer)}: {self._limit}: {self._buffer[-100:]}"  # pyre-ignore
            )
            self._session.inc_counter("streamreader.wait_for_retry")

            if len(self._buffer) > self._limit:
                self._session.inc_counter("streamreader.overrun")
                raise StreamReaderErrorException(
                    "Reader buffer overrun: %d: %d" % (len(self._buffer), self._limit)
                )

            if now - start_ts > self.QUICK_COMMAND_RUNTIME:
                # Keep waiting for data till we get a timeout
                try:
                    while True:
                        fut = self._wait_for_data(  # pyre-ignore
                            "CommandStreamReader.wait_for"
                        )
                        await asyncio.wait_for(
                            fut,
                            timeout=self.COMMAND_DATA_TIMEOUT,
                        )
                except asyncio.TimeoutError:
                    # Now try to match the prompt
                    pass
            else:
                # match quickly initially
                await self._wait_for_data("CommandStreamReader.wait_for")

            res = predicate(self._buffer)

        self.logger.debug("match found at: %s", res)

        # Reset last_feed_data_call_time_s to 0.0 so that in case of a later call to feed_data
        # that doesn't go through wait_for, we don't accidentally capture the time from now until then
        self._last_feed_data_call_time_s = 0.0

        return res

    def _search_re(
        self, regex: typing.Pattern, data: bytes, start: int = 0
    ) -> typing.Optional[typing.Match]:
        self.logger.debug(f"searching for: {regex}")
        return regex.search(data, start)

    async def readuntil_re(
        self,
        regex: typing.Pattern,
        timeout: typing.Optional[int] = None,
        start: int = 0,
    ) -> ResponseMatch:
        """
        Read data until a regex is matched on the input stream
        """
        self.logger.debug("readuntil_re: %s", regex)

        try:
            match = await self.wait_for(lambda data: regex.search(data, start), timeout)

            m_beg, m_end = match.span()
            # We are matching against the data stored stored in bytebuffer
            # The bytebuffer is manipulated in place. After we read the data
            # the buffer may get overwritten. The match object seems to be
            # directly referring the data in bytebuffer. This causes a problem
            # when we try to find the matched groups in match object.
            #
            # In [38]: data = bytearray(b"localhost login:")
            #
            # In [39]: rex = re.compile(b'(?P<login>.*((?<!Last ).ogin|.sername):)|(?P<passwd>\n.*assword:)|(?P<prompt>\n.*[%#>])|(?P<ignore>( to cli \\])|(who is on this device.\\]\r\n)|(Press R
            #     ...: ETURN to get started\r\n))\\s*$')
            #
            # In [40]: m = rex.search(data)
            #
            # In [41]: m.groupdict()
            # Out[41]: {'ignore': None, 'login': b'localhost login:', 'passwd': None, 'prompt': None}
            #
            # In [42]: data[:]=b'overwrite'
            #
            # In [43]: m.groupdict()
            # Out[43]: {'ignore': None, 'login': b'overwrite', 'passwd': None, 'prompt': None}
            #
            groupdict = match.groupdict()
            rdata = await self.read(m_end)
            data = rdata[:m_beg]  # Data before the regex match
            matched = rdata[m_beg:m_end]  # portion that matched regex
        except AssertionError as exc:
            if self._eof:  # pyre-ignore
                # We are at the EOF. Read the whole buffer and send it back
                data = await self.read(len(self._buffer))  # pyre-ignore
                matched = b""
                match = None
                groupdict = None
            else:
                # re-raise the exception
                raise AssertionErrorException(str(exc)) from exc

        return ResponseMatch(data, matched, groupdict, match)

    async def drain(self) -> bytes:
        """
        Drain the read buffer. Typically used before sending a new commands to
        make sure the stream in in sane state
        """
        return await self.read(len(self._buffer))  # pyre-ignore


class CommandStream(asyncio.StreamReaderProtocol):

    # TODO: make this tweakable from configerator
    _BUFFER_LIMIT = 100 * (2**20)  # 100M

    def __init__(
        self, session: "CliCommandSession", loop: asyncio.AbstractEventLoop
    ) -> None:
        super().__init__(
            CommandStreamReader(session, limit=self._BUFFER_LIMIT, loop=loop),
            client_connected_cb=self._on_connect,
            loop=loop,
        )
        self._session = session
        self._loop = loop

    def _on_connect(
        self, stream_reader: asyncio.StreamReader, stream_writer: asyncio.StreamWriter
    ) -> None:
        """
        called when transport is connected
        """
        # Sometimes the remote side doesn't send the newline for the first
        # prompt. This causes our prompt matching to fail. Here we inject a
        # newline to normalize these cases. This keeps our prompt processing
        # simple.
        super().data_received(b"\n")
        self._session._session_connected(stream_reader, stream_writer)

    def close(self) -> None:
        if self._stream_writer:  # pyre-ignore
            self._stream_writer.close()

    def data_received(self, data: bytes, datatype=None) -> None:
        # TODO: check if we need to handle stderr data separately
        # for stderr data: datatype == EXTENDED_DATA_STDERR
        return super().data_received(data)

    def session_started(self) -> None:
        # Not used yet. But needs to be defined
        pass

    def exit_status_received(self, status: str) -> None:
        self._session.exit_status_received(status)


class CliCommandSession(CommandSession):
    """
    A command session for CLI commands. Does prompt processing on the command stream.
    """

    _SPECIAL_CHAR_REGEX = re.compile(rb".\x08|\x07")
    _NEWLINE_REPLACE_REGEX = re.compile(rb"(\r+\n)|(\n\r+)|\r")

    def __init__(
        self,
        service: "FcrServiceBase",
        devinfo: "DeviceInfo",
        options: typing.Dict[str, typing.Any],
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        super().__init__(service, devinfo, options, loop)

        self._cmd_stream = None
        self._stream_reader = None  # for reading data from device
        self._stream_writer = None  # for writing data to the device
        # TODO: investigate if we need an error stream

    @classmethod
    def register_counters(cls, stats_mgr: "Counters") -> None:
        super().register_counters(stats_mgr)
        stats_mgr.register_counter("streamreader.wait_for_retry")
        stats_mgr.register_counter("streamreader.overrun")
        stats_mgr.register_counter("streamreader.overrun")

    async def _setup_connection(self) -> None:
        # At this point login process should already be complete. If a
        # particular session needs to send password, it should override this
        # method and complete the login before calling this method
        await self.wait_prompt()
        for cmd in self._pre_setup_commands:
            self.logger.debug(f"Sending pre setup command: {cmd}")
            await self.run_command(cmd.encode("utf-8") + b"\n")
        for cmd in self._devinfo.vendor_data.cli_setup:
            self.logger.debug(f"Sending setup command: {cmd}")
            await self.run_command(cmd + b"\n")

    async def _create_connection(self) -> None:
        await super()._create_connection()
        await self.wait_until_connected(self.open_timeout)
        await self._setup_connection()

    async def wait_prompt(
        self,
        prompt_re: typing.Optional[typing.Pattern] = None,
        timeout: typing.Optional[int] = None,
    ) -> ResponseMatch:
        """
        Wait for a prompt
        """
        return await self._stream_reader.readuntil_re(
            prompt_re or self._devinfo.prompt_re,
            timeout,
            -self._MAX_PROMPT_SIZE,
        )

    async def _wait_response(
        self, prompt_re: typing.Pattern, timeout: int
    ) -> ResponseMatch:
        """
        Wait for command response from the device
        """
        self.logger.debug("Waiting for prompt")
        resp = await self.wait_prompt(prompt_re=prompt_re, timeout=timeout)
        return resp

    def _fixup_whitespace(self, output: bytes) -> bytes:
        # we need to sanitize the output to remove '\r' and other chars.
        # List of chars that will be removed
        #        ' *\x08+': space* followed by backspace characters
        #          '\x07' : BEL(bell) char
        output = self._SPECIAL_CHAR_REGEX.sub(b"", output)

        #
        # We need to apply following transforms
        #   '\r+\n' -> '\n'
        #   '\n\r+' -> '\n'
        #   '\r' -> '\n'     standalone \r
        output = self._NEWLINE_REPLACE_REGEX.sub(b"\n", output)

        return output.strip()

    def _format_output(self, cmd: bytes, resp: ResponseMatch) -> bytes:
        """
        Format the output to comply with following format

            <prompt> <command>
            command-output
            ...

        In addition '\r\n' | '\n\r' | '\r' will be replace with '\n'

        """
        cmd_words = cmd.split()

        # Fixup the white spaces first, as some devices are inserting backspace
        # characters in the command echo
        cmd_output = self._fixup_whitespace(resp.data)

        # Command regex in the output
        # [SPACE]{Command string}[SPACE]
        # The words in the command string can be separated by mulitple spaces.
        # for e.g regex for matching 'show version' command would be
        #    b'^\s*show\s+version\s*$'
        # We also need to escape the words to handle characters like '|'
        cmd_words_esc = (re.escape(w) for w in cmd_words)
        cmd_re = rb"^\s*" + rb"\s+".join(cmd_words_esc) + rb"([ \t]*\n)*"

        # Now replace the 'command string' in the output with a sanitized
        # version (redundant spaces removed)
        # '  show  version  '  ==>  'show version'
        cmd_output = re.sub(cmd_re, b" ".join(cmd_words) + b"\n", cmd_output, 1, re.M)

        # Now we need to prepend the prompt to the command output. The prompt is
        # the matched part in the 'resp'
        output = resp.matched.strip() + b" " + cmd_output

        return output

    async def _run_command(
        self,
        command: bytes,
        timeout: typing.Optional[int] = None,
        prompt_re: typing.Optional[typing.Pattern] = None,
    ) -> bytes:
        """
        Run a command and return response to user
        """
        if not self._connected:
            raise RuntimeErrorException(
                "Not Connected", f"status: {self.exit_status!r}", self.key
            )

        # Ideally there should be no data on the stream. We will in any case
        # drain any stale data. This is mostly for debugging and making sure
        # that we are in sane state
        stale_data = await self._stream_reader.drain()
        if len(stale_data) != 0:
            self.logger.warning(f"Stale data on session: {stale_data}")

        output = []

        commands = command.splitlines()
        for command in commands:
            cmdinfo = self._devinfo.get_command_info(
                command,
                self._opts.get("command_prompts"),
                self._opts.get("clear_command"),
            )

            self.logger.info(f"RUN: {cmdinfo.cmd!r}")

            # Send any precmd data (e.g. \x15 to clear the commandline)
            if cmdinfo.precmd:
                self._stream_writer.write(cmdinfo.precmd)

            self._stream_writer.write(cmdinfo.cmd)

            try:
                prompt = prompt_re or cmdinfo.prompt_re
                cmd_timeout = timeout or self._devinfo.vendor_data.cmd_timeout_sec
                resp = await asyncio.wait_for(
                    self._wait_response(prompt, cmd_timeout),
                    cmd_timeout,
                )
                output.append(self._format_output(command, resp))
            except asyncio.TimeoutError:
                self.logger.error("Timeout waiting for command response")
                data = await self._stream_reader.drain()
                raise CommandExecutionTimeoutErrorException(
                    "Command Response Timeout", data[-200:]
                )

        return b"\n".join(output).rstrip()

    def _session_connected(
        self, stream_reader: asyncio.StreamReader, stream_writer: asyncio.StreamWriter
    ) -> None:
        """
        This called once the session is connected to the transport.
        stream_reader and stream_writer are used for receiving and sending
        data on the session
        """
        self._stream_reader = stream_reader
        self._stream_writer = stream_writer
        self._connected = True

        # Notify anyone waiting for session to be connected
        self._loop.create_task(self._notify())

    def exit_status_received(self, status: str) -> None:
        self.logger.info(f"exit status received: {status}")
        self._connected = False
        self._exit_status = str(status)


class SSHCommandClient(asyncssh.SSHClient):
    """
    The connection objects are leaked if the session timeout while the
    authentication is in progres. The fix ideally needs to be implemented in
    asyncssh. For now we are adding a workaround in FCR. We will save the
    connection object when we get a connection_made callback. This will be used
    to close the connection when we close the session.
    """

    def __init__(self, session: "SSHCommandSession") -> None:
        super().__init__()
        self._session = session

    def connection_made(self, conn: asyncssh.SSHClientConnection) -> None:
        super().connection_made(conn)
        self._session.connection_made(conn)


class SSHCommandSession(CliCommandSession):
    TERM_TYPE: typing.Optional[str] = "vt100"

    def __init__(
        self,
        service: "FcrServiceBase",
        devinfo: "DeviceInfo",
        options: typing.Dict[str, typing.Any],
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        super().__init__(service, devinfo, options, loop)

        self._conn = None
        self._chan = None

    def connection_made(self, conn: asyncssh.SSHClientConnection) -> None:
        s = conn.get_extra_info("socket")
        self._extra_info["fd"] = s.fileno()
        self._extra_info["sockname"] = conn.get_extra_info("sockname")
        self._conn = conn

    def _client_factory(self) -> SSHCommandClient:
        return SSHCommandClient(self)

    async def dest_info(self) -> typing.Tuple[List[IPInfo], int, str, str]:
        ip_list = self.service.ip_utils.get_ip(
            options=self._opts, devinfo=self._devinfo, service=self.service
        )
        port = int(
            self._extra_options.get("port") or self._devinfo.vendor_data.get_port()
        )
        return (ip_list, port, self._username, self._password)

    # pyre-fixme: Inconsistent override
    async def _connect(
        self,
        subsystem: typing.Optional[str] = None,
        exec_command: typing.Optional[str] = None,
    ) -> asyncssh.SSHTCPSession:
        """
        Some session types require us to run a command to start a session. The
        SSH protocol defines three ways to start a session.
        1. shell: this starts a regular user shell on the remote system. This is
                  the most common way of using SSH. If none of 'subsystem' or
                  'command' is specified, this is the method that we use.

        2. exec: Here we specify the command we want to run on remote system.
                 This allows the user start a custom shell. For example run
                 a 'netconf' command to start netconf session

        3. subsystem: Here instead of running a comman we specify a subsystems
                      that has been configured on the remote system. These are
                      predefined systems

        see sec 6.5 https://tools.ietf.org/html/rfc4254 for more details
        """
        ip_list, port, user, passwd = await self.dest_info()
        self.logger.debug(f"Order in which ips will be tried: {ip_list}")
        self._extra_info["peer_list"] = PeerInfoList(ip_list, port)
        if self.device and not self.device.failover_to_backup_ips:
            # Use the first IP in the list if failover is not enabled
            ip, ip_is_pingable = ip_list[0]
            try:
                return await self._connect_to_ip(
                    ip,
                    port,
                    user,
                    passwd,
                    subsystem,
                    exec_command,
                )
            finally:
                self._extra_info["peer"] = PeerInfo(ip, ip_is_pingable, port)

        ips_tried = []
        for index, (ip, ip_is_pingable) in enumerate(ip_list):
            try:
                return await self._connect_to_ip(
                    ip,
                    port,
                    user,
                    passwd,
                    subsystem,
                    exec_command,
                )
            except Exception as e:
                self.logger.exception(f"Connection to {ip} failed")
                ips_tried.append(ip)
                # Raise the last exception in the iteration
                if index == len(ip_list) - 1:
                    msg = f"IPs that failed to connect: {ips_tried}"
                    # Gather the information from the original exception:
                    exc_type, exc_value, exc_traceback = sys.exc_info()
                    traceback_string = "".join(
                        traceback.format_exception(exc_type, exc_value, exc_traceback)
                    )
                    # Re-raise a new exception of the same class as the original one,
                    # using custom message and the original traceback
                    if isinstance(e, asyncssh.misc.DisconnectError):
                        raise type(e)(code=e.code, reason=f"{msg}:{e.reason}")
                    raise type(e)(f"{msg}:{traceback_string}")
            finally:
                self._extra_info["peer"] = PeerInfo(ip, ip_is_pingable, port)

        raise LookupErrorException(
            f"No Valid IP address was found for the device {self._hostname}: {ip_list}"
        )

    async def _connect_to_ip(
        self,
        ip: str,
        port: int,
        user: str,
        passwd: str,
        subsystem: typing.Optional[str] = None,
        exec_command: typing.Optional[str] = None,
    ) -> asyncssh.SSHTCPSession:
        if self.service.ip_utils.proxy_required(ip):
            host = self.service.get_http_proxy_url(ip)
        elif self.service.ip_utils.should_nat(ip, self.service):
            host = await self.service.ip_utils.translate_address(ip, self.service)
        else:
            host = ip

        self.logger.info("Connecting to: %s: %d", host, port)

        open_connection_time_s = time.perf_counter()

        # known_hosts is set to None to disable the host verifications. Without
        # this the connection setup fails for some devices
        conn, _ = await asyncssh.create_connection(
            self._client_factory,
            host=host,
            port=port,
            username=user,
            password=passwd,
            client_keys=None,
            known_hosts=None,
        )

        chan, cmd_stream = await self._conn.create_session(
            lambda: CommandStream(self, self._loop),
            encoding=None,
            term_type=self.TERM_TYPE,
            subsystem=subsystem,
            command=exec_command,
        )
        self._chan = chan
        end_connection_time_s = time.perf_counter()
        self.captured_time_ms.increment_external_communication_time_ms(
            (end_connection_time_s - open_connection_time_s) * 1000
        )
        return cmd_stream

    async def _close(self) -> None:
        if self._chan is not None:
            self._chan.close()
        if self._conn is not None:
            self._conn.close()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) Facebook, Inc. and its affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import asyncio
import typing

from fbnet.command_runner import command_session

# pyre-fixme[21]: Could not find name `IPInfo` in `fbnet.command_runner.device_info`.
from fbnet.command_runner.device_info import IPInfo

if typing.TYPE_CHECKING:
    # pyre-fixme[21]: Could not find module `fbnet.command_runner.counters`.
    from fbnet.command_runner.counters import Counters


class MockCommandTransport(asyncio.Transport):

    _COMMAND_OUTPUTS: typing.Dict[bytes, bytes] = {
        b"\x15": b"",
        b"en\n": b"en\n$",
        b"term width 511\n": b"term width 511\n$",
        b"term len 0\n": b"term len 0\n$",
        b"test1\n": b"""test1
Mock response for test1
$""",
        b"show version\n": b"""show version
Mock response for show version
$""",
        b"command timeout\n": b"""command timeout
Mock response for command timeout""",
        b"user prompt test\n": b"""user prompt test
Test for user prompts
<<<User Magic Prompt>>>""",
    }

    def __init__(
        self,
        mock_options: typing.Dict[str, typing.Any],
        protocol_factory: typing.Callable,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        super().__init__()
        self._options = mock_options
        self._protocol = protocol_factory()
        self._protocol.connection_made(self)
        self._loop = loop
        self._prompt = b"\n$"

        self._recv_data(self._prompt, self.prompt_delay())

    def prompt_delay(self) -> int:
        return self._options.get("prompt_delay", 0)

    def command_delay(self) -> int:
        return self._options.get("command_delay", 0)

    def _gen_cmd_response(self, cmd: bytes) -> bytes:
        return self._COMMAND_OUTPUTS[cmd]

    def _recv_data(self, data: bytes, delay: float = 0.1) -> None:
        self._loop.call_later(delay, self._protocol.data_received, data)

    def _run_command(self, cmd: bytes) -> None:
        # Echo back the command
        response = self._gen_cmd_response(cmd)
        self._recv_data(response, self.command_delay())

    def write(self, data: bytes) -> None:
        self._run_command(data)

    def close(self) -> None:
        pass


class MockSessionFactory:
    def __init__(
        self,
        mock_options: typing.Dict[str, typing.Any],
        session_class: typing.Type["MockCommandSession"],
    ) -> None:
        self._mock_options = mock_options
        self._session_class = session_class

    def __call__(self, *args, **kwargs) -> "MockCommandSession":
        return self._session_class(self._mock_options, *args, **kwargs)

    # pyre-fixme[11]: Annotation `Counters` is not defined as a type.
    def register_counters(self, counter_mgr: "Counters") -> None:
        pass


class MockCommandSession(command_session.CliCommandSession):
    """
    A mock commands session used for testing
    """

    def __init__(
        self, mock_options: typing.Dict[str, typing.Any], *args, **kwargs
    ) -> None:
        super().__init__(*args, **kwargs)

        self._mock_options = mock_options
        self.connect_called = False
        self.close_called = False
        self._transport = None
        self._cmd_stream = None

    def set_option(self, opt: str, value: typing.Any) -> None:
        self._mock_options[opt] = value

    def _delayed_connect(self) -> None:
        self.connect_called = True
        # Declare the session as connected
        self._cmd_stream = command_session.CommandStream(self, loop=self._loop)
        self._transport = MockCommandTransport(
            self._mock_options, lambda: self._cmd_stream, loop=self._loop
        )

    async def _connect(self) -> None:
        self._extra_info["peer_list"] = command_session.PeerInfoList(
            # pyre-fixme[16]: Module `device_info` has no attribute `IPInfo`.
            [IPInfo("test-ip", True)],
            22,
        )
        # pyre-fixme[6]: For 3rd argument expected `Optional[bool]` but got `int`.
        self._extra_info["peer"] = command_session.PeerInfo("test-ip", True, 22)
        if self._mock_options.get("connect_drop", False):
            return
        delay = self._mock_options.get("connect_delay", 0)
        self._loop.call_later(delay, self._delayed_connect)

    async def _close(self) -> None:
        self.close_called = True

    async def _run_command(self, *args, **kwargs) -> bytes:
        run_error = self._mock_options.get("run_error", False)
        if run_error:
            raise IOError("Run Error")
        else:
            return await super()._run_command(*args, **kwargs)

    @classmethod
    def Factory(cls, mock_options) -> MockSessionFactory:
        return MockSessionFactory(mock_options, MockCommandSession)

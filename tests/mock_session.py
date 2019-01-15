#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2017-present, Facebook, Inc.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree. An additional grant
# of patent rights can be found in the PATENTS file in the same directory.
#

import asyncio

from fbnet.command_runner import command_session


class MockCommandTransport(asyncio.Transport):

    _COMMAND_OUTPUTS = {
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

    def __init__(self, mock_options, protocol_factory, loop):
        super().__init__()
        self._options = mock_options
        self._protocol = protocol_factory()
        self._protocol.connection_made(self)
        self._loop = loop
        self._prompt = b"\n$"

        self._recv_data(self._prompt, self.prompt_delay())

    def prompt_delay(self):
        return self._options.get("prompt_delay", 0)

    def command_delay(self):
        return self._options.get("command_delay", 0)

    def _gen_cmd_response(self, cmd):
        return self._COMMAND_OUTPUTS[cmd]
        response = b"""Mock response for %s\n"""
        return response % cmd.strip()

    def _recv_data(self, data, delay=0.1):
        self._loop.call_later(delay, self._protocol.data_received, data)

    def _run_command(self, cmd):
        # Echo back the command
        response = self._gen_cmd_response(cmd)
        self._recv_data(response, self.command_delay())

    def write(self, data):
        self._run_command(data)

    def close(self):
        pass


class MockSessionFactory:
    def __init__(self, mock_options, session_class):
        self._mock_options = mock_options
        self._session_class = session_class

    def __call__(self, *args, **kwargs):
        return self._session_class(self._mock_options, *args, **kwargs)

    def register_counters(self, counter_mgr):
        pass


class MockCommandSession(command_session.CliCommandSession):
    """
    A mock commands session used for testing
    """

    def __init__(self, mock_options, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._mock_options = mock_options
        self.connect_called = False
        self.close_called = False
        self._transport = None
        self._cmd_stream = None

    def set_option(self, opt, value):
        self._mock_options[opt] = value

    def _delayed_connect(self):
        self.connect_called = True
        # Declare the session as connected
        self._cmd_stream = command_session.CommandStream(self, loop=self._loop)
        self._transport = MockCommandTransport(
            self._mock_options, lambda: self._cmd_stream, loop=self._loop
        )

    async def _connect(self):
        self._extra_info["peer"] = command_session.PeerInfo("test-ip", 22)
        if self._mock_options.get("connect_drop", False):
            return
        delay = self._mock_options.get("connect_delay", 0)
        self._loop.call_later(delay, self._delayed_connect)

    async def _close(self):
        self.close_called = True

    async def run_command(self, *args, **kwargs):
        run_error = self._mock_options.get("run_error", False)
        if run_error:
            raise IOError("Run Error")
        else:
            return await super().run_command(*args, **kwargs)

    @classmethod
    def Factory(cls, mock_options):
        return MockSessionFactory(mock_options, MockCommandSession)

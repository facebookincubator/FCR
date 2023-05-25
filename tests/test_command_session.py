#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) Facebook, Inc. and its affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import logging
import typing

import unittest.mock as mock

from fbnet.command_runner.command_session import CommandSession
from fbnet.command_runner.exceptions import (
    CommandExecutionTimeoutErrorException,
    ConnectionTimeoutErrorException,
    LookupErrorException,
    RuntimeErrorException,
)

from .mock_session import MockCommandSession
from .mocks import MockService
from .testutil import async_test, AsyncTestCase


log = logging.getLogger()


class CommandSessionTest(AsyncTestCase):
    def setUp(self) -> None:
        super().setUp()

        self.mock_options = {}
        self.mocks = MockService(self.mock_options, self._loop)

        test_device = self.mock_device("test-dev-1")
        self.devinfo = self._run_loop(self.mocks.device_db.get(test_device))[0]

        self.options = {
            "client_ip": "10.10.10.10",
            "client_port": 1010,
            "open_timeout": 10,
        }
        handler = mock.Mock()
        self.session = MockCommandSession(
            self.mock_options, handler, self.devinfo, self.options, loop=self._loop
        )
        self.session_id = self.session.id
        self.key = (
            self.session.id,
            self.options["client_ip"],
            self.options["client_port"],
        )

    def tearDown(self) -> None:
        try:
            q_session = self._get_session()
            self._run_loop(q_session.close())
        except Exception:
            # session already closed in the test
            pass
        self.mocks.tearDown()
        super().tearDown()

    def mock_device(
        self,
        name: str,
        console: typing.Optional[str] = None,
        command_prompts: typing.Optional[typing.Dict[str, str]] = None,
    ) -> mock.Mock:
        return mock.Mock(
            hostname=name,
            console=console,
            command_prompts=command_prompts,
            pre_setup_commands=[],
            clear_command=None,
        )

    def _get_session(self) -> CommandSession:
        """
        helper method the get session from cache
        """
        return CommandSession.get(
            self.session_id,
            # pyre-fixme[6]: For 2nd argument expected `str` but got `Union[int, str]`.
            self.options["client_ip"],
            # pyre-fixme[6]: For 3rd argument expected `str` but got `Union[int, str]`.
            self.options["client_port"],
        )

    def test_create(self) -> None:
        self.assertFalse(self.session._connected)
        self.assertIn(self.key, CommandSession._ALL_SESSIONS)

    def test_get(self) -> None:
        q_session = self._get_session()
        self.assertEqual(self.session, q_session)

    @async_test
    async def test_connect(self) -> None:
        # Session is initially not connected
        self.assertFalse(self.session._connected)

        await self.session.connect()
        await self.session.wait_until_connected()

        self.assertTrue(self.session._connected)

    @async_test
    async def test_delay_connect(self) -> None:
        # Session is initially not connected
        self.assertFalse(self.session._connected)

        self.session.set_option("connect_delay", 0.1)
        # Initiate the connection and wait for connect
        await self.session.connect()
        await self.session.wait_until_connected(0.2)  # pyre-ignore

        self.assertTrue(self.session._connected)

    @async_test
    async def test_connect_timeout(self) -> None:
        # Session is initially not connected
        self.assertFalse(self.session._connected)

        self.session.set_option("connect_delay", 0.2)
        # Initiate the connection and wait for connect
        with self.assertRaises(ConnectionTimeoutErrorException):
            await self.session.connect()
            await self.session.wait_until_connected(0.1)  # pyre-ignore

        self.assertFalse(self.session._connected)

    @async_test
    async def test_setup_success(self) -> None:
        device = self.mock_device("test-dev-1")
        devinfo = await self.mocks.device_db.get(device)

        self.options["open_timeout"] = 2
        self.mock_options["prompt_delay"] = 0

        handler = mock.Mock()
        session = MockCommandSession(
            self.mock_options, handler, devinfo, self.options, loop=self._loop
        )
        # Session is initially not connected
        self.assertFalse(session._connected)

        await session.setup()
        self.assertTrue(session._connected)

    @async_test
    async def test_setup_prompt_timeout(self) -> None:
        device = self.mock_device("test-dev-1")
        devinfo = await self.mocks.device_db.get(device)

        self.options["open_timeout"] = 2
        self.mock_options["prompt_delay"] = 3

        handler = mock.Mock()
        session = MockCommandSession(
            self.mock_options, handler, devinfo, self.options, loop=self._loop
        )
        # Session is initially not connected
        self.assertFalse(session._connected)

        # Initiate the connection and wait for connect
        with self.assertRaises(ConnectionTimeoutErrorException):
            await session.setup()

    @async_test
    async def test_setup_command_timeout(self) -> None:
        device = self.mock_device("test-dev-1")
        devinfo = await self.mocks.device_db.get(device)

        self.options["open_timeout"] = 2

        # force a delay in setup commands
        self.mock_options["command_delay"] = 3

        handler = mock.Mock()
        session = MockCommandSession(
            self.mock_options, handler, devinfo, self.options, loop=self._loop
        )
        # Session is initially not connected
        self.assertFalse(session._connected)

        # Initiate the connection and wait for connect
        with self.assertRaises(ConnectionTimeoutErrorException):
            await session.setup()

    @async_test
    async def test_close(self) -> None:
        q_session = self._get_session()
        self.assertEqual(self.session, q_session)

        await self.session.close()

        with self.assertRaises(LookupErrorException):
            q_session = self._get_session()

    @async_test
    async def test_run_command(self) -> None:
        with self.assertRaises(RuntimeErrorException) as rexc:
            await self.session.run_command(b"test\n")

        self.assertEqual(rexc.exception.args[0], "Not Connected")

        # Initiate the connection and wait for connect
        await self.session.connect()
        await self.session.wait_until_connected()
        await self.session.wait_prompt()

        res = await self.session.run_command(b"test1\n")
        self.assertEqual(res, b"$ test1\nMock response for test1")

    @async_test
    async def test_run_command_timeout_prompt(self) -> None:

        # Initiate the connection and wait for connect
        await self.session.connect()
        await self.session.wait_until_connected()
        await self.session.wait_prompt()

        with self.assertRaises(CommandExecutionTimeoutErrorException) as rexc:
            await self.session.run_command(b"command timeout\n", 1)

        self.assertEqual(rexc.exception.args[0], "Command Response Timeout")
        self.assertEqual(
            rexc.exception.args[1],
            b"command timeout\nMock response for command timeout",
        )

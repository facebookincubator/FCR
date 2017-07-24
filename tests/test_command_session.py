#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2017-present, Facebook, Inc.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree. An additional grant
# of patent rights can be found in the PATENTS file in the same directory.
#

from .testutil import AsyncTestCase, async_test
import asyncio
import mock

from .mock_session import MockCommandSession
from .mocks import MockService

from fbnet.command_runner.command_session import CommandSession

import logging

log = logging.getLogger()


class CommandSessionTest(AsyncTestCase):

    def setUp(self):
        super().setUp()

        self.mock_options = {}
        self.mocks = MockService(self.mock_options, self._loop)

        test_device = self.mock_device("test-dev-1")
        self.devinfo = self._run_loop(self.mocks.device_db.get(test_device))[0]

        self.options = {
            'client_ip': "10.10.10.10",
            'client_port': 1010,
            'open_timeout': 10,
        }
        handler = mock.Mock()
        self.session = MockCommandSession(self.mock_options, handler,
                                          self.devinfo, self.options,
                                          loop=self._loop)
        self.session_id = self.session.id
        self.key = (self.session.id,
                    self.options["client_ip"],
                    self.options["client_port"])

    def tearDown(self):
        try:
            q_session = self._get_session()
            self._run_loop(q_session.close())
        except Exception:
            # session already closed in the test
            pass
        self.mocks.tearDown()
        super().tearDown()

    def mock_device(self, name, console=None, command_prompts=None):
        return mock.Mock(hostname=name, console=console,
                         command_prompts=command_prompts)

    def _get_session(self):
        """
        helper method the get session from cache
        """
        return CommandSession.get(self.session_id,
                                  self.options["client_ip"],
                                  self.options["client_port"])

    def test_create(self):
        self.assertFalse(self.session._connected)
        self.assertIn(self.key, CommandSession._ALL_SESSIONS)

    def test_get(self):
        q_session = self._get_session()
        self.assertEqual(self.session, q_session)

    @async_test
    async def test_connect(self):
        # Session is initially not connected
        self.assertFalse(self.session._connected)

        await self.session.connect()
        await self.session.wait_until_connected()

        self.assertTrue(self.session._connected)

    @async_test
    async def test_delay_connect(self):
        # Session is initially not connected
        self.assertFalse(self.session._connected)

        self.session.set_option("connect_delay", 0.1)
        # Initiate the connection and wait for connect
        await self.session.connect()
        await self.session.wait_until_connected(0.2)

        self.assertTrue(self.session._connected)

    @async_test
    async def test_connect_timeout(self):
        # Session is initially not connected
        self.assertFalse(self.session._connected)

        self.session.set_option("connect_delay", 0.2)
        # Initiate the connection and wait for connect
        with self.assertRaises(asyncio.TimeoutError):
            await self.session.connect()
            await self.session.wait_until_connected(0.1)

        self.assertFalse(self.session._connected)

    @async_test
    async def test_setup_success(self):
        device = self.mock_device("test-dev-1")
        devinfo = await self.mocks.device_db.get(device)

        self.options['open_timeout'] = 2
        self.mock_options['prompt_delay'] = 0

        handler = mock.Mock()
        session = MockCommandSession(self.mock_options, handler,
                                     devinfo, self.options,
                                     loop=self._loop)
        # Session is initially not connected
        self.assertFalse(session._connected)

        await session.setup()
        self.assertTrue(session._connected)

    @async_test
    async def test_setup_prompt_timeout(self):
        device = self.mock_device("test-dev-1")
        devinfo = await self.mocks.device_db.get(device)

        self.options['open_timeout'] = 2
        self.mock_options['prompt_delay'] = 3

        handler = mock.Mock()
        session = MockCommandSession(self.mock_options, handler,
                                     devinfo, self.options,
                                     loop=self._loop)
        # Session is initially not connected
        self.assertFalse(session._connected)

        # Initiate the connection and wait for connect
        with self.assertRaises(asyncio.TimeoutError):
            await session.setup()

    @async_test
    async def test_setup_command_timeout(self):
        device = self.mock_device("test-dev-1")
        devinfo = await self.mocks.device_db.get(device)

        self.options['open_timeout'] = 2

        # force a delay in setup commands
        self.mock_options['command_delay'] = 3

        handler = mock.Mock()
        session = MockCommandSession(self.mock_options, handler,
                                     devinfo, self.options,
                                     loop=self._loop)
        # Session is initially not connected
        self.assertFalse(session._connected)

        # Initiate the connection and wait for connect
        with self.assertRaises(asyncio.TimeoutError):
            await session.setup()

    @async_test
    async def test_close(self):
        q_session = self._get_session()
        self.assertEqual(self.session, q_session)

        await self.session.close()

        with self.assertRaises(KeyError):
            q_session = self._get_session()

    @async_test
    async def test_run_command(self):
        with self.assertRaises(RuntimeError) as rexc:
            await self.session.run_command(b"test\n")

        self.assertEqual(rexc.exception.args[0], "Not Connected")

        # Initiate the connection and wait for connect
        await self.session.connect()
        await self.session.wait_until_connected()
        await self.session.wait_prompt()

        res = await self.session.run_command(b"test1\n")
        self.assertEqual(res, b"$ test1\nMock response for test1")

    @async_test
    async def test_run_command_timeout_prompt(self):

        # Initiate the connection and wait for connect
        await self.session.connect()
        await self.session.wait_until_connected()
        await self.session.wait_prompt()

        with self.assertRaises(RuntimeError) as rexc:
            await self.session.run_command(b"command timeout\n", 1)

        self.assertEqual(rexc.exception.args[0], "Command Response Timeout")
        self.assertEqual(rexc.exception.args[1],
                         b"command timeout\nMock response for command timeout")

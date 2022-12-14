#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) Facebook, Inc. and its affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import asyncio
import typing
from unittest.mock import AsyncMock, Mock, patch

from fbnet.command_runner.command_session import CommandStreamReader, SSHCommandSession

from .mocks import MockService
from .testutil import async_test, AsyncTestCase

if typing.TYPE_CHECKING:
    # pyre-fixme[21]: Could not find module
    #  `nettools.fb_command_runner.oss.tests.device_info`.
    from .device_info import DeviceInfo
    from .testutil import FcrTestEventLoop


class SSHCommandSessionTest(AsyncTestCase):
    def setUp(self) -> None:
        super().setUp()

        self.mock_options = {}
        self.mocks = MockService(self.mock_options, self._loop)

        test_device = self.mock_device("test-dev-1")
        self.devinfo = self._run_loop(self.mocks.device_db.get(test_device))[0]

        self._mock_asyncssh = patch(
            "fbnet.command_runner.command_session.asyncssh"
        ).start()

        self.options = {
            "client_ip": "10.10.10.10",
            "client_port": 1010,
            "open_timeout": 10,
        }

    def tearDown(self) -> None:
        self.mocks.tearDown()
        super().tearDown()

    def mock_session(
        self,
        service: MockService,
        # pyre-fixme[11]: Annotation `DeviceInfo` is not defined as a type.
        devinfo: "DeviceInfo",
        options: typing.Dict[str, typing.Any],
        loop: "FcrTestEventLoop",
    ) -> SSHCommandSession:
        session = SSHCommandSession(
            service=service,
            devinfo=devinfo,
            options=options,
            loop=loop,
        )
        session._stream_reader = AsyncMock(spec=CommandStreamReader)
        session._stream_writer = Mock(spec=asyncio.StreamWriter)

        session._captured_time_ms = Mock(wraps=session.captured_time_ms)

        mock_response = b"run_command response"
        session.run_command = AsyncMock(return_value=mock_response)

        return session

    def mock_device(
        self,
        name: str,
        console: typing.Optional[str] = None,
        command_prompts: typing.Optional[typing.Dict[str, str]] = None,
    ) -> Mock:
        return Mock(
            hostname=name,
            console=console,
            command_prompts=command_prompts,
            pre_setup_commands=[],
            clear_command=None,
        )

    @async_test
    async def test_external_communication_time_reset(self) -> None:
        """
        Test the capturing of external communication time in SSHCommandSession
        If we connect to a session, reset the time, and then run a command,
        we should capture the external communication time of each separately without overlap
        """
        session = self.mock_session(
            service=self.mocks,
            devinfo=self.devinfo,
            options=self.options,
            loop=self._loop,
        )

        session._conn = AsyncMock(spec_set=session._conn)
        self._mock_asyncssh.create_connection = AsyncMock(
            spec_set=self._mock_asyncssh.create_connection,
            return_value=(Mock(), Mock()),
        )
        session._conn.create_session = AsyncMock(
            spec_set=session._conn.create_session,
            return_value=(Mock(), Mock()),
        )

        # Session is initially not connected
        self.assertFalse(session._connected)

        # Manually set _connected to True since CommandStream's
        # callback in wait_until_connected won't set it properly otherwise
        session._connected = True

        # Initiate the connection and wait for connect
        await session.connect()
        await session.wait_until_connected(10)

        # External communication time is updated once during connect()
        self.assertTrue(session._connected)
        self.assertEqual(
            # pyre-fixme[16]: Callable `increment_external_communication_time_ms`
            #  has no attribute `call_count`.
            session.captured_time_ms.increment_external_communication_time_ms.call_count,
            1,
        )

        # Reset mocks to specifically test that any feed_data calls
        # in _setup_connection() also increment time
        session._stream_reader.reset_mock()
        # pyre-fixme[16]: `CapturedTimeMS` has no attribute `reset_mock`.
        session.captured_time_ms.reset_mock()
        await session._setup_connection()
        self.assertEqual(
            session.captured_time_ms.increment_external_communication_time_ms.call_count,
            session._stream_reader.feed_data.call_count,
        )

        # Reset time and mocks to reset the call count of feed_data and
        # simulate making a second API call with the same session
        session.captured_time_ms.reset_time()
        session._stream_reader.reset_mock()
        session.captured_time_ms.reset_mock()

        res = await session.run_command(b"test1\n")
        self.assertEqual(res, b"run_command response")

        self.assertEqual(
            session.captured_time_ms.increment_external_communication_time_ms.call_count,
            session._stream_reader.feed_data.call_count,
        )

    @async_test
    async def test_external_communication_time_no_reset(self) -> None:
        """
        Test the capturing of external communication time in SSHCommandSession
        If we connect to a session and run a command without resetting, we should capture
        the external communication time of both actions
        """
        session = self.mock_session(
            service=self.mocks,
            devinfo=self.devinfo,
            options=self.options,
            loop=self._loop,
        )

        session._conn = AsyncMock(spec_set=session._conn)
        self._mock_asyncssh.create_connection = AsyncMock(
            spec_set=self._mock_asyncssh.create_connection,
            return_value=(Mock(), Mock()),
        )
        session._conn.create_session = AsyncMock(
            spec_set=session._conn.create_session,
            return_value=(Mock(), Mock()),
        )

        # Session is initially not connected
        self.assertFalse(session._connected)

        # Manually set _connected to True since CommandStream's
        # callback in wait_until_connected won't set it properly otherwise
        session._connected = True

        # Initiate the connection and wait for connect
        await session.connect()
        await session.wait_until_connected()

        self.assertTrue(session._connected)
        self.assertEqual(
            # pyre-fixme[16]: Callable `increment_external_communication_time_ms`
            #  has no attribute `call_count`.
            session.captured_time_ms.increment_external_communication_time_ms.call_count,
            1,
        )

        # Reset mock to reset the call count of feed_data since session
        # doesn't capture feed_data calls made in connect()
        session._stream_reader.reset_mock()
        await session._setup_connection()

        res = await session.run_command(b"test1\n")
        self.assertEqual(res, b"run_command response")

        # External communication time is updated for each feed_data call
        # plus once during connect()
        self.assertEqual(
            session.captured_time_ms.increment_external_communication_time_ms.call_count,
            session._stream_reader.feed_data.call_count + 1,
        )

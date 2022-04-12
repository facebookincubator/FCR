#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) Facebook, Inc. and its affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import typing

from fbnet.command_runner.exceptions import ConnectionTimeoutErrorException
from mock import Mock

from .mocks import MockService
from .testutil import async_test, AsyncTestCase

if typing.TYPE_CHECKING:
    from fbnet.command_runner_asyncio.CommandRunner.ttypes import Device

    from .mock_session import MockCommandSession


class DeviceInfoTest(AsyncTestCase):
    def setUp(self) -> None:
        super().setUp()

        self.mock_options = {}
        self.session_options = {
            "console": None,
            "client_ip": "10.10.10.10",
            "client_port": 1010,
        }
        self.pingable_addrs = {
            "test-dev-1": "ipv6",
            "test-dev-2": "ipv4",
            "test-dev-3": "mgmt_ipv6",
            "test-dev-4": "mgmt_ipv4",
        }

        self.mocks = MockService(self.mock_options, self._loop)

        self.test_device = Mock()
        self.test_device.hostname = "test-dev-1"
        self.test_devinfo = self._run_loop(self.mocks.device_db.get(self.test_device))[
            0
        ]

    def _get_pingable(self, dev: typing.Dict[str, str]) -> str:
        if dev["name"] in self.pingable_addrs:
            addrtype = self.pingable_addrs[dev["name"]]
            return dev[addrtype + ".prefix"]
        return dev["ip"]

    async def _get_device(self, name: str) -> "Device":
        device = Mock(hostname=name)
        return await self.mocks.device_db.get(device)

    def tearDown(self) -> None:
        self.mocks.tearDown()
        super().tearDown()

    async def _setup_session(self) -> "MockCommandSession":
        return await self.test_devinfo.setup_session(
            Mock(), self.test_device, self.session_options, self._loop
        )

    @async_test
    async def test_setup_session(self) -> None:
        session = await self._setup_session()

        self.assertIsNotNone(session)
        self.assertTrue(session.connect_called)
        self.assertTrue(session._connected)

        await session.close()

    @async_test
    async def test_setup_session_delay(self) -> None:
        self.mock_options["connect_delay"] = 0.1
        self.session_options["open_timeout"] = 0.3

        session = await self._setup_session()

        self.assertIsNotNone(session)
        self.assertTrue(session.connect_called)
        self.assertTrue(session._connected)

        await session.close()

    @async_test
    async def test_setup_session_timeout(self) -> None:
        self.mock_options["connect_delay"] = 0.1
        self.session_options["open_timeout"] = 0.05

        with self.assertRaises(ConnectionTimeoutErrorException):
            await self._setup_session()

    @async_test
    async def test_setup_session_setup_failure(self) -> None:
        # make run_command throw an error
        self.mock_options["run_error"] = True
        # inject some test commands into session setup
        self.test_devinfo._session_setup = ["term len 0"]

        with self.assertRaises(IOError):
            await self._setup_session()

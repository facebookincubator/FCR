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
from mock import Mock

import asyncio

from .mocks import MockService


class DeviceInfoTest(AsyncTestCase):

    def setUp(self):
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
        self.test_devinfo = self._run_loop(
            self.mocks.device_db.get(self.test_device))[0]

    def _get_pingable(self, dev):
        if dev['name'] in self.pingable_addrs:
            addrtype = self.pingable_addrs.get(dev['name'])
            return dev[addrtype + '.prefix']
        return dev['ip']

    async def _get_device(self, name):
        device = Mock(hostname=name)
        return await self.mocks.device_db.get(device)

    def tearDown(self):
        self.mocks.tearDown()
        super().tearDown()

    async def _setup_session(self):
        return await self.test_devinfo.setup_session(
            Mock(),
            self.test_device,
            self.session_options,
            self._loop)

    @async_test
    async def test_setup_session(self):
        session = await self._setup_session()

        self.assertIsNotNone(session)
        self.assertTrue(session.connect_called)
        self.assertTrue(session._connected)

        await session.close()

    @async_test
    async def test_setup_session_delay(self):
        self.mock_options["connect_delay"] = 0.1
        self.session_options["open_timeout"] = 0.3

        session = await self._setup_session()

        self.assertIsNotNone(session)
        self.assertTrue(session.connect_called)
        self.assertTrue(session._connected)

        await session.close()

    @async_test
    async def test_setup_session_timeout(self):
        self.mock_options["connect_delay"] = 0.1
        self.session_options["open_timeout"] = 0.05

        with self.assertRaises(asyncio.TimeoutError):
            await self._setup_session()

    @async_test
    async def test_setup_session_setup_failure(self):
        # make run_command throw an error
        self.mock_options["run_error"] = True
        # inject some test commands into session setup
        self.test_devinfo._session_setup = ['term len 0']

        with self.assertRaises(IOError):
            await self._setup_session()

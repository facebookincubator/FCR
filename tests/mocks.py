#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2017-present, Facebook, Inc.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree. An additional grant
# of patent rights can be found in the PATENTS file in the same directory.
#

import logging
import pkg_resources

from fbnet.command_runner.device_vendor import DeviceVendor, DeviceVendors
from fbnet.command_runner.device_db import BaseDeviceDB
from fbnet.command_runner.base_service import ServiceTask
from fbnet.command_runner.service import FcrServiceBase
from fbnet.command_runner.device_info import DeviceInfo, DeviceIP

from .mock_session import MockCommandSession

test_user = "testuser"
test_pass = "testpass"

mock_vendors = """
{
  "vendor_config": {
    "vendor1": {
      "vendor_name": "vendor1",
      "session_type": "mock",
      "cli_setup": ["en", "term len 0"],
      "prompt_regex": ["[$#]"],
      "shell_prompts": ["\\\\$"]
    },
    "vendor2": {
      "vendor_name": "vendor2",
      "session_type": "mock",
      "cli_setup": ["en", "command timeout"],
      "prompt_regex": ["[$#]"],
      "shell_prompts": ["\\\\$"]
    }
  }
}
"""

log = logging.getLogger()


class MockDeviceDB(BaseDeviceDB):

    def __init__(self, service):
        super().__init__(service)

        self.mock_devices = [self.mock_dev(i) for i in range(1, 10)]

    def mock_dev(self, idx):
        addrs = [
            'fd01:db00:11:{:04x}::a'.format(idx),
            'fd01:db00:11:{:04x}::b'.format(idx),
            '10.10.{}.11'.format(idx),
            '10.10.{}.12'.format(idx),
        ]
        addrs = [DeviceIP(a, a, False) for a in addrs]
        vendor_id = (idx // 5) + 1
        vendor = 'vendor%d' % (vendor_id)
        return DeviceInfo(
            self.service,
            'test-dev-%d' % (idx),
            test_user,
            test_pass,
            addrs,
            addrs[0],
            self.service.vendors.get(vendor),
            'role%d' % (idx % 3),
            'ch_model'
        )

    async def _fetch_device_data(self, name_filter=None, hostname=None):
        self.logger.info('got devices: %s', self.mock_devices)
        return self.mock_devices


class MockDeviceVendors(DeviceVendors):

    def __init__(self, service):
        super().__init__(service)

        jsonb = pkg_resources.resource_string(__name__, 'mock_vendors.json')
        self.load_vendors('mock_vendors.json', jsonb.decode('utf-8'))


class MockService(FcrServiceBase):

    def __init__(self, mock_options, loop):

        super().__init__('MockService', args=[], loop=loop)

        self.mock_options = mock_options
        self.vendors = MockDeviceVendors(self)
        self.device_db = MockDeviceDB(self)
        self.setUp()

    def _run_loop(self, *coro):
        return self._loop.run_until_complete(*coro)

    def setUp(self):

        DeviceVendor._SESSION_TYPES[b"mock"] = \
            MockCommandSession.Factory(self.mock_options)

        self._run_loop(self.device_db.wait_for_data())

    def tearDown(self):
        for _, svc_task in ServiceTask.all_tasks():
            svc_task.cancel()

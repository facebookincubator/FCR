#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2017-present, Facebook, Inc.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree. An additional grant
# of patent rights can be found in the PATENTS file in the same directory.
#

from fbnet.command_runner.command_server import CommandServer
from fbnet.command_runner.device_db import BaseDeviceDB
from fbnet.command_runner.device_info import DeviceInfo, DeviceIP
from fbnet.command_runner.device_vendor import DeviceVendors
from fbnet.command_runner.service import FcrServiceBase


class DeviceDB(BaseDeviceDB):
    def create_device(self, name):
        vendor = "Default"
        addr = DeviceIP(name, name, False)
        return DeviceInfo(
            self.service,
            name,
            None,
            None,
            [addr],
            addr,
            self.service.vendors.get(vendor),
            "GEN",
            "Generic",
        )

    async def _fetch_device_data(self, name_filter=None):
        self.logger.info("fetch_device_data: %s", name_filter)
        if name_filter:
            self.logger.info("Getting device")
            return [self.create_device(name_filter)]
        else:
            return []


class Vendors(DeviceVendors):
    pass


class FCRService(FcrServiceBase):
    def __init__(self):

        super().__init__("FCR")

        self.vendors = Vendors(self)
        self.device_db = DeviceDB(self)
        self.service = CommandServer(self)


def main():

    service = FCRService()
    service.start()


if __name__ == "__main__":
    main()

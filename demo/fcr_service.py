#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2017-present, Facebook, Inc.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree. An additional grant
# of patent rights can be found in the PATENTS file in the same directory.
#

import docker
from fbnet.command_runner.command_server import CommandServer
from fbnet.command_runner.command_session import SessionReaperTask
from fbnet.command_runner.device_db import BaseDeviceDB
from fbnet.command_runner.device_info import DeviceInfo, DeviceIP
from fbnet.command_runner.device_vendor import DeviceVendors
from fbnet.command_runner.service import FcrServiceBase


class DeviceDB(BaseDeviceDB):

    docker_client = docker.from_env()

    async def _fetch_device_data(self, name_filter=None, hostname=None):
        self.logger.info(
            "fetch_device_data: name_filter=%s, hostname=%s", name_filter, hostname
        )

        containers = await self._run_in_executor(self.list_containers)

        return [self.create_device(c) for c in containers]

    @classmethod
    def list_containers(cls):
        return cls.docker_client.containers.list()

    def create_device(self, container):
        vendor = "docker"
        ip = container.attrs["NetworkSettings"]["IPAddress"]
        addr = DeviceIP("addr", ip, False)
        return DeviceInfo(
            self.service,
            container.name,
            "netbot",
            "bot1234",
            [addr],
            addr,
            self.service.vendors.get(vendor),
            "Demo",
            "Ubuntu",
        )


class FCRService(FcrServiceBase):
    def __init__(self):
        super().__init__("FCR")

        self.vendors = DeviceVendors(self)
        self.device_db = DeviceDB(self)
        self.service = CommandServer(self)
        self.add_task("session_reaper_task", SessionReaperTask(service=self))


def main():

    service = FCRService()
    service.start()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse


from fbnet.command_runner.service import FcrServiceBase
from fbnet.command_runner.command_server import CommandServer
from fbnet.command_runner.device_db import BaseDeviceDB
from fbnet.command_runner.device_vendor import DeviceVendors
from fbnet.command_runner.device_info import DeviceInfo, DeviceIP


class DeviceDB(BaseDeviceDB):

    def create_device(self, name):
        vendor = 'Default'
        addr = DeviceIP(name, name, False)
        return DeviceInfo(
            self.app,
            name,
            None,
            None,
            [addr],
            addr,
            self.app.vendors.get(vendor),
            'GEN',
            'Generic'
        )

    async def _fetch_device_data(self, name_filter=None):
        self.logger.info('fetch_device_data: %s', name_filter)
        if name_filter:
            self.logger.info("Getting device")
            return [self.create_device(name_filter)]
        else:
            return []


class Vendors(DeviceVendors):
    pass


class FCRService(FcrServiceBase):

    def __init__(self, config):

        super().__init__("FCR", config)

        self.vendors = Vendors(self)
        self.device_db = DeviceDB(self)
        self.service = CommandServer(self)


def _parse_args():

    parser = argparse.ArgumentParser()

    parser.add_argument("--asyncio_debug",
                        help="turn on debug for asyncio",
                        action="store_true",
                        default=False)
    parser.add_argument("-p", "--port",
                        help="listen on port",
                        type=int,
                        default=5000)
    parser.add_argument("--log_level",
                        help="logging level",
                        choices=["debug", "info", "warning",
                                 "error", "critical"],
                        default="info")
    parser.add_argument("--max_default_executor_threads",
                        help="Max number of worker threads",
                        type=int,
                        default=4)
    parser.add_argument("--remote_call_overhead",
                        help="Overhead for running commands remotely (for bulk calls)",
                        type=int,
                        default=20)
    parser.add_argument("--device_name_filter_loading",
                        help="regex for fcr to load device info from fbnet")
    parser.add_argument("--exit_max_wait",
                        type=int,
                        default=300,
                        help="Max time (seconds) to wait for session to terminate")

    return parser.parse_args()


def main():

    app = FCRService(_parse_args())
    app.start()


if __name__ == "__main__":
    main()

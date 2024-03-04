#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# pyre-unsafe

# Copyright (c) Facebook, Inc. and its affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import typing

from .base_service import PeriodicServiceTask
from .exceptions import LookupErrorException, NotImplementedErrorException
from .options import Option


if typing.TYPE_CHECKING:
    from fbnet.command_runner_asyncio.CommandRunner.ttypes import Device

    from .device_info import DeviceInfo, DeviceIP


class BaseDeviceDB(PeriodicServiceTask):
    """
    Interface to device database.

    Adapt this to get devices from your backend system.
    """

    DEVICE_DB_UPDATE_INTERVAL = Option(
        "--device_db_update_interval",
        help="device db update interval (in seconds)",
        type=int,
        default=30 * 60,
    )

    DEVICE_NAME_FILTER = Option(
        "--device_name_filter",
        help="A regex to restrict the database to matching device names",
    )

    def __init__(self, service, name=None, period=None):
        super().__init__(
            service,
            name or self.__class__.__name__,
            period=period or self.DEVICE_DB_UPDATE_INTERVAL,
        )

        self._data_valid = False
        self._devices = {}

    @property
    def data_valid(self):
        return self._data_valid

    async def run(self):
        """
        Fetch data for devices. This is called periodically.

        Here we are reloading data from JSON file periodically. How you get
        your data depends on your local setup. Override this according to your
        setup
        """
        try:
            await self._fetch_devices(name_filter=self.DEVICE_NAME_FILTER)
        except Exception as ex:
            self.service.logger.error(
                f"Failed to fetch device info, error message: {str(ex)}"
            )
        else:
            self._data_valid = True

    async def _fetch_devices(self, name_filter=None, hostname=None):
        devices = await self._fetch_device_data(name_filter, hostname)
        for d in devices:
            self._devices[d.hostname] = d
            if d.alias:
                self._devices[d.alias] = d

    async def _fetch_device_data(self, name_filter=None, hostname=None):
        """
        Fetch device data

        Override this to get the device information from your backend systems
        """
        raise NotImplementedErrorException(
            "Please implement this to get host information"
        )

    async def wait_for_data(self):
        """Wait for the data to be fetched"""
        while not self._data_valid:
            self.logger.info("Waiting for data")
            await self.wait()
        self.logger.info("Device data valid")

    async def get(
        self, device: typing.Union["Device", str], autofetch: bool = True
    ) -> "DeviceInfo":
        """
        Get device information for a given device.

        * First we lookup in our local cache
        * If not found then we will try to fetch the specific device from backend if autofetch is true

        device parameter can be the hostname string or the Device struct
        """

        hostname = device if isinstance(device, str) else device.hostname
        if hostname not in self._devices and autofetch:
            # Try to fetch the device info
            await self._fetch_devices(hostname=hostname)

        if hostname in self._devices:
            # Found the device
            return self._devices.get(hostname)

        # still not able to find device, raise an exeception
        raise LookupErrorException("Device not found", hostname)

    def is_pingable(self, ip: typing.Union[str, "DeviceIP"]) -> bool:
        raise NotImplementedErrorException(
            "Please implement this to check if an ip is pingable"
        )

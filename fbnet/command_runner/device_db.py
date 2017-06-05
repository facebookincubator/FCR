#!/usr/bin/env python3

from .base_service import PeriodicServiceTask


class DeviceDB(PeriodicServiceTask):
    '''
    Interface to device database.

    Adapt this to get devices from your backend system.
    '''

    _TASK_PERIOD = 30 * 60

    def __init__(self, app, name=None, period=None):
        super().__init__(
            app,
            name or self.__class__.__name__,
            period=period or self._TASK_PERIOD)

        self._data_valid = False
        self._devices = {}

    def _device_name_filter(self):
        return None

    async def run(self):
        """
        Fetch data for devices. This is called periodically.

        Here we are reloading data from JSON file periodically. How you get
        your data depends on your local setup. Override this according to your
        setup
        """
        await self._fetch_devices(self._device_name_filter())
        self._data_valid = True

    async def _fetch_devices(self, name_filter=None):
        devices = await self._fetch_device_data(name_filter)
        for d in devices:
            self._devices[d.hostname] = d
            if d.alias:
                self._devices[d.alias] = d

    async def _fetch_device_data(self, name_filter=None):
        '''
        Fetch device data

        Override this get the device information from your backend systems
        '''
        raise NotImplementedError("Please implement this get host information")

    async def wait_for_data(self):
        '''Wait for the data to be fetched'''
        while not self._data_valid:
            self.logger.info("Waiting for data")
            await self.wait()
        self.logger.info("Device data valid")

    async def get(self, device, autofetch=True):
        '''
        Get device information for a given device.

        * First we lookup in our local cache
        * If not found then we will try to fetch the specific device from backend
        '''
        if device.hostname not in self._devices and autofetch:
            # Try to fetch the device info
            await self._fetch_devices(device.hostname)

        if device.hostname in self._devices:
            # Found the device
            return self._devices.get(device.hostname)

        # still not able to find device, raise an exeception
        raise KeyError("Device not found", device.hostname)

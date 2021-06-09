#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) Facebook, Inc. and its affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import re
from collections import namedtuple
from typing import NamedTuple

from .base_service import ServiceObj
from .console_session import ConsoleCommandSession


CommandInfo = namedtuple("CommandInfo", "cmd precmd prompt_re")
DeviceIP = namedtuple("DeviceIP", ["name", "addr", "mgmt_ip"])
IPInfo = NamedTuple("IPInfo", [("addr", str), ("is_pingable", bool)])


class DeviceInfo(ServiceObj):
    """
    An abstraction to represent the network devices.
    """

    def __init__(
        self, service, hostname, pref_ips, ip, vendor_data, role, ch_model, alias=None
    ):
        super().__init__(service, "DeviceInfo")
        self._hostname = hostname
        self._pref_ips = pref_ips
        self._ip = ip
        self._vendor_data = vendor_data
        self._role = role
        self._ch_model = ch_model
        self._alias = alias

    @classmethod
    def register_counters(cls, stats_mgr):
        stats_mgr.register_counter("device_info.mgmt_ip")
        stats_mgr.register_counter("device_info.fallback_to_mgmt_ip")
        stats_mgr.register_counter("device_info.default_ip")

    async def setup_session(self, service, device, options, loop):
        """
        create and setup a session to the device.
        """
        try:
            session = self.create_session(service, device, options, loop)
            await session.setup()
            return session

        except Exception as e:
            await session.close()  # Cleanup the session
            raise e

    def create_session(self, service, device, options, loop):
        """
        Create a session object.

        Note: This doesn't setup the session. The session has to be explicitly
              setup either by calling "setup" method or by using a context
              manager

        session = devinfo.create_session(...)
        await session.setup()

        # or you can use setup_session
        session = await devinfo.setup_session(...)

        # or you can use async context manager
        async with devinfo.create_session(...) as session:
            # do something with session

        """
        _SessionType = self.get_session_type(options)
        return _SessionType(service, self, options, loop=loop)

    @classmethod
    def proxy_required(cls, ip):
        return False

    def should_nat(self, ip: str) -> bool:
        return False

    async def translate_address(self, ip: str) -> str:
        """
        Return a translated address (i.e. via NAT). Currently does nothing.
        """
        return ip

    def __repr__(self):
        return "Device[{0!r}]".format(self._hostname)

    @property
    def hostname(self):
        return self._hostname

    def get_ip(self, options) -> IPInfo:
        """
        Returns IP address and whether it is pingable or not.

        ip_address = devinfo.get_ip(...).addr
        is_pingable = devinfo.get_ip(...).is_pingable
        """
        # If user specified an ip address, then use it directly
        ip_address = options.get("ip_address")
        if ip_address:
            return IPInfo(ip_address, self.check_ip(ip_address))

        # Return the first pingable IP
        use_mgmt_ip = options.get("mgmt_ip")
        if use_mgmt_ip:
            self.inc_counter("device_info.mgmt_ip")
        for ip in self._pref_ips:
            if use_mgmt_ip and not self._is_mgmt_ip(ip):
                # User request to only use the management IP
                continue

            if self.check_ip(ip):
                return IPInfo(ip.addr, True)

        # None of the required IP is pingable, return first valid IP address
        # if use_mgmt_ip is True, then return the first valid MGMT IP address
        self.inc_counter("device_info.default_ip")
        for ip in [self._ip] + self._pref_ips:
            # ip.addr is None, skip
            if not ip.addr:
                continue

            # return first valid ip address if user didn't specify to use mgmt ip
            if not use_mgmt_ip:
                return IPInfo(ip.addr, False)

            # return first valid mgmt ip if user specifies to use mgmt ip
            if self._is_mgmt_ip(ip):
                self.inc_counter("device_info.fallback_to_mgmt_ip")
                return IPInfo(ip.addr, False)

        # No valid MGMT IPs were found when user specifies use_mgmt_ip, raise
        # LookupError
        if use_mgmt_ip:
            raise LookupError(
                "User has set 'mgmt_ip=True' in the request but no mgmt ip is "
                f"found for {self._hostname}"
            )

        # None of the IPs is valid, raise LookupError
        raise LookupError(
            f"No Valid IP address was found for the device {self._hostname}"
        )

    @property
    def role(self):
        return self._role

    @property
    def ch_model(self):
        return self._ch_model

    @property
    def vendor_data(self):
        return self._vendor_data

    @property
    def vendor_name(self):
        return self._vendor_data.vendor_name

    @property
    def alias(self):
        return self._alias

    @property
    def prompt_re(self):
        return self._vendor_data.get_prompt_re()

    def get_prompt_re(self, trailer=None):
        return self._vendor_data.get_prompt_re(trailer)

    def _is_question(self, cmd):
        return cmd.endswith(b"?")

    def _autocomplete(self):
        return self.vendor_data.autocomplete

    def get_command_info(self, cmd, command_prompts=None):
        """
        get command information.

        * command string to send
        * any pre-command strings to send. This is mostly used to clear the
          current command line
        * expected prompts: this is the prompt expected after the end of
          command output.
        """

        cmd = cmd.strip()

        prompt_rex = None
        trailer = None

        # Check if user specified a prompt override for this command
        if command_prompts:
            prompt_re = command_prompts.get(cmd)
            if prompt_re:
                prompt_rex = re.compile(b"(?P<prompt>%s)" % prompt_re)
                cmd += b"\n"

        if not prompt_rex:
            if self._is_question(cmd) and self._autocomplete():
                # We expect the command to be echoed back after prompt
                trailer = cmd[:-1].strip()  # remove the last char ('?')
                trailer = rb"(?P<command>%s)[\b\s]*" % re.escape(trailer)
            else:
                # Normal command
                cmd = cmd + b"\n"  # Add newline

            prompt_rex = self.get_prompt_re(trailer)

        # Send a NACK to clear the current command line
        precmd = self._vendor_data.clear_command

        return CommandInfo(cmd, precmd, prompt_rex)

    def get_session_type(self, options):
        if options["console"]:
            return ConsoleCommandSession
        return self._vendor_data.select_session_type(options)

    def _is_mgmt_ip(self, ip):
        return False

    def check_ip(self, ip):
        return True

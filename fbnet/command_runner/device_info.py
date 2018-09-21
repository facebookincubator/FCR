#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2017-present, Facebook, Inc.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree. An additional grant
# of patent rights can be found in the PATENTS file in the same directory.
#

import re
from collections import namedtuple

from .base_service import ServiceObj
from .console_session import ConsoleCommandSession


CommandInfo = namedtuple("CommandInfo", "cmd precmd prompt_re")
DeviceIP = namedtuple("DeviceIP", ["name", "addr", "mgmt_ip"])


class DeviceInfo(ServiceObj):
    """
    An abstraction to represent the network devices.
    """

    def __init__(
        self,
        service,
        hostname,
        username,
        password,
        pref_ips,
        ip,
        vendor_data,
        role,
        ch_model,
        alias=None,
    ):
        super().__init__(service, "DeviceInfo")
        self._hostname = hostname
        self._username = username  # Default username for device
        self._password = password  # Default password for device
        self._pref_ips = pref_ips
        self._ip = ip
        self._vendor_data = vendor_data
        self._role = role
        self._ch_model = ch_model
        self._alias = alias

    @classmethod
    def register_counters(cls, stats_mgr):
        stats_mgr.register_counter("device_info.mgmt_ip")
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
        _SessionType = self._get_session_type(options)
        return _SessionType(service, self, options, loop=loop)

    def connect_using_proxy(self):
        return False

    def __repr__(self):
        return "Device[{0!r}]".format(self._hostname)

    @property
    def hostname(self):
        return self._hostname

    def get_ip(self, options):
        # If user specified an ip address, then use it directly
        # Else we call the parent class to do the address selection
        ip_address = options.get("ip_address")
        if ip_address:
            return ip_address

        use_mgmt_ip = options.get("mgmt_ip")
        if use_mgmt_ip:
            self.inc_counter("device_info.mgmt_ip")
        for ip in self._pref_ips:
            if use_mgmt_ip and not self._is_mgmt_ip(ip):
                # User request to only use the management IP
                continue

            if self.check_ip(ip):
                return ip.addr
        self.inc_counter("device_info.default_ip")
        return self._ip.addr

    @property
    def username(self):
        return self._username

    @property
    def password(self):
        return self._password

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
                trailer = b"(?P<command>%s)[\b\s]*" % re.escape(trailer)
            else:
                # Normal command
                cmd = cmd + b"\n"  # Add newline

            prompt_rex = self.get_prompt_re(trailer)

        # Send a NACK to clear the current command line
        precmd = self._vendor_data.clear_command

        return CommandInfo(cmd, precmd, prompt_rex)

    def _get_session_type(self, options):
        if options["console"]:
            return ConsoleCommandSession
        return self._vendor_data.select_session_type(options)

    def _is_mgmt_ip(self, ip):
        return False

    def check_ip(self, ip):
        return True

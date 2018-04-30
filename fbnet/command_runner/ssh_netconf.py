#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import asyncio

from fbnet.command_runner.command_session import SSHCommandSession


class SSHNetconf(SSHCommandSession):
    TERM_TYPE = None
    DELIM = b']]>]]>'
    PROMPT = re.compile(DELIM)

    HELLO_MESSAGE = b'''<?xml version="1.0"?>
<nc:hello xmlns:nc="urn:ietf:params:xml:ns:netconf:base:1.0">
  <nc:capabilities>
  <nc:capability>urn:ietf:params:xml:ns:netconf:base:1.0</nc:capability>
  </nc:capabilities>
</nc:hello>
'''

    async def _setup_connection(self):
        # Wait for the hello message from the peer. We will save this message
        # and include this with first reply.
        resp = await self.wait_prompt(self.PROMPT)
        self.server_hello = resp.data
        # Send our hello message to the server
        self._send_command(self.HELLO_MESSAGE)

    def _send_command(self, cmd):
        # Send a command followed by a delimiter
        self._stream_writer.write(b'\n' + cmd + self.DELIM + b'\n')

    async def _wait_response(self, cmd, prompt_re):
        """
        Wait for command response from the device
        """
        return await self.wait_prompt(self.PROMPT)

    def _format_output(self, cmd, resp):
        output = resp.data
        # Not sure if this is needed. But it may be useful for some client to
        # know the server capabilities (mostly for interactive sessions)
        if self.server_hello:
            output = (
                self.server_hello +
                b'\n' + self.DELIM + b'\n' +
                output
            )
            self.server_hello = None  # Clear it out so we don't send it again
        return output

    async def run_command(self, cmd, timeout=None, prompt_re=None):
        try:
            self._send_command(cmd)
            # Wait for response with timeout
            resp = await asyncio.wait_for(
                self._wait_response(None, self.PROMPT),
                timeout or self._devinfo.vendor_data.cmd_timeout_sec,
                loop=self._loop)
            return self._format_output(cmd, resp)
        except asyncio.TimeoutError:
            self.logger.error("Timeout waiting for command response")
            data = await self._stream_reader.drain()
            raise RuntimeError("Command Response Timeout", data[-200:])

    async def _connect(self):
        command = None
        subsystem = None
        device = self._opts.get('device')

        # One of subsystem/command needs to be specified. If subsystem is specified
        # we will ignore the commmand
        subsystem = device.session_data.subsystem
        if not subsystem:
            command = device.session_data.exec_command
            if not command:
                raise RuntimeError(
                    'either subsystem or exce_command must be specified '
                    'for netconf session'
                )

        return await super()._connect(subsystem=subsystem, command=command)

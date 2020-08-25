#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) Facebook, Inc. and its affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import asyncio
import re
from typing import Any, Dict, List, Optional

from fbnet.command_runner.command_session import ResponseMatch, SSHCommandSession
from fbnet.command_runner_asyncio.CommandRunner.ttypes import CommandResult


class SSHNetconf(SSHCommandSession):
    TERM_TYPE: Optional[str] = None
    DELIM: bytes = b"]]>]]>"
    PROMPT: re.Pattern = re.compile(DELIM)

    HELLO_MESSAGE: bytes = b"""<?xml version="1.0" encoding="UTF-8" ?>
<hello xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">
  <capabilities>
    <capability>urn:ietf:params:netconf:base:1.0</capability>
  </capabilities>
</hello>
"""

    def __init__(self, *args: List[Any], **kwargs: Dict[str, Any]) -> None:
        super().__init__(*args, **kwargs)

        self.server_hello: Optional[str] = None

    async def _setup_connection(self) -> None:
        # Wait for the hello message from the peer. We will save this message
        # and include this with first reply.
        resp = await self.wait_prompt(self.PROMPT)
        self.server_hello = resp.data.strip()
        # Send our hello message to the server
        self._send_command(self.HELLO_MESSAGE)

    def _send_command(self, cmd: bytes) -> None:
        # Send a command followed by a delimiter
        self._stream_writer.write(b"\n" + cmd + self.DELIM + b"\n")

    def _format_output(self, cmd: bytes, resp: ResponseMatch) -> bytes:
        return resp.data.strip()

    def build_result(self, output: str, status: str, command: str) -> CommandResult:
        result = super().build_result(output, status, command)
        if self.server_hello:
            result.capabilities = self.server_hello
            self.server_hello = None
        return result

    async def _run_command(
        self,
        cmd: bytes,
        timeout: Optional[int] = None,
        prompt_re: Optional[re.Pattern] = None,
    ) -> bytes:
        try:
            self._send_command(cmd)
            # Wait for response with timeout
            resp = await asyncio.wait_for(
                self.wait_prompt(self.PROMPT),
                timeout or self._devinfo.vendor_data.cmd_timeout_sec,
                loop=self._loop,
            )
            return self._format_output(cmd, resp)
        except asyncio.TimeoutError:
            self.logger.error("Timeout waiting for command response")
            data = await self._stream_reader.drain()
            raise RuntimeError("Command Response Timeout", data[-200:])

    async def _connect(
        self, subsystem: Optional[str] = None, exec_command: Optional[str] = None
    ) -> None:
        command = None
        device = self._opts.get("device")

        # One of subsystem/command needs to be specified. If subsystem is specified
        # we will ignore the commmand
        subsystem = device.session_data.subsystem
        if not subsystem:
            command = device.session_data.exec_command
            if not command:
                raise RuntimeError(
                    "either subsystem or exce_command must be specified "
                    "for netconf session"
                )

        return await super()._connect(subsystem=subsystem, exec_command=command)

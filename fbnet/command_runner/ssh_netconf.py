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
from fbnet.command_runner.counters import Counters
from fbnet.command_runner_asyncio.CommandRunner.ttypes import CommandResult

from .utils import construct_netconf_capability_set


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

    @classmethod
    def register_counter(cls, counters: Counters):
        super().register_counters(counters)

        stats = ["sum", "avg"]
        counters.add_stats_counter("netconf_capability_construction.error", stats)
        counters.add_stats_counter("netconf_capability_construction.all", stats)

    async def _setup_connection(self) -> None:
        # Wait for the hello message from the peer. We will save this message
        # and include this with first reply.
        resp = await self.wait_prompt(self.PROMPT)
        self.server_hello = resp.data.strip()
        # Send our hello message to the server
        self._send_command(self.HELLO_MESSAGE)

        self._validate_netconf_capabilities()

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

    def _validate_netconf_capabilities(self) -> None:
        """
        Validates that the remote netconf host (device) has FCR's netconf
        base capability. Raise exception if not.
        """

        assert self.server_hello, "We haven't received hello message from Device yet!"

        self.inc_counter("netconf_capability_construction.all")
        try:
            remote_host_netconf_base_capabilities_set = (
                construct_netconf_capability_set(self.server_hello)  # pyre-ignore
            )
            local_netconf_base_capabilities_set = construct_netconf_capability_set(
                self.HELLO_MESSAGE
            )
        except Exception:
            # Failed at constructing the capability set, let's continue the session
            # without validating the capabilities
            self.logger.exception("Failed at constructing remote host's capability set")
            self.inc_counter("netconf_capability_construction.error")
            return

        if not (
            remote_host_netconf_base_capabilities_set
            & local_netconf_base_capabilities_set
        ):
            # Device does not share common capability with us, terminate the connection
            super().close()
            raise ConnectionError(
                "Remote host and FCR do not share common Netconf base capabilities!\n"
                f"Current FCR supported Netconf base capabilities: {local_netconf_base_capabilities_set}"
            )

    async def _run_command(
        self,
        cmd: bytes,
        timeout: Optional[int] = None,
        prompt_re: Optional[re.Pattern] = None,
    ) -> bytes:
        try:
            self.logger.info(f"Sending command to device. Command: {cmd}")
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

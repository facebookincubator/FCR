#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) Facebook, Inc. and its affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import asyncio
import re
from collections import namedtuple

from .command_session import SSHCommandSession


class ConsoleInfo(namedtuple("ConsoleInfo", "contype, host, server, port")):
    """
    Information about the console
    """

    def __repr__(self):
        """
        pretty representation of console information
        """
        return "host:{s.host} {s.contype}: {s.server}:{s.port}".format(s=self)


class ConsoleCommandSession(SSHCommandSession):
    """
    A command session that runs over a console connections.

    Currently we only support SSH connection to the console server
    """

    _INTERACT_PROMPTS = {b"Y": rb"Do you acknowledge\? \(Y/N\)\?"}
    _CONSOLE_PROMPTS = {
        # For login we need to ignore output like:
        #  Last login: Mon May  8 13:53:17 on ttyS0
        b"login": b".*((?<!Last ).ogin|.sername):",
        b"passwd": b"\n.*assword:",
        # Ignore login failure message like P64639613
        b"prompt": b"\n.*[#>](?!Login incorrect)",
        b"interact_prompts": rb"Do you acknowledge\? \(Y/N\)\?",
    }

    # Certain prompts that we get during the login attemts that we will like to
    # ignore
    _CONSOLE_INGORE = {rb" to cli \]", rb"who is on this device.\]\r\n"}
    _DEFAULT_LOGOUT_COMMAND = b"exit"

    _CONSOLE_PROMPT_RE = None
    _CONSOLE_EXPECT_DELAY = 5

    def __init__(self, service, devinfo, options, loop):
        super().__init__(service, devinfo, options, loop)
        self._console = options["console"]

    @classmethod
    def _build_prompt_re(cls, prompts, ignore):
        prompts = [b"(?P<%s>%s)" % (group, regex) for group, regex in prompts.items()]
        # Add a set of prompts that we want to ignore
        ignore_prompts = b"|".join((b"(%s)" % p for p in ignore))
        prompts.append(b"(?P<ignore>%s)" % ignore_prompts)
        prompt_re = b"|".join(prompts)
        cls._CONSOLE_PROMPT_RE = re.compile(prompt_re + rb"\s*$")

    @classmethod
    def get_prompt_re(cls):
        """
        The first time this is called, we will builds the prompt for the
        console. After that we will return the pre-computed regex
        """
        if not cls._CONSOLE_PROMPT_RE:
            cls._build_prompt_re(cls._CONSOLE_PROMPTS, cls._CONSOLE_INGORE)
        return cls._CONSOLE_PROMPT_RE

    async def dest_info(self):
        console = await self.get_console_info()
        self.logger.info("%s", str(console))
        return (console.server, console.port)

    async def expect(self, regex, timeout=_CONSOLE_EXPECT_DELAY):
        try:
            return await asyncio.wait_for(
                self.wait_prompt(regex), timeout, loop=self._loop
            )
        except asyncio.TimeoutError as ex:
            data = []
            if self._stream_reader:
                data = await self._stream_reader.drain()
            self.logger.exception("Timeout waiting for: %s", regex)
            raise asyncio.TimeoutError(
                "Timeout during waiting for prompt."
                f"Currently received data: {data[-200:]}"
            ) from ex

    def send(self, data, end=b"\n"):
        """
        send some data and optionally wait for some data
        """
        if isinstance(data, str):
            data = data.encode("utf8")
        self._stream_writer.write(data + end)

    async def _try_login(
        self,
        username=None,
        passwd=None,
        kickstart=False,
        username_tried=False,
        pwd_tried=False,
    ):
        """
        A helper function that tries to login into the device.

        kickstart gives the option to send a clear line to the console
        before entering the username and password to prevent false TimeoutError,
        since sometimes user needs to hit an Enter before logging in.

        username_tried and pwd_tried are an indicator showing that the
        FCR has received a login error from the console after sending the
        username and password to the console, if this triggers, we would
        raise a PermissionError stating that the console has failed to login,
        this will also prevent false TimeoutError to happen.
        """
        res = await self._get_response(
            username, passwd, kickstart, username_tried, pwd_tried
        )

        if res.groupdict.get("ignore"):
            # If we match anything in the ignore prompts, set a \r\n
            self._send_newline(end=b"")
            await asyncio.sleep(0.2)  # Let the console catch up
            # Now again try to login.
            return await self._try_login(
                username=username,
                passwd=passwd,
                username_tried=username_tried,
                pwd_tried=pwd_tried,
            )

        elif res.groupdict.get("login"):
            if username_tried:
                raise PermissionError(
                    "Login failure, possibly incorrect username or password, "
                    "or device refuses to login."
                )
            # The device is requesting login information
            # If we don't have a username, then likely we already sent a
            # username. The consoles are slow, we may have send extra
            # carriage returns, resulting in multiple login prompts. We will
            # simply ignore the subsequent login prompts.
            if username is not None:
                self.send(self._username)
            # if we don't have username, we are likely waiting for password
            return await self._try_login(
                passwd=passwd, username_tried=True, pwd_tried=pwd_tried
            )

        elif res.groupdict.get("passwd"):
            if pwd_tried:
                raise PermissionError(
                    "Login failure, possibly incorrect username or password, "
                    "or device refuses to login."
                )
            if passwd is None:
                # passwd information not available
                # Likely we have alreay sent the password. Bail out instead
                # of getting stuck in a loop.
                raise RuntimeError("Failed to login: Password not expected")
            self.send(self._password)
            return await self._try_login(username_tried=username_tried, pwd_tried=True)

        elif res.groupdict.get("interact_prompts"):
            # send Y to get past the post login prompt
            self._interact_prompts_action(res.groupdict.get("interact_prompts"))
            return await self._try_login(
                username_tried=username_tried, pwd_tried=pwd_tried
            )

        elif res.groupdict.get("prompt"):
            # Finally we matched a prompt. we are done
            return self._send_newline()

        else:
            raise RuntimeError("Matched no group: %s" % (res.groupdict))

    async def _get_response(
        self, username, passwd, kickstart, username_tried, pwd_tried
    ):
        # A small delay to avoid having to match extraneous input
        await asyncio.sleep(0.1)
        try:
            res = await self.expect(self.get_prompt_re())
            return res
        except asyncio.TimeoutError:
            if kickstart and username:
                # We likey didn't get anything from the console. Try sending a
                # newline to kickstart the login process
                self.logger.debug("kickstart console login")

                # Clear the current line and send a newline
                self._send_clearline()
                return await self._try_login(
                    username=username,
                    passwd=passwd,
                    username_tried=username_tried,
                    pwd_tried=pwd_tried,
                )
            else:
                raise

    async def _try_logout(self, kick_shutdown=False) -> None:
        """
        Run logout command and wait for the login prompt to show up (the login
        prompt indicates that it successfully logs out and is waiting for the
        next login). This is to ensure we cleanly diconnect from the device
        after running the command
        """
        if not self._stream_writer:
            return

        self.logger.info("Logout from device")
        logout_cmd = (
            self._devinfo.vendor_data.exit_command or self._DEFAULT_LOGOUT_COMMAND
        )
        self._stream_writer.write(logout_cmd + b"\n")
        # Make sure we logout of the system
        while True:
            try:
                res = await self.expect(self.get_prompt_re())
            except asyncio.TimeoutError:
                if kick_shutdown:
                    self._send_newline()
                    return await self._try_logout()
                else:
                    raise

            if not res:
                self.logger.warn(
                    "Console connection timeout. Most likely the connection is "
                    "already killed by the device."
                )
                return
            elif res.groupdict.get("ignore"):
                # If we match anything in the ignore prompts, set a \r\n
                self._send_newline(end=b"")
                await asyncio.sleep(0.2)  # Let the console catch up
            elif res.groupdict.get("login"):
                self.logger.info("Logout successfully")
                return
            else:
                self.logger.error(
                    "Get unexpected prompt when logging out: {}".format(res)
                )
                return

    async def _close(self) -> None:
        await self._try_logout(kick_shutdown=True)
        await super()._close()

    def _send_clearline(self):
        self.send(b"\x15\r\n")

    def _send_newline(self, end=b"\n"):
        self.send(b"\r", end)

    def _interact_prompts_action(self, prompt_match):
        interact_prompts = [
            b"(?P<%s>%s)" % (group, regex)
            for group, regex in self._INTERACT_PROMPTS.items()
        ]
        interact_prompts_re = b"|".join(interact_prompts)
        interact_prompt_match = re.match(interact_prompts_re, prompt_match)
        for action in interact_prompt_match.groupdict():
            self.send(action)

    async def _setup_connection(self):
        if self._opts.get("raw_session"):
            await asyncio.sleep(1)
        else:
            # Since this is a normal session, try to login to device.
            await self._try_login(self._username, self._password, kickstart=True)
            # Now send the setup commands
            await super()._setup_connection()

    async def get_console_info(self):
        """
        By default we assume a console is directly specified by the user.
        Depending on your system, you may want to get this information from
        your local database. In such case you can override this method
        according to your needs
        """
        con_srv, con_port = self._console.split(":")

        return ConsoleInfo("CON", self.hostname, con_srv, con_port)

    async def _run_command(self, cmd, timeout=None, prompt_re=None):
        if self._opts.get("raw_session"):
            await self._stream_reader.drain()
            self.send(cmd)
            resp = await self.wait_prompt(prompt_re)
            return resp.data + resp.matched
        else:
            return await super()._run_command(cmd, timeout, prompt_re)

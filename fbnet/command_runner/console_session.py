#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) Facebook, Inc. and its affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import asyncio
import re
from typing import (
    TYPE_CHECKING,
    Any,
    AnyStr,
    Dict,
    NamedTuple,
    Optional,
    Pattern,
    Set,
    Tuple,
    Union,
)

from .command_session import SSHCommandSession
from .options import Option


if TYPE_CHECKING:
    from asyncio import AbstractEventLoop
    from fbnet.command_runner.service import FcrServiceBase
    from .command_session import ResponseMatch


class ConsoleInfo(NamedTuple):
    """
    Information about the console
    """

    contype: str
    host: str
    server: str
    port: Union[str, int]

    def __repr__(self) -> str:
        """
        pretty representation of console information
        """
        return "host:{s.host} {s.contype}: {s.server}:{s.port}".format(s=self)


class ConsoleCommandSession(SSHCommandSession):
    """
    A command session that runs over a console connections.

    Currently we only support SSH connection to the console server
    """

    _INTERACT_PROMPTS: Dict[bytes, bytes] = {b"Y": rb"Do you acknowledge\? \(Y/N\)\?"}
    _CONSOLE_PROMPTS: Dict[bytes, bytes] = {
        # For login we need to ignore output like:
        #  Last login: Mon May  8 13:53:17 on ttyS0
        b"login": b".*((?<!Last ).ogin|.sername):",
        b"passwd": rb"\n.*assword\s?:",
        # Ignore login failure message like P64639613
        b"prompt": b"\n.*[#>](?!Login incorrect)",
        b"interact_prompts": rb"Do you acknowledge\? \(Y/N\)\?",
    }

    # Certain prompts that we get during the login attemts that we will like to
    # ignore
    _CONSOLE_INGORE: Set[bytes] = {rb" to cli \]", rb"who is on this device.\]\r\n"}
    _DEFAULT_LOGOUT_COMMAND: bytes = b"exit"

    _CONSOLE_PROMPT_RE: Optional[Pattern] = None
    _CONSOLE_EXPECT_DELAY: int = 5

    _CONSOLE_LOGIN_TIMEOUT_S = Option(
        "--console_login_timeout_s",
        help="The upper bound of the time (in seconds) that FCR waits for a "
        "console server to login to the target device (only applies when a "
        "console is used to connect to a device). (default: %(default)s)",
        type=int,
        default=60,
    )

    def __init__(
        self,
        service: "FcrServiceBase",
        devinfo: Dict[str, Any],
        options: Dict[str, str],
        loop: "AbstractEventLoop",
    ) -> None:
        super().__init__(service, devinfo, options, loop)
        self._console: str = options["console"]

    @classmethod
    def _build_prompt_re(
        cls, prompts: Dict[bytes, bytes], ignore: Set[bytes]
    ) -> Pattern:
        prompts_re = [
            b"(?P<%s>%s)" % (group, regex) for group, regex in prompts.items()
        ]
        # Add a set of prompts that we want to ignore
        ignore_prompts = b"|".join((b"(%s)" % p for p in ignore))
        prompts_re.append(b"(?P<ignore>%s)" % ignore_prompts)
        prompt_re = b"|".join(prompts_re)
        return re.compile(prompt_re + rb"\s*$")

    @classmethod
    def get_prompt_re(cls) -> Pattern:
        """
        The first time this is called, we will builds the prompt for the
        console. After that we will return the pre-computed regex
        Due to this if statement and that cls._build_prompt_re method returns
        a valid Pattern, we can ensure cls_CONSOLE_PROMPT_RE is not
        none, therefore we should ignore the pyre warning
        """
        if not cls._CONSOLE_PROMPT_RE:
            cls._CONSOLE_PROMPT_RE = cls._build_prompt_re(
                cls._CONSOLE_PROMPTS, cls._CONSOLE_INGORE
            )
        return cls._CONSOLE_PROMPT_RE  # pyre-ignore

    async def dest_info(self) -> Tuple[str, Union[str, int]]:
        console = await self.get_console_info()
        self.logger.info("%s", str(console))
        return (console.server, console.port)

    async def expect(
        self, regex: Pattern, timeout: int = _CONSOLE_EXPECT_DELAY
    ) -> "ResponseMatch":
        try:
            return await asyncio.wait_for(
                self.wait_prompt(regex), timeout, loop=self._loop
            )
        except asyncio.TimeoutError as ex:
            data = []
            # This statement ensures that _stream_reader is not none
            if self._stream_reader:
                # pyre-fixme[16]: `None` has no attribute `drain`.
                data = await self._stream_reader.drain()
            raise asyncio.TimeoutError(
                "Timeout during waiting for prompt."
                f"Currently received data: {data[-200:]}"
            ) from ex

    def send(self, data: AnyStr, end: bytes = b"\n") -> None:
        """
        send some data and optionally wait for some data
        """
        if isinstance(data, str):
            data = data.encode("utf8")
        # This check ensure _stream_writer is not none, ignoring the pyre warning
        if self._stream_writer:
            self._stream_writer.write(data + end)  # pyre-ignore

    async def _try_login(  # noqa C901
        self,
        username: Optional[str] = None,
        passwd: Optional[str] = None,
        kickstart: bool = False,
        username_tried: bool = False,
        pwd_tried: bool = False,
        get_response_timeout: int = _CONSOLE_EXPECT_DELAY,
    ) -> None:
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
        try:
            res = await self._get_response(timeout=get_response_timeout)
        except asyncio.TimeoutError:
            if kickstart and username:
                # We likely didn't get anything from the console. Try sending a
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
                # TODO: It seems the original author of this session used the
                # arguments `username` and `passwd` to indicate whether the
                # username or password have been sent to the device (it will
                # set the corresponding argument to None after sending the
                # credential). This seems to be duplicated with the arguments
                # `username_tried` and `pwd_tried` we added later. If so, we'll
                # need to remove one of them
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
                raise RuntimeError("Failed to login: Missing password")
            self.send(self._password)
            return await self._try_login(
                username_tried=username_tried,
                pwd_tried=True,
                get_response_timeout=self._CONSOLE_LOGIN_TIMEOUT_S,
            )

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

    async def _get_response(self, timeout: int) -> "ResponseMatch":
        # A small delay to avoid having to match extraneous input
        await asyncio.sleep(0.1)
        res = await self.expect(self.get_prompt_re(), timeout=timeout)
        return res

    async def _try_logout(self, kick_shutdown: bool = False) -> None:
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
        # pyre-fixme[16]: `None` has no attribute `write`.
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
                    self.logger.exception("Console session timed out while logging out")
                    return
            except Exception as ex:
                self.logger.exception(f"Console session log out failure: {ex}")
                return

            if res.groupdict.get("ignore"):
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

    def _send_clearline(self) -> None:
        self.send(b"\x15\r\n")

    def _send_newline(self, end: bytes = b"\n") -> None:
        self.send(b"\r", end)

    def _interact_prompts_action(self, prompt_match: AnyStr) -> None:
        interact_prompts = [
            b"(?P<%s>%s)" % (group, regex)
            for group, regex in self._INTERACT_PROMPTS.items()
        ]
        interact_prompts_re = b"|".join(interact_prompts)
        interact_prompt_match = re.match(
            interact_prompts_re, prompt_match  # pyre-ignore
        )
        # Ignoring the pyre warning since the logic in _try_login ensures we
        # find a match
        for action in interact_prompt_match.groupdict():  # pyre-ignore
            self.send(action)

    async def _setup_connection(self) -> None:
        if self._opts.get("raw_session"):
            await asyncio.sleep(1)
        else:
            # Since this is a normal session, try to login to device.
            await self._try_login(self._username, self._password, kickstart=True)
            # Now send the setup commands
            await super()._setup_connection()

    async def get_console_info(self) -> ConsoleInfo:
        """
        By default we assume a console is directly specified by the user.
        Depending on your system, you may want to get this information from
        your local database. In such case you can override this method
        according to your needs
        """
        con_srv, con_port = self._console.split(":")
        return ConsoleInfo("CON", self.hostname, con_srv, con_port)

    async def _run_command(
        self,
        cmd: str,
        timeout: Optional[int] = None,
        prompt_re: Optional[Pattern] = None,
    ) -> Union[str, bytes]:
        if self._opts.get("raw_session"):
            # This statement ensures _stream_reader is not none
            if self._stream_reader:
                # pyre-fixme[16]: `None` has no attribute `drain`.
                await self._stream_reader.drain()
            self.send(cmd)
            resp = await self.wait_prompt(prompt_re)
            return resp.data + resp.matched
        else:
            return await super()._run_command(cmd, timeout, prompt_re)

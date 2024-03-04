#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# pyre-unsafe

# Copyright (c) Facebook, Inc. and its affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import asyncio
import re
from typing import (
    Any,
    AnyStr,
    Dict,
    List,
    NamedTuple,
    Optional,
    Pattern,
    Tuple,
    TYPE_CHECKING,
    Union,
)

from fbnet.command_runner.exceptions import (
    PermissionErrorException,
    RuntimeErrorException,
)

from .command_session import SSHCommandSession
from .device_info import IPInfo
from .options import Option


if TYPE_CHECKING:
    from asyncio import AbstractEventLoop

    from fbnet.command_runner.service import FcrServiceBase

    from .command_session import ResponseMatch
    from .device_info import DeviceInfo


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

    # The three default class variables below let you preset the prompts in-case vendor is unknown.
    # If you would like to hard-code or preset the prompts for specific devices, you can do so
    # by hardcoding _CONFIG_CONSOLE_PROMPTS_RE_DICT and _CONFIG_INTERACT_PROMPTS_RE_DICT
    _DEFAULT_INTERACT_PROMPTS: Dict[bytes, bytes] = {
        b"Y": rb"Do you acknowledge\? \(Y/N\)\?"
    }
    _DEFAULT_CONSOLE_PROMPTS: Dict[bytes, bytes] = {
        # For login we need to ignore output like:
        #   Last login: Mon May  8 13:53:17 on ttyS0
        b"login": rb".*((?<!Last ).ogin|.sername):\s*$",
        b"passwd": rb"\n.*assword\s?:\s*$",
        # Ignore login failure message like P64639613
        b"prompt": b"\n.*[$#>%](?!Login incorrect)",
        b"interact_prompts": rb"Do you acknowledge\? \(Y/N\)\?",
        # Ignore these prompts during login attempts
        b"ignore_prompts": b"( to cli \\])|(who is on this device.\\]\\r\\n)|(Press RETURN to get started\r\n)",
    }
    _DEFAULT_CONSOLE_PROMPTS_RE: Optional[Pattern] = None

    _DEFAULT_LOGOUT_COMMAND: bytes = b"exit"

    _CONSOLE_EXPECT_DELAY: int = 5

    _CONSOLE_LOGIN_TIMEOUT_S = Option(
        "--console_login_timeout_s",
        help="The upper bound of the time (in seconds) that FCR waits for a "
        "console server to login to the target device (only applies when a "
        "console is used to connect to a device). (default: %(default)s)",
        type=int,
        default=60,
    )

    _CONFIG_CONSOLE_PROMPTS_RE_DICT: Optional[Dict[int, Pattern]] = None
    _CONFIG_INTERACT_PROMPTS_RE_DICT: Optional[Dict[int, Dict[bytes, bytes]]] = None

    def __init__(
        self,
        service: "FcrServiceBase",
        devinfo: "DeviceInfo",
        options: Dict[str, Any],
        loop: "AbstractEventLoop",
    ) -> None:
        super().__init__(service, devinfo, options, loop)
        self._console: str = options["console"]

    @classmethod
    def _build_and_set_prompts_re_dict(
        cls,
        vendor_prompts: Optional[Dict[int, Dict[bytes, bytes]]] = None,
        vendor_interact_prompts: Optional[Dict[int, Dict[bytes, bytes]]] = None,
    ) -> None:
        """
        This method takes in a dictionary of a dictionary of vendor specific prompts, builds each
        set of vendor prompts and adds them to the instance dictionary of regexs CONFIG_CONSOLE_PROMPTS_RE_DICT to be matched
        against console prompts. Also sets the interact_prompts dictionary,
        if applicable (unneccessary to compile regexes until there is a match).
        """
        cls._CONFIG_CONSOLE_PROMPTS_RE_DICT = {}
        cls._CONFIG_INTERACT_PROMPTS_RE_DICT = {}

        if vendor_prompts:
            for vendor, prompts in vendor_prompts.items():
                cls._CONFIG_CONSOLE_PROMPTS_RE_DICT[vendor] = (  # pyre-ignore
                    cls._build_individual_prompt_re(prompts)
                )
        if vendor_interact_prompts:
            cls._CONFIG_INTERACT_PROMPTS_RE_DICT = vendor_interact_prompts

    @classmethod
    def _build_individual_prompt_re(
        cls, prompts: Optional[Dict[bytes, bytes]] = None
    ) -> Pattern:
        """
        This function takes in a dictionary of regexes of a single vendor to match prompts against,
        then compiles all the prompts into a single grouped regex and returns the regex.
        """
        prompts_re = []
        if prompts:
            prompts_re = [
                b"(?P<%s>%s)" % (group, regex) for group, regex in prompts.items()
            ]
        prompt_re = b"|".join(prompts_re)
        return re.compile(prompt_re + rb"\s*$")

    @classmethod
    def get_default_console_prompt_re(cls) -> Pattern:
        # This check ensures that _DEFAULT_CONSOLE_PROMPTS_RE is not None, ignoring pyre warning
        if not cls._DEFAULT_CONSOLE_PROMPTS_RE:
            cls._DEFAULT_CONSOLE_PROMPTS_RE = cls._build_individual_prompt_re(
                cls._DEFAULT_CONSOLE_PROMPTS
            )
        return cls._DEFAULT_CONSOLE_PROMPTS_RE  # pyre-ignore

    @classmethod
    def get_prompt_re(cls, vendor_name: Optional[int] = None) -> Pattern:
        """
        This method takes in a vendor name and retrieves the pre-compiled group regex
        corresponding to that vendor from the _CONFIG_CONSOLE_PROMPTS_RE_DICT. If the vendor is not given or
        does not already exist in the dictionary, return the default (hard-coded) regex.
        If the default regex is not already built, build it and then set it.
        """
        # This check ensure that _CONFIG_CONSOLE_PROMPTS_RE_DICT is not None, ignoring pyre warning
        if cls._CONFIG_CONSOLE_PROMPTS_RE_DICT and vendor_name:
            return cls._CONFIG_CONSOLE_PROMPTS_RE_DICT.get(  # pyre-ignore
                vendor_name, cls.get_default_console_prompt_re()
            )

        return cls.get_default_console_prompt_re()

    async def dest_info(self) -> Tuple[List[IPInfo], int, str, str]:
        console = await self.get_console_info()
        self.logger.info(f"{str(console)}")

        # By default we assume a console is directly specified by the user,
        # so we don't want to raise error messages that it is not pingable
        # Set is_pingable to True since check_ip method always returns True
        is_pingable = True

        return (
            [IPInfo(console.server, is_pingable)],
            console.port,
            self._username,
            self._password,
        )

    async def expect(
        self, regex: Pattern, timeout: int = _CONSOLE_EXPECT_DELAY
    ) -> "ResponseMatch":
        try:
            return await asyncio.wait_for(
                self.wait_prompt(prompt_re=regex, timeout=timeout),
                timeout,
                loop=self._loop,
            )
        except asyncio.TimeoutError as ex:
            data = []
            # This statement ensures that _stream_reader is not none
            if self._stream_reader:
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

        if res.groupdict.get("ignore_prompts"):
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
                raise PermissionErrorException(
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
                raise PermissionErrorException(
                    "Login failure, possibly incorrect username or password, "
                    "or device refuses to login."
                )
            if passwd is None:
                # passwd information not available
                # Likely we have alreay sent the password. Bail out instead
                # of getting stuck in a loop.
                raise RuntimeErrorException("Failed to login: Missing password")
            self.send(self._password)
            return await self._try_login(
                username_tried=username_tried,
                pwd_tried=True,
                get_response_timeout=self._CONSOLE_LOGIN_TIMEOUT_S,
            )

        elif res.groupdict.get("interact_prompts"):
            # E.g. send 'Y' to to satisfy the post login prompt on Nokia device
            self._interact_prompts_action(res.groupdict.get("interact_prompts"))
            return await self._try_login(
                username_tried=username_tried, pwd_tried=pwd_tried
            )

        elif res.groupdict.get("prompt"):
            # Finally we matched a prompt. we are done
            return self._send_newline()

        else:
            raise RuntimeErrorException("Matched no group: %s" % (res.groupdict))

    async def _get_response(self, timeout: int) -> "ResponseMatch":
        # A small delay to avoid having to match extraneous input
        await asyncio.sleep(0.1)
        res = await self.expect(
            self.get_prompt_re(self._devinfo.vendor_name), timeout=timeout
        )
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

        logout_cmd = (
            self._devinfo.vendor_data.exit_command or self._DEFAULT_LOGOUT_COMMAND
        )
        self.logger.info(f"Logout from device, running logout command: {logout_cmd}")
        self._stream_writer.write(logout_cmd + b"\n")
        # Make sure we logout of the system
        while True:
            try:
                res = await self._get_response(timeout=self._CONSOLE_EXPECT_DELAY)
            except asyncio.TimeoutError:
                if kick_shutdown:
                    self.logger.info(
                        "Received first timeout while matching console prompt, "
                        "sending a new line character to the console"
                    )
                    self._send_newline()
                    return await self._try_logout()
                else:
                    self.logger.exception("Console session timed out while logging out")
                    return
            except Exception:
                self.logger.exception("Console session log out failure")
                return

            if res.groupdict.get("ignore_prompts"):
                # If we match anything in the ignore prompts, set a \r\n
                self._send_newline(end=b"")
                await asyncio.sleep(0.2)  # Let the console catch up
            elif res.groupdict.get("login"):
                self.logger.info("Logout successfully")
                return
            else:
                self.logger.error(f"Get unexpected prompt when logging out: {res}")
                return

    async def _close(self) -> None:
        await self._try_logout(kick_shutdown=True)
        await super()._close()

    def _send_clearline(self) -> None:
        self.send(b"\x15\r\n")

    def _send_newline(self, end: bytes = b"\n") -> None:
        self.send(b"\r", end)

    def _interact_prompts_action(self, prompt_match: AnyStr) -> None:
        # Check if to use default interactive prompts or configured prompts
        vendor_interact_prompts = self._DEFAULT_CONSOLE_PROMPTS
        if (
            self._CONFIG_INTERACT_PROMPTS_RE_DICT
            and self._devinfo.vendor_name in self._CONFIG_INTERACT_PROMPTS_RE_DICT
        ):
            vendor_interact_prompts = self._CONFIG_INTERACT_PROMPTS_RE_DICT.get(
                self._devinfo.vendor_name
            )
        interact_prompts = [
            b"(?P<%s>%s)" % (group, regex)
            # pyre-fixme[16]: `Optional` has no attribute `items`.
            for group, regex in vendor_interact_prompts.items()
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
        command: bytes,
        timeout: Optional[int] = None,
        prompt_re: Optional[Pattern] = None,
    ) -> bytes:
        if self._opts.get("raw_session"):
            # This statement ensures _stream_reader is not none
            if self._stream_reader:
                await self._stream_reader.drain()
            self.send(command)
            resp = await self.wait_prompt(prompt_re)
            return resp.data + resp.matched
        else:
            return await super()._run_command(command, timeout, prompt_re)

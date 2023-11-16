#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) Facebook, Inc. and its affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import argparse
import asyncio
import cmd
import getpass

from fbnet.command_runner.thrift_client import AsyncioThriftClient
from fbnet.command_runner_asyncio.CommandRunner import ttypes
from fbnet.command_runner_asyncio.CommandRunner.Command import Client as FcrClient
from termcolor import cprint


"""
A simple CLI to run commands using FCR service

"""


class Fcr:
    def __init__(self, options, loop=None):
        self._loop = loop or asyncio.get_event_loop()
        self._options = options

    async def open_client(self):
        self._client = await AsyncioThriftClient(
            FcrClient, self._options["fcr_host"], self._options["fcr_port"]
        )

    async def run(self, cmd, device, *args, **kwargs):
        return await self._client.run(cmd, device, *args, **kwargs)

    async def bulk_run(self, cmdmap, *args, **kwargs):
        return await self._client.bulk_run(cmdmap, *args, **kwargs)

    async def open_session(self, device, *args, **kwargs):
        return await self._client.open_session(device, *args, **kwargs)

    async def run_session(self, cmd, *args, **kwargs):
        return await self._client.run_session(cmd, *args, **kwargs)

    async def close_session(self, *args, **kwargs):
        return await self._client.close_session(*args, **kwargs)


class DeviceCli(cmd.Cmd, Fcr):
    _INTRO = """
    Opening session to {s.num_devices} devices
"""

    def __init__(self, devices, options, loop):
        cmd.Cmd.__init__(self)
        Fcr.__init__(self, options, loop)

        self._options = options
        self._devices = [self._create_device(d) for d in devices]
        self.prompt = "{s.user}@fcr [d={s.num_devices}] $ ".format(s=self)

        self.intro = self._INTRO.format(s=self)
        self.opened = False

    def _run_event_loop(self, f, *args, **kwargs):
        coro = f(*args, **kwargs)
        return self._loop.run_until_complete(coro)

    @property
    def num_devices(self):
        return len(self._devices)

    @property
    def fcr_host(self):
        return self._options["fcr_host"]

    @property
    def fcr_port(self):
        return self._options["fcr_port"]

    @property
    def user(self):
        return self._options["user"]

    @property
    def passwd(self):
        return self._options["passwd"]

    def do_EOF(self, line):
        return self.do_exit()

    def do_exit(self, line=None):
        print()
        return True

    def default(self, line):
        results = self._run(line)
        self._format_results(results)

    def completenames(self, text, line, begidx, endidx):
        res = self._run_first("compgen -abc {}".format(text))
        comps = res.output.splitlines()[1:]
        return comps

    def completedefault(self, text, line, begidx, endidx):
        word = line.split()[-1]

        cmd = "compgen -d -S /  {0}; compgen -f {0}"
        res = self._run_first(cmd.format(word))
        comps = res.output.splitlines()[1:]

        pfxlen = len(word) - len(text)
        comps = {c[pfxlen:] for c in comps}

        # We get duplicate entries for files and directories.
        comps = [c for c in comps if c and c + "/" not in comps]

        return comps

    def _create_device(self, name):
        return ttypes.Device(hostname=name, username=self.user, password=self.passwd)

    def _format_output(self, devname, command_result):
        head = " {0} ".format(devname)
        cprint("{0:-^60}".format(head), "red", attrs=["bold"])
        print(command_result.output)
        print("\n")

    def _format_results(self, results):
        print()
        for dev, res in results.items():
            self._format_output(dev, res)

    def __enter__(self):
        self._open()
        return self

    def __exit__(self, *args):
        self._close()

    def _run_coroutines(self, coros):
        """
        Run coroutines in parallel
        """
        return self._loop.run_until_complete(asyncio.gather(*coros, loop=self._loop))

    def _open(self):
        self._run_event_loop(self.open_client)

        coros = [self.open_session(d) for d in self._devices]
        self._sessions = self._run_coroutines(coros)

    def _close(self):
        coros = [self.close_session(s) for s in self._sessions]
        self._run_coroutines(coros)
        self._client.close()

    def _run(self, cmd, **kwargs):
        coros = [self.run_session(s, cmd, **kwargs) for s in self._sessions]
        results = self._run_coroutines(coros)
        return {dev.hostname: res for dev, res in zip(self._devices, results)}

    def _run_first(self, cmd, **kwargs):
        return self._run_event_loop(self.run_session, self._sessions[0], cmd, **kwargs)


class FCR(cmd.Cmd):
    def __init__(self, devices):
        super().__init__()

        self.prompt = "FCR $ "

        self._loop = asyncio.get_event_loop()

        self._options = {
            "fcr_host": "localhost",
            "fcr_port": 5000,
            "user": "netbot",
            "passwd": "bot1234",  # Super Secure password :)
        }
        self._devices = devices or ["dev-001"]

    def do_cred(self, line):
        user = getpass.getuser()
        user = input("Username [%s]: " % user) or user
        passwd = getpass.getpass("%s password: " % user)

        self._option["user"] = user
        self._option["passwd"] = passwd

    def do_devices(self, line):
        if line:
            self._devices = line.split()

        print()
        self.columnize(self._devices)
        print()

    def do_login(self, line):
        with DeviceCli(self._devices, self._options, self._loop) as cli:
            cli.cmdloop()

    def do_EOF(self, line):
        return self.do_exit()

    def do_exit(self, line=None):
        print()
        return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("devices", nargs="+", help="list of devices")
    args = parser.parse_args()
    # pyre-fixme[16]: Callable `bin` has no attribute `fcr-cli`.
    fcr = FCR(args.devices)
    try:
        fcr.cmdloop()
    except KeyboardInterrupt:
        print("Received keyboard interrupt")


if __name__ == "__main__":
    # pyre-fixme[16]: Callable `bin` has no attribute `fcr-cli`.
    main()  # pragma: no cover

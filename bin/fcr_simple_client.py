#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# pyre-unsafe

# Copyright (c) Facebook, Inc. and its affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import asyncio
import getpass

import click
from fbnet.command_runner.thrift_client import AsyncioThriftClient
from fbnet.command_runner_asyncio.CommandRunner import ttypes
from fbnet.command_runner_asyncio.CommandRunner.Command import Client as FcrClient


class FCRSvcClient:
    def __init__(self, user, fcr_host="localhost", fcr_port=5000):
        self.loop = asyncio.get_event_loop()
        self._user = user
        self._passwd = None
        self._fcr_host = fcr_host
        self._fcr_port = fcr_port
        self._fcr_client = None

    @property
    def user(self):
        return self._user

    @property
    def passwd(self):
        if not self._passwd:
            self._passwd = getpass.getpass("%s Password: " % self._user)
        return self._passwd

    def _get_fcr_client(self):
        return AsyncioThriftClient(FcrClient, self._fcr_host, self._fcr_port)

    async def _fcr_api_caller(self, api, *args, **kwargs):
        async with self._get_fcr_client() as client:
            api = getattr(client, api)
            return await api(*args, **kwargs)

    def get_fcr_api(self, apiname):
        def fcr_api_wrapper(*args, **kwargs):
            return self.loop.run_until_complete(
                self._fcr_api_caller(apiname, *args, **kwargs)
            )

        return fcr_api_wrapper

    def __getattr__(self, attr):
        if attr in ["run", "getCounters"]:
            return self.get_fcr_api(attr)
        raise AttributeError()


@click.group()
@click.option("--fcr_host", default="localhost", help="Hostname for fcr service")
@click.option("--fcr_port", default=5000, type=int, help="Port for fcr service")
@click.option("--user", default=getpass.getuser(), help="username to login as")
@click.pass_context
def fcr(ctx, fcr_host, fcr_port, user):
    ctx.obj = FCRSvcClient(user, fcr_host, fcr_port)


@fcr.command()
@click.pass_context
def counters(ctx):
    res = ctx.obj.getCounters()
    for counter, value in res.items():
        print("{0:15d}: {1}".format(value, counter))


@fcr.command()
@click.option("--host", default="localhost", help="device name")
@click.option("--console", help="console")
@click.option("--timeout", type=int, help="timeout")
@click.option("--exit_prompt", help="exit prompt")
@click.option("--mgmt_ip", is_flag=True, help="use mgmt ips")
@click.option("--ip_address", help="address to use to connect to device")
@click.option("--port", help="port to use to connect to device")
@click.argument("cmd", nargs=-1)
@click.pass_context
def run(
    ctx,
    host,
    cmd,
    console=None,
    timeout=None,
    exit_prompt=None,
    mgmt_ip=False,
    ip_address=None,
    port=None,
):
    cmd = " ".join(cmd)
    command_prompts = None

    if exit_prompt:
        command_prompts = {"exit": exit_prompt}
        cmd = cmd + "\nexit"

    d = ttypes.Device(
        hostname=host,
        username=ctx.obj.user,
        password=ctx.obj.passwd,
        console=console or "",
        mgmt_ip=mgmt_ip or False,
        ip_address=ip_address,
        command_prompts=command_prompts,
        session_data=ttypes.SessionData(extra_options={"port": port}) if port else None,
    )

    res = ctx.obj.run(cmd, d, timeout)
    print(res)


if __name__ == "__main__":
    # pyre-fixme[16]: Callable `bin` has no attribute `fcr_simple_client`.
    fcr()

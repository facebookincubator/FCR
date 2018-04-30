#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2017-present, Facebook, Inc.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree. An additional grant
# of patent rights can be found in the PATENTS file in the same directory.
#

import asyncio
import random
import re
from itertools import islice

from fbnet.command_runner_asyncio.CommandRunner.Command import Iface as FcrIface
from fbnet.command_runner_asyncio.CommandRunner import ttypes, constants

from fb303_asyncio.FacebookBase import FacebookBase

from .command_session import CommandSession
from .counters import Counters
from .options import Option


class CommandHandler(Counters, FacebookBase, FcrIface):
    """
    Command implementation for api defined in thrift for command runner
    """

    _COUNTER_PREFIX = "fbnet.command_runner"
    _LB_THRESHOLD = 100

    REMOTE_CALL_OVERHEAD = Option(
        '--remote_call_overhead',
        help="Overhead for running commands remotely (for bulk calls)",
        type=int, default=20)

    LB_THRESHOLD = Option(
        '--lb_threshold',
        help='''Load Balance threashold for bulk_run calls. If number of
        devices is greater than this threashold, the requests are broken and
        send to other instances using bulk_run_local() api''',
        type=int, default=100)

    BULK_SESSION_LIMIT = Option(
        '--bulk_session_limit',
        help='''session limit above which we reject the bulk run local
        calls''',
        type=int, default=200)

    BULK_RETRY_LIMIT = Option(
        '--bulk_retry_limit',
        help='''number of times to retry bulk call on the remote instances''',
        type=int, default=5)

    BULK_RUN_JITTER = Option(
        '--bulk_run_jitter',
        help='''A random delay added for bulk commands to stagger the calls to
        distribute the load.''',
        type=int, default=5)

    BULK_RETRY_DELAY_MIN = Option(
        '--bulk_retry_delay_min',
        help='''number of seconds to wait before retrying''',
        type=int, default=5)

    BULK_RETRY_DELAY_MAX = Option(
        '--bulk_retry_delay_max',
        help='''number of seconds to wait before retrying''',
        type=int, default=10)

    _bulk_session_count = 0

    def __init__(self, service, name=None):
        Counters.__init__(self, service, name)
        FacebookBase.__init__(self, service.app_name)
        FcrIface.__init__(self)

        self.service.register_stats_mgr(self)

    def cleanup(self):
        pass

    @classmethod
    def register_counters(cls, stats_mgr):
        stats_mgr.register_counter("bulk_run.remote")
        stats_mgr.register_counter("bulk_run.local")
        stats_mgr.register_counter("bulk_run.local.overload_error")

    def getCounters(self):
        ret = {}
        for key, value in self.counters.items():
            if not key.startswith(self._COUNTER_PREFIX):
                key = self._COUNTER_PREFIX + "." + key
            ret[key] = value() if callable(value) else value
        return ret

    async def run(self,
                  command,
                  device,
                  timeout,
                  open_timeout,
                  client_ip,
                  client_port):

        result = await self._run_commands([command],
                                          device,
                                          timeout,
                                          open_timeout,
                                          client_ip,
                                          client_port)
        return result[0]

    def _bulk_failure(self, device_to_commands, message):

        def command_failures(cmds):
            return [
                ttypes.CommandResult(output=message,
                                     status=constants.FAILURE_STATUS,
                                     command=cmd)
                for cmd in cmds
            ]

        return {
            self._get_result_key(dev): command_failures(cmds)
            for dev, cmds in device_to_commands.items()
        }

    async def bulk_run(self,
                       device_to_commands,
                       timeout,
                       open_timeout,
                       client_ip,
                       client_port):

        if ((len(device_to_commands) < self.LB_THRESHOLD) and
                (self._bulk_session_count < self.BULK_SESSION_LIMIT)):
            # Run these command locally.
            self.incrementCounter('bulk_run.local')
            return await self.bulk_run_local(device_to_commands, timeout,
                                             open_timeout, client_ip, client_port)

        async def _remote_task(chunk):
            # Run the chunk of commands on remote instance
            self.incrementCounter('bulk_run.remote')
            retry_count = 0
            while True:
                try:
                    return await self._bulk_run_remote(
                        chunk, timeout, open_timeout,
                        client_ip, client_port)
                except ttypes.InstanceOverloaded as ioe:
                    # Instance we ran the call on was overloaded. We can retry
                    # the command again, hopefully on a different instance
                    self.incrementCounter('bulk_run.remote.overload_error')
                    self.logger.error("Instance Overloaded: %d: %s", retry_count, ioe)
                    if retry_count > self.BULK_RETRY_LIMIT:
                        # Fail the calls
                        return self._bulk_failure(chunk, str(ioe))
                    # Stagger the retries
                    delay = random.uniform(self.BULK_RETRY_DELAY_MIN,
                                           self.BULK_RETRY_DELAY_MAX)
                    await asyncio.sleep(delay)
                    retry_count += 1

        # Split the request into chunks and run them on remote hosts
        tasks = [_remote_task(chunk)
                 for chunk in self._chunked_dict(device_to_commands,
                                                 self.LB_THRESHOLD)]

        all_results = {}
        for task in asyncio.as_completed(tasks, loop=self.loop):
            result = await task
            all_results.update(result)

        return all_results

    async def bulk_run_local(self,
                             device_to_commands,
                             timeout,
                             open_timeout,
                             client_ip,
                             client_port):

        devices = sorted(device_to_commands.keys(), key=lambda d: d.hostname)

        session_count = self._bulk_session_count
        if session_count + len(device_to_commands) > self.BULK_SESSION_LIMIT:
            self.logger.error("To many session open: %d", session_count)
            raise ttypes.InstanceOverloaded(
                message='Too many session open: %d' % session_count)

        self._bulk_session_count += len(devices)

        async def _run_one_device(device):
            # Instead of running all commands at once, stagger the commands to
            # distribute the load
            delay = random.uniform(0, self.BULK_RUN_JITTER)
            await asyncio.sleep(delay)
            return await self._run_commands(
                device_to_commands[device],
                device,
                timeout,
                open_timeout,
                client_ip,
                client_port,
                return_exceptions=True)

        try:
            commands = []
            for device in devices:
                commands.append(_run_one_device(device))

            # Run commands in parallel
            cmd_results = await asyncio.gather(*commands,
                                               loop=self.loop,
                                               return_exceptions=True)
        finally:
            self._bulk_session_count -= len(devices)

        return {self._get_result_key(dev): res
                for dev, res in zip(devices, cmd_results)}

    async def open_session(self,
                           device,
                           open_timeout,
                           idle_timeout,
                           client_ip,
                           client_port):

        return await self._open_session(
            device, open_timeout, idle_timeout,
            client_ip, client_port, raw_session=False)

    async def run_session(self,
                          tsession,
                          command,
                          timeout,
                          client_ip,
                          client_port):
        return await self._run_session(
            tsession, command, timeout, client_ip, client_port)

    async def close_session(self, tsession, client_ip, client_port):
        try:
            session = CommandSession.get(tsession.id, client_ip, client_port)
            await session.close()
        except Exception as e:
            raise ttypes.SessionException(
                message="close_session failed: %r" % (e)) from e

    async def open_raw_session(self,
                               device,
                               open_timeout,
                               idle_timeout,
                               client_ip,
                               client_port):
        return await self._open_session(
            device, open_timeout, idle_timeout, client_ip, client_port,
            raw_session=True)

    async def run_raw_session(self,
                              tsession,
                              command,
                              timeout,
                              prompt_regex,
                              client_ip,
                              client_port):
        if not prompt_regex:
            raise ttypes.SessionException(message="prompt_regex not specified")

        prompt_re = re.compile(prompt_regex.encode('utf8'), re.M)

        return await self._run_session(
            tsession, command, timeout, client_ip, client_port, prompt_re)

    async def close_raw_session(self, tsession, client_ip, client_port):
        return await self.close_session(tsession, client_ip, client_port)

    async def _open_session(self,
                            device,
                            open_timeout,
                            idle_timeout,
                            client_ip,
                            client_port,
                            raw_session=False):
        options = self._get_options(
            device, client_ip, client_port, open_timeout, idle_timeout,
            raw_session=raw_session)

        try:
            devinfo = await self._lookup_device(device)
            session = await devinfo.setup_session(self.service,
                                                  device,
                                                  options,
                                                  loop=self.loop)

            return ttypes.Session(id=session.id,
                                  name=session.hostname,
                                  hostname=device.hostname)
        except Exception as e:
            raise ttypes.SessionException(
                message='open_session failed: %r' % e) from e

    async def _run_session(self,
                           tsession,
                           command,
                           timeout,
                           client_ip,
                           client_port,
                           prompt_re=None):
        try:
            session = CommandSession.get(tsession.id, client_ip, client_port)
            return await self._run_command(session, command, timeout,
                                           prompt_re)
        except Exception as e:
            raise ttypes.SessionException(
                message="run_session failed: %r" % (e)) from e

    def _get_result_key(self, device):
        # TODO: just returning the hostname for now. Some additional processing
        # may be required e.g. using shortnames, adding console info, etc
        return device.hostname

    async def _run_command(self, session, command, timeout, prompt_re=None):
        output = await session.run_command(
            command.encode('utf8'), timeout=timeout, prompt_re=prompt_re)
        return ttypes.CommandResult(
            output=output.decode('utf8', errors='ignore'),
            status=session.exit_status or constants.SUCCESS_STATUS,
            command=command)

    async def _run_commands(self,
                            commands,
                            device,
                            timeout,
                            open_timeout,
                            client_ip,
                            client_port,
                            return_exceptions=False):

        options = self._get_options(
            device, client_ip, client_port, open_timeout, timeout)

        if device.command_prompts:
            options['command_prompts'] = {
                c.encode(): p.encode() for c, p in device.command_prompts.items()}

        command = ""

        try:
            devinfo = await self._lookup_device(device)

            async with devinfo.create_session(self.service,
                                              device,
                                              options,
                                              loop=self.loop) as session:

                results = []
                for command in commands:
                    result = await self._run_command(session, command, timeout)
                    results.append(result)

                return results

        except Exception as e:
            if not isinstance(e, ttypes.SessionException):
                e = ttypes.SessionException(message='%r' % e)
            if return_exceptions:
                return [ttypes.CommandResult(output='',
                                             status='%r' % e,
                                             command=command)]
            else:
                raise e from e

    def _chunked_dict(self, data, chunk_size):
        '''split the dict into smaller dicts'''
        items = iter(data.items())  # get an iterator for items
        for _ in range(0, len(data), chunk_size):
            yield dict(islice(items, chunk_size))

    async def _bulk_run_remote(self,
                               device_to_commands,
                               timeout,
                               open_timeout,
                               client_ip,
                               client_port):

        # Determine a timeout for remote call.
        call_timeout = open_timeout + timeout
        remote_timeout = timeout - self.REMOTE_CALL_OVERHEAD

        # Make sure we have a sane timeout value
        assert remote_timeout > 10, \
            "timeout: '%d' value too low for bulk_run" % timeout

        async with self._get_fcr_client(timeout=call_timeout) as client:
            result = await client.bulk_run_local(device_to_commands,
                                                 remote_timeout,
                                                 open_timeout, client_ip, client_port)
            return result

    def _lookup_device(self, device):
        return self.service.device_db.get(device)

    def _get_fcr_client(self, timeout):
        return self.service.get_fcr_client(timeout=timeout)

    def _get_options(self, device, client_ip, client_port,
                     open_timeout, idle_timeout, raw_session=False):
        options = {
            "username": self._get_device_username(device),
            "password": self._get_device_password(device),
            "console": device.console,
            "command_prompts": {},
            "client_ip": client_ip,
            "client_port": client_port,
            "mgmt_ip": device.mgmt_ip or False,
            "open_timeout": open_timeout,
            "idle_timeout": idle_timeout,
            "ip_address": device.ip_address,
            "session_type": device.session_type,
            "device": device,
            "raw_session": raw_session,
        }

        if device.command_prompts:
            options['command_prompts'] = {
                c.encode(): p.encode() for c, p in device.command_prompts.items()}

        return options

    def _get_device_username(self, device):
        return device.username

    def _get_device_password(self, device):
        # If the username is specified then password must also be specified.
        if device.username:
            return self._decrypt(device.password)

    def _decrypt(self, data):
        return data

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
from itertools import islice

from fbnet.command_runner_asyncio.CommandRunner.Command import Iface as FcrIface
from fbnet.command_runner_asyncio.CommandRunner import ttypes, constants

from fb303_asyncio.FacebookBase import FacebookBase

from .command_session import CommandSession
from .counters import Counters


class CommandHandler(Counters, FacebookBase, FcrIface):
    """
    Command implementation for api defined in thrift for command runner
    """

    _COUNTER_PREFIX = "fbnet.command_runner"
    _LB_THRESHOLD = 100

    def __init__(self, service, name=None):
        Counters.__init__(self, service, name)
        FacebookBase.__init__(self, service.app_name)
        FcrIface.__init__(self)

        self.service.register_stats_mgr(self)

    @classmethod
    def register_counters(cls, stats_mgr):
        stats_mgr.register_counter("bulk_run.remote")
        stats_mgr.register_counter("bulk_run.local")

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

    async def bulk_run(self,
                       device_to_commands,
                       timeout,
                       open_timeout,
                       client_ip,
                       client_port):

        if len(device_to_commands) < self._LB_THRESHOLD:
            # Run these command locally.
            self.incrementCounter('bulk_run.local')
            return await self.bulk_run_local(device_to_commands, timeout,
                                             open_timeout, client_ip, client_port)

        def _remote_task(chunk):
            # Run the chunk of commands on remote instance
            self.incrementCounter('bulk_run.remote')
            return self._bulk_run_remote(chunk, timeout, open_timeout,
                                         client_ip, client_port)

        # Split the request into chunks and run them on remote hosts
        tasks = [_remote_task(chunk)
                 for chunk in self._chunked_dict(device_to_commands,
                                                 self._LB_THRESHOLD)]

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

        commands = []
        for device in devices:
            cmd = self._run_commands(
                device_to_commands[device],
                device,
                timeout,
                open_timeout,
                client_ip,
                client_port,
                return_exceptions=True)
            commands.append(cmd)

        # Run commands in parallel
        cmd_results = await asyncio.gather(*commands,
                                           loop=self.loop,
                                           return_exceptions=True)

        return {self._get_result_key(dev): res
                for dev, res in zip(devices, cmd_results)}

    async def open_session(self,
                           device,
                           open_timeout,
                           idle_timeout,
                           client_ip,
                           client_port):

        options = self._get_command_options(
            device, client_ip, client_port, open_timeout, idle_timeout)

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

    async def run_session(self,
                          tsession,
                          command,
                          timeout,
                          client_ip,
                          client_port):
        try:
            session = CommandSession.get(tsession.id, client_ip, client_port)
            return await self._run_command(session, command, timeout)

        except Exception as e:
            raise ttypes.SessionException(
                message="run_session failed: %r" % (e)) from e

    async def close_session(self, tsession, client_ip, client_port):
        try:
            session = CommandSession.get(tsession.id, client_ip, client_port)
            await session.close()
        except Exception as e:
            raise ttypes.SessionException(
                message="close_session failed: %r" % (e)) from e

    def _get_result_key(self, device):
        # TODO: just returning the hostname for now. Some additional processing
        # may be required e.g. using shortnames, adding console info, etc
        return device.hostname

    async def _run_command(self, session, command, timeout):
        output = await session.run_command(command.encode('utf8'), timeout)
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

        options = self._get_command_options(
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
            if return_exceptions:
                return [ttypes.CommandResult(output='',
                                             status="run failed: %r" % (e),
                                             command=command)]
            else:
                raise ttypes.SessionException(
                    message="run failed: %r" % (e)) from e

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
        remote_timeout = timeout - self._remote_call_overhead

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

    def _get_command_options(self, device, client_ip, client_port,
                             open_timeout, idle_timeout):
        options = {
            "username": device.username,
            "password": self._decrypt(device.password),
            "console": device.console,
            "command_prompts": {},
            "client_ip": client_ip,
            "client_port": client_port,
            "open_timeout": open_timeout,
            "idle_timeout": idle_timeout,
        }

        if device.command_prompts:
            options['command_prompts'] = {
                c.encode(): p.encode() for c, p in device.command_prompts.items()}

        return options

    def _decrypt(self, data):
        return data

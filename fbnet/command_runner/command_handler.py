#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) Facebook, Inc. and its affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import asyncio
import functools
import inspect
import random
import re
import sys
import typing
from dataclasses import dataclass
from functools import wraps
from itertools import islice
from uuid import uuid4

from fb303_asyncio.FacebookBase import FacebookBase
from fbnet.command_runner_asyncio.CommandRunner import constants, ttypes
from fbnet.command_runner_asyncio.CommandRunner.Command import Iface as FcrIface

from .command_session import CapturedTimeMS, CommandSession
from .counters import Counters
from .exceptions import convert_to_fcr_exception, ensure_thrift_exception
from .global_namespace import GlobalNamespace
from .options import Option
from .utils import input_fields_validator


@dataclass(frozen=True)
class DeviceResult:
    """
    Class for passing information received after sending commands to device
    Includes CommandResult(s), captured communication/processing time, and any raised exceptions
    (remains None for exceptions that are returned instead)
    """

    device_response: typing.Union[
        typing.List[typing.Optional[ttypes.CommandResult]],
        typing.Optional[ttypes.CommandResult],
    ] = None
    captured_time_ms: CapturedTimeMS = CapturedTimeMS()
    exception: typing.Optional[Exception] = None


def _append_debug_info_to_exception(fn):
    @wraps(fn)
    async def wrapper(self, *args, **kwargs):
        try:
            return await fn(self, *args, **kwargs)
        except Exception as ex:
            # Retrieve request uuid from the global namespace
            uuid = GlobalNamespace.get_request_uuid()
            # Exception defined in command runner thrift spec has attribute 'message'
            if hasattr(ex, "message"):
                ex.message = await self.add_debug_info_to_error_message(  # noqa
                    error_msg=ex.message, uuid=uuid  # noqa
                )
                raise ex
            else:
                # Don't pass in ex.message to debug info to avoid duplicate message
                debug_info = await self.add_debug_info_to_error_message(
                    error_msg="", uuid=uuid
                )
                # Append message as new arg instead of constructing new exception
                # to account for exceptions having different required args
                ex.args = ex.args + (debug_info,)
                raise ex.with_traceback(sys.exc_info()[2])

    return wrapper


def _ensure_uuid(fn):
    """Make sure the 'uuid' parameter for both input and return is non-empty"""

    @wraps(fn)
    async def wrapper(*args, **kwargs):
        uuid = ""
        callargs = inspect.getcallargs(fn, *args, **kwargs)
        if "uuid" in callargs:
            uuid = callargs["uuid"] or uuid4().hex[:8]
            callargs["uuid"] = uuid
        elif "request" in callargs:
            uuid = callargs["request"].uuid or uuid4().hex[:8]
            callargs["request"] = callargs["request"](uuid=uuid)
        # Note: this won't work for functions that specify positional-only or
        # kwarg-only parameters.
        result = await fn(**callargs)

        # Set UUID on the resulting struct -- if it supports it: Map of, or
        # raw, CommandResult and Session
        if isinstance(result, (ttypes.CommandResult, ttypes.Session)):
            result.uuid = uuid
        elif isinstance(result, dict):
            # bulk_run() returns a dict of map<string, list<CommandResult>>
            for val in result.values():  # val is list<CommandResult>
                # If size of result is large, we can refactor to only check the
                # first element. (time taken: ~100ns * N)
                if isinstance(val, typing.List):
                    for i in range(len(val)):  # val[i] is CommandResult
                        if isinstance(val[i], ttypes.CommandResult):
                            if not val[i].uuid:
                                val[i].uuid = uuid
                        else:
                            break
                elif not isinstance(val, ttypes.CommandResult):
                    break
                else:
                    val.uuid = uuid
        elif isinstance(result, ttypes.BulkRunCommandResponse):
            d2r_values = {}
            d2r_values.update(result.device_to_result)  # d2r_values is dict
            for val in d2r_values.values():  # val is list<CommandResult>
                for i in range(len(val)):  # val[i] is CommandResult
                    if isinstance(val[i], ttypes.CommandResult):
                        if not val[i].uuid:
                            val[i].uuid = uuid
                    else:
                        break
            result.device_to_result = d2r_values
        return result

    return wrapper


class CommandHandler(Counters, FacebookBase, FcrIface):
    """
    Command implementation for api defined in thrift for command runner
    """

    _COUNTER_PREFIX = "fbnet.command_runner"
    _LB_THRESHOLD = 100

    REMOTE_CALL_OVERHEAD = Option(
        "--remote_call_overhead",
        help="Overhead for running commands remotely (for bulk calls)",
        type=int,
        default=20,
    )

    LB_THRESHOLD = Option(
        "--lb_threshold",
        help="""Load Balance threashold for bulk_run calls. If number of
        devices is greater than this threashold, the requests are broken and
        send to other instances using bulk_run_local() api""",
        type=int,
        default=100,
    )

    BULK_SESSION_LIMIT = Option(
        "--bulk_session_limit",
        help="""session limit above which we reject the bulk run local
        calls""",
        type=int,
        default=200,
    )

    BULK_RETRY_LIMIT = Option(
        "--bulk_retry_limit",
        help="""number of times to retry bulk call on the remote instances""",
        type=int,
        default=5,
    )

    BULK_RUN_JITTER = Option(
        "--bulk_run_jitter",
        help="""A random delay added for bulk commands to stagger the calls to
        distribute the load.""",
        type=int,
        default=5,
    )

    BULK_RETRY_DELAY_MIN = Option(
        "--bulk_retry_delay_min",
        help="""number of seconds to wait before retrying""",
        type=int,
        default=5,
    )

    BULK_RETRY_DELAY_MAX = Option(
        "--bulk_retry_delay_max",
        help="""number of seconds to wait before retrying""",
        type=int,
        default=10,
    )

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

    @classmethod
    def _set_bulk_session_count(cls, new_count: int) -> None:
        """Method to set the class variable _bulk_session_count"""
        cls._bulk_session_count = new_count

    async def add_debug_info_to_error_message(self, uuid, error_msg=None):
        if not error_msg:
            return f"(DebugInfo: thrift_uuid={uuid})"
        return f"{error_msg} (DebugInfo: thrift_uuid={uuid})"

    @ensure_thrift_exception
    @input_fields_validator
    @_append_debug_info_to_exception
    @_ensure_uuid
    async def run_v2(self, request: ttypes.RunCommandRequest) -> ttypes.CommandResult:
        result = await self.run(
            request.command,
            request.device,
            request.timeout,
            request.open_timeout,
            request.client_ip,
            request.client_port,
            request.uuid,
        )
        return result

    @ensure_thrift_exception
    @input_fields_validator
    @_append_debug_info_to_exception
    @_ensure_uuid
    async def run(
        self, command, device, timeout, open_timeout, client_ip, client_port, uuid
    ) -> ttypes.CommandResult:
        result = await self._run_commands(
            [command], device, timeout, open_timeout, client_ip, client_port, uuid
        )

        GlobalNamespace.set_api_captured_time_ms(
            GlobalNamespace.get_api_captured_time_ms() + result.captured_time_ms
        )

        # Raise exception if needed here since _run_commands does not raise
        # and exceptions are not returned
        if isinstance(result.exception, Exception):
            raise result.exception

        cmd_result = result.device_response
        if isinstance(cmd_result, list):
            cmd_result = result.device_response[0]  # pyre-ignore checked is list

        return cmd_result

    def _bulk_failure(self, device_to_commands, message):
        def command_failures(cmds):
            return [
                ttypes.CommandResult(
                    output=message, status=constants.FAILURE_STATUS, command=cmd
                )
                for cmd in cmds
            ]

        return {
            self._get_result_key(dev): command_failures(cmds)
            for dev, cmds in device_to_commands.items()
        }

    @ensure_thrift_exception
    @input_fields_validator
    @_append_debug_info_to_exception
    @_ensure_uuid
    async def bulk_run_v2(
        self, request: ttypes.BulkRunCommandRequest
    ) -> ttypes.BulkRunCommandResponse:
        device_to_commands = {}
        for device_commands in request.device_commands_list:
            device_details = device_commands.device
            # Since this is in the handler, is it okay to have struct as a key?
            device_to_commands[device_details] = device_commands.commands

        result = await self.bulk_run(
            device_to_commands,
            request.timeout,
            request.open_timeout,
            request.client_ip,
            request.client_port,
            request.uuid,
        )
        response = ttypes.BulkRunCommandResponse()
        response.device_to_result = result
        return response

    @ensure_thrift_exception
    @input_fields_validator
    @_append_debug_info_to_exception
    @_ensure_uuid
    async def bulk_run(
        self, device_to_commands, timeout, open_timeout, client_ip, client_port, uuid
    ) -> typing.Dict[str, typing.List[ttypes.CommandResult]]:
        if (len(device_to_commands) < self.LB_THRESHOLD) and (
            self._bulk_session_count < self.BULK_SESSION_LIMIT
        ):
            # Run these command locally.
            self.incrementCounter("bulk_run.local")
            return await self._bulk_run_local(
                device_to_commands, timeout, open_timeout, client_ip, client_port, uuid
            )

        async def _remote_task(chunk):
            # Run the chunk of commands on remote instance
            self.incrementCounter("bulk_run.remote")
            retry_count = 0
            while True:
                try:
                    return await self._bulk_run_remote(
                        chunk, timeout, open_timeout, client_ip, client_port, uuid
                    )
                except Exception as e:
                    if isinstance(e, ttypes.InstanceOverloaded):
                        # Instance we ran the call on was overloaded. We can retry
                        # the command again, hopefully on a different instance
                        self.incrementCounter("bulk_run.remote.overload_error")
                        self.logger.error("Instance Overloaded: %d: %s", retry_count, e)

                    if (
                        self._remote_task_should_retry(ex=e)
                        and retry_count <= self.BULK_RETRY_LIMIT
                    ):
                        # Stagger the retries
                        delay = random.uniform(
                            self.BULK_RETRY_DELAY_MIN, self.BULK_RETRY_DELAY_MAX
                        )
                        await asyncio.sleep(delay)
                        retry_count += 1
                    else:
                        # Append message as new arg instead of constructing new exception
                        # to account for exceptions having different required args
                        e.args = e.args + ("bulk_run_remote failed",)
                        return self._bulk_failure(chunk, str(e))

        # Split the request into chunks and run them on remote hosts
        tasks = [
            _remote_task(chunk)
            for chunk in self._chunked_dict(device_to_commands, self.LB_THRESHOLD)
        ]

        all_results = {}
        for task in asyncio.as_completed(tasks):
            result = await task
            all_results.update(result)

        return all_results

    @ensure_thrift_exception
    @_ensure_uuid
    async def bulk_run_local(
        self, device_to_commands, timeout, open_timeout, client_ip, client_port, uuid
    ):
        return await self._bulk_run_local(
            device_to_commands, timeout, open_timeout, client_ip, client_port, uuid
        )

    @_ensure_uuid
    async def _bulk_run_local(
        self, device_to_commands, timeout, open_timeout, client_ip, client_port, uuid
    ) -> typing.Dict[str, typing.List[ttypes.CommandResult]]:
        devices = sorted(device_to_commands.keys(), key=lambda d: d.hostname)

        session_count = self._bulk_session_count
        if session_count + len(device_to_commands) > self.BULK_SESSION_LIMIT:
            self.logger.error("Too many session open: %d", session_count)
            raise ttypes.InstanceOverloaded(
                message="Too many session open: %d" % session_count
            )

        self._set_bulk_session_count(self._bulk_session_count + len(devices))

        async def _run_one_device(device) -> DeviceResult:
            if not device_to_commands[device]:
                return DeviceResult(device_response=[])
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
                uuid,
                return_exceptions=True,
            )

        captured_time_ms_list = []
        try:
            commands = []
            for device in devices:
                commands.append(_run_one_device(device))

            # Run commands in parallel
            results: typing.List[DeviceResult] = await asyncio.gather(
                *commands, return_exceptions=True
            )

            # pyre-ignore: _run_commands always returns list of CommandResults
            # when return_exceptions is True
            cmd_results: typing.List[typing.List[ttypes.CommandResult]] = [
                result.device_response for result in results
            ]

            # Get the captured communication/processing time to save later in finally block
            captured_time_ms_list = [result.captured_time_ms for result in results]
        finally:
            self._set_bulk_session_count(self._bulk_session_count - len(devices))

            GlobalNamespace.set_api_captured_time_ms(
                functools.reduce(
                    CapturedTimeMS.__add__,
                    [GlobalNamespace.get_api_captured_time_ms()]
                    + captured_time_ms_list,
                )
            )

        return {
            self._get_result_key(dev): res for dev, res in zip(devices, cmd_results)
        }

    @ensure_thrift_exception
    @input_fields_validator
    @_append_debug_info_to_exception
    @_ensure_uuid
    async def open_session(
        self, device, open_timeout, idle_timeout, client_ip, client_port, uuid
    ):
        return await self._open_session(
            device,
            open_timeout,
            idle_timeout,
            client_ip,
            client_port,
            uuid,
            raw_session=False,
        )

    @ensure_thrift_exception
    @input_fields_validator
    @_append_debug_info_to_exception
    @_ensure_uuid
    async def run_session(
        self, session, command, timeout, client_ip, client_port, uuid
    ):
        return await self._run_session(
            session, command, timeout, client_ip, client_port, uuid
        )

    @ensure_thrift_exception
    @input_fields_validator
    @_append_debug_info_to_exception
    @_ensure_uuid
    async def close_session(self, session, client_ip, client_port, uuid):
        closed_session = None
        try:
            closed_session = CommandSession.get(session.id, client_ip, client_port)
            # Reset captured time field so we don't include
            # the time from a previous API call
            closed_session.captured_time_ms.reset_time()
            await closed_session.close()
        except Exception as e:
            # Append message as new arg instead of constructing new exception
            # to account for exceptions having different required args
            e.args = e.args + ("close_session failed",)
            raise e
        finally:
            if closed_session:
                GlobalNamespace.set_api_captured_time_ms(
                    GlobalNamespace.get_api_captured_time_ms()
                    + closed_session.captured_time_ms
                )

    @ensure_thrift_exception
    @_append_debug_info_to_exception
    @_ensure_uuid
    async def open_raw_session(
        self, device, open_timeout, idle_timeout, client_ip, client_port, uuid
    ):
        return await self._open_session(
            device,
            open_timeout,
            idle_timeout,
            client_ip,
            client_port,
            uuid,
            raw_session=True,
        )

    @ensure_thrift_exception
    @_append_debug_info_to_exception
    @_ensure_uuid
    async def run_raw_session(
        self, tsession, command, timeout, prompt_regex, client_ip, client_port, uuid
    ):
        if not prompt_regex:
            raise ttypes.SessionException(message="prompt_regex not specified")

        prompt_re = re.compile(prompt_regex.encode("utf8"), re.M)

        return await self._run_session(
            tsession, command, timeout, client_ip, client_port, uuid, prompt_re
        )

    @ensure_thrift_exception
    @_append_debug_info_to_exception
    @_ensure_uuid
    async def close_raw_session(self, tsession, client_ip, client_port, uuid):
        return await self.close_session(tsession, client_ip, client_port, uuid)

    async def _open_session(
        self,
        device,
        open_timeout,
        idle_timeout,
        client_ip,
        client_port,
        uuid,
        raw_session=False,
    ):
        options = self._get_options(
            device,
            client_ip,
            client_port,
            open_timeout,
            idle_timeout,
            raw_session=raw_session,
        )

        session = None
        try:
            devinfo = await self._lookup_device(device)
            session = await devinfo.setup_session(
                self.service, device, options, loop=self.loop
            )

            return ttypes.Session(
                id=session.id, name=session.hostname, hostname=device.hostname
            )
        except Exception as e:
            # Append message as new arg instead of constructing new exception
            # to account for exceptions having different required args
            e.args = e.args + ("open_session failed",)
            raise e
        finally:
            if session:
                GlobalNamespace.set_api_captured_time_ms(
                    GlobalNamespace.get_api_captured_time_ms()
                    + session.captured_time_ms
                )

    async def _run_session(
        self, tsession, command, timeout, client_ip, client_port, uuid, prompt_re=None
    ):
        session = None
        captured_time_ms = CapturedTimeMS()
        try:
            session = CommandSession.get(tsession.id, client_ip, client_port)
            # Reset captured time field so we don't include
            # the time from a previous API call
            session.captured_time_ms.reset_time()
            return await self._run_command(session, command, timeout, uuid, prompt_re)
        except Exception as e:
            # Append message as new arg instead of constructing new exception
            # to account for exceptions having different required args
            e.args = e.args + ("run_session failed",)
            raise e
        finally:
            if session:
                captured_time_ms = session.captured_time_ms

            GlobalNamespace.set_api_captured_time_ms(
                GlobalNamespace.get_api_captured_time_ms() + captured_time_ms
            )

    def _get_result_key(self, device):
        # TODO: just returning the hostname for now. Some additional processing
        # may be required e.g. using shortnames, adding console info, etc
        return device.hostname

    async def _run_command(self, session, command, timeout, uuid, prompt_re=None):
        self.logger.info(f"[request_id={uuid}]: Run command with session {session.id}")
        output = await session.run_command(
            command.encode("utf8"), timeout=timeout, prompt_re=prompt_re
        )
        return session.build_result(
            output=output.decode("utf8", errors="ignore"),
            status=session.exit_status or constants.SUCCESS_STATUS,
            command=command,
        )

    async def _run_commands(
        self,
        commands,
        device,
        timeout,
        open_timeout,
        client_ip,
        client_port,
        uuid,
        return_exceptions=False,
    ) -> DeviceResult:

        options = self._get_options(
            device, client_ip, client_port, open_timeout, timeout
        )

        if device.command_prompts:
            options["command_prompts"] = {
                c.encode(): p.encode() for c, p in device.command_prompts.items()
            }

        command = commands[0]
        devinfo = None
        session = None
        results = []
        captured_time_ms = CapturedTimeMS()
        exc = None
        try:
            devinfo = await self._lookup_device(device)

            async with devinfo.create_session(
                self.service, device, options, loop=self.loop
            ) as session:

                for command in commands:
                    result = await self._run_command(session, command, timeout, uuid)
                    results.append(result)

        except Exception as e:
            await self._record_error(e, command, uuid, options, devinfo, session)
            if return_exceptions:
                if not isinstance(e, ttypes.SessionException):
                    e = convert_to_fcr_exception(e)
                    e = ttypes.SessionException(message=f"{e!s}", code=e._CODE)

                e.message = await self.add_debug_info_to_error_message(  # noqa
                    error_msg=e.message, uuid=uuid  # noqa
                )
                results = [
                    ttypes.CommandResult(output="", status="%r" % e, command=command)
                ]
            else:
                # save exc from the original place so we have full stacktrace
                # when we raise in API level later
                exc = e

        if session:
            captured_time_ms = session.captured_time_ms

        return DeviceResult(
            device_response=results,
            captured_time_ms=captured_time_ms,
            exception=exc,
        )

    def _chunked_dict(self, data, chunk_size):
        """split the dict into smaller dicts"""
        items = iter(data.items())  # get an iterator for items
        for _ in range(0, len(data), chunk_size):
            yield dict(islice(items, chunk_size))

    async def _bulk_run_remote(
        self, device_to_commands, timeout, open_timeout, client_ip, client_port, uuid
    ):

        # Determine a timeout for remote call.
        call_timeout = open_timeout + timeout
        remote_timeout = timeout - self.REMOTE_CALL_OVERHEAD

        # Make sure we have a sane timeout value
        assert remote_timeout > 10, "timeout: '%d' value too low for bulk_run" % timeout

        fcr_client = await self._get_fcr_client(timeout=call_timeout)
        async with fcr_client as client:
            result = await client.bulk_run_local(
                device_to_commands,
                remote_timeout,
                open_timeout,
                client_ip,
                client_port,
                uuid,
            )
            return result

    async def _lookup_device(self, device):
        return await self.service.device_db.get(device)

    async def _get_fcr_client(self, timeout):
        return await self.service.get_fcr_client(timeout=timeout)

    def _get_options(
        self,
        device,
        client_ip,
        client_port,
        open_timeout,
        idle_timeout,
        raw_session=False,
    ):
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
            "clear_command": device.clear_command,
        }

        if device.command_prompts:
            options["command_prompts"] = {
                c.encode(): p.encode() for c, p in device.command_prompts.items()
            }

        return options

    def _get_device_username(self, device):
        return device.username

    def _get_device_password(self, device):
        # If the username is specified then password must also be specified.
        if device.username:
            return self._decrypt(device.password)

    def _decrypt(self, data):
        return data

    async def _record_error(
        self, error, command, uuid, options, devinfo, session, **kwargs
    ):
        """
        Subclass can override this method to export the interested error messages
        to proper data store
        """
        pass

    def _remote_task_should_retry(self, ex: Exception) -> bool:
        """
        The function that decides whether a remote task (fan out request) should or should not
        retry
        """

        if not ex:
            return False

        if isinstance(ex, ttypes.InstanceOverloaded):
            return True

        return False

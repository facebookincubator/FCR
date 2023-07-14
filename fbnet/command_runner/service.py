#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) Facebook, Inc. and its affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import asyncio
import logging
import signal
import typing
from concurrent.futures import ThreadPoolExecutor

from fbnet.command_runner_asyncio.CommandRunner.Command import Client as FcrClient

from .base_service import ServiceObjMeta, ServiceTask
from .command_server import CommandServer
from .command_session import CommandSession
from .exceptions import (
    LookupErrorException,
    NotImplementedErrorException,
    ValueErrorException,
)
from .options import Option
from .thrift_client import AsyncioThriftClient
from .utils import IPUtils


class FcrServiceBase:
    """
    Main Application object.

    This manages application resources and provides a common orchestraion point
    for the application modules.
    """

    ASYNCIO_DEBUG = Option(
        "--asyncio_debug",
        help="turn on debug for asyncio",
        action="store_true",
        default=False,
    )

    LOG_LEVEL = Option(
        "--log_level",
        help="logging level",
        choices=["debug", "info", "warning", "error", "critical"],
        default="info",
    )

    MAX_DEFAULT_EXECUTOR_THREADS = Option(
        "--max_default_executor_threads",
        help="Max number of worker threads",
        type=int,
        default=10,
    )

    EXIT_MAX_WAIT = Option(
        "--exit_max_wait",
        help="Max time (seconds) to wait for session to terminate",
        type=int,
        default=300,
    )

    def __init__(self, app_name, args=None, loop=None):
        self._app_name = app_name
        self._shutting_down = False
        self._stats_mgr = None

        Option.parse_args(args)

        self._loop = loop or asyncio.get_event_loop()
        self._loop.set_debug(self.ASYNCIO_DEBUG)

        executor = ThreadPoolExecutor(max_workers=self.MAX_DEFAULT_EXECUTOR_THREADS)
        self._loop.set_default_executor(executor)

        self._init_logging()

        self._loop.add_signal_handler(signal.SIGINT, self.shutdown)
        self._loop.add_signal_handler(signal.SIGTERM, self.shutdown)

        self._tasks = {}

        self.logger = logging.getLogger(self._app_name)

    def register_stats_mgr(self, stats_mgr):
        self.logger.info("Registering Counter manager")
        self._stats_mgr = stats_mgr
        ServiceObjMeta.register_all_counters(stats_mgr)

    @property
    def stats_mgr(self):
        return self._stats_mgr

    def incrementCounter(self, counter):
        self._stats_mgr.incrementCounter(counter)

    @property
    def config(self):
        return Option.config

    @property
    def app_name(self):
        return self._app_name

    @property
    def loop(self):
        return self._loop

    @property
    def ip_utils(self) -> typing.Type[IPUtils]:
        return IPUtils

    def add_task(self, key, task):
        if key in self._tasks:
            raise LookupErrorException(f"Duplicated key: {key}")
        self._tasks[key] = task

    def start(self):
        try:
            self._loop.run_forever()
        finally:
            pending_tasks = asyncio.all_tasks(loop=self._loop)
            for task in pending_tasks:
                task.cancel()
            self._loop.run_until_complete(
                asyncio.gather(*pending_tasks, return_exceptions=True)
            )
            self._loop.close()

    async def _clean_shutdown(self):
        try:
            coro = CommandSession.wait_sessions("Shutdown", service=self)
            await asyncio.wait_for(coro, timeout=self.EXIT_MAX_WAIT)

        except asyncio.TimeoutError:
            self.logger.error("Timeout waiting for sessions, shutting down anyway")

        finally:
            self.terminate()

    def terminate(self):
        """
        Terminate the application. We cancel all the tasks that are currently active
        """
        self.logger.info("Terminating")

        pending_tasks = asyncio.all_tasks(loop=self.loop)
        for t in pending_tasks:
            t.cancel()

        self.loop.stop()

    def shutdown(self):
        """initiate a clean shutdown"""
        if not self._shutting_down:
            self._shutting_down = True
            for name, task in ServiceTask.all_tasks():
                self.logger.info("Stopping: %s", name)
                task.cancel()
            self.loop.create_task(self._clean_shutdown())
        else:
            # Forcibly shutdown.
            self.terminate()

    def _init_logging(self):

        level = getattr(logging, self.LOG_LEVEL.upper(), None)

        if not isinstance(level, int):
            raise ValueErrorException("Invalid log level: %s" % self.LOG_LEVEL)

        logging.basicConfig(level=level)

    def decrypt(self, data):
        """helper method to decrypt data.

        The default implementation doesn't do anything. Override this method to
        implement security according to your needs
        """
        return data

    async def get_fcr_client(self, timeout=None):
        """
        Get a FCR client for your service.

        This client is used to distribute requests for bulk calls
        """
        return AsyncioThriftClient(
            FcrClient, "localhost", CommandServer.PORT, service=self, timeout=timeout
        )

    def check_ip(self, ipaddr):
        """
        Check if ip address is usable.

        You will likely need to override this function to implement the ip
        validation logic. For eg. a service could periodically check what ip
        addresses are reachable. The application can then use this data to
        filter out non-reachable addresses.

        The default implementation assumes that everything is reachable
        """
        return True

    def get_http_proxy_url(self, host):
        """build a url for http proxy"""
        raise NotImplementedErrorException("Proxy support not implemented")

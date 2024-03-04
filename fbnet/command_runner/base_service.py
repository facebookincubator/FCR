#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# pyre-unsafe

# Copyright (c) Facebook, Inc. and its affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import abc
import asyncio
import logging
from enum import Enum

from fbnet.command_runner.exceptions import NotImplementedErrorException


class State(Enum):

    CREATE = 0
    INIT = 1
    RUN = 2
    CANCELED = 3
    STOP = 4


class ServiceObjMeta(abc.ABCMeta):
    """
    A meta class for handing commmon initializations

    """

    _ALL_OBJTYPES = []

    def __new__(cls, name, bases, attrs):
        objtype = super().__new__(cls, name, bases, attrs)
        ServiceObjMeta._ALL_OBJTYPES.append(objtype)
        return objtype

    @staticmethod
    def register_all_counters(stats_mgr):
        for objtype in ServiceObjMeta._ALL_OBJTYPES:
            objtype.register_counters(stats_mgr)


class ServiceObj(metaclass=ServiceObjMeta):
    """
    Common base-class for all application objects.

    * takes care of common initilization to provide a consistent view across objects

    """

    def __init__(self, service, name=None):
        self._service = service
        self._loop = service.loop if service else asyncio.get_event_loop()
        self._objname = name or self.__class__.__name__
        self._logger = self.create_logger()

    @property
    def loop(self):
        return self._loop

    @property
    def objname(self):
        return self._objname

    @property
    def service(self):
        return self._service

    @property
    def logger(self):
        return self._logger

    def create_logger(self):
        return logging.getLogger("fcr." + self.objname)

    def inc_counter(self, counter):
        if self.service and self.service.stats_mgr:
            self.service.stats_mgr.incrementCounter(counter)

    @classmethod
    def register_counters(cls, stats_mgr):
        pass


class ServiceTask(ServiceObj):
    """
    Base class for defining a Service Task in FCR. This takes care of common
    functionality for a service

    * make sure exception a properly handled
    * Each service only needs to implement to 'run()' method to add the business
      logic
    * Each service can optionally implement the 'cleanup()' method to free up
      the resources
    * Logging as service transitions through various stages.
    """

    # Store reference to tasks that are currently running. This is mainly used
    # in unit-tests and for debugging
    _ALL_TASKS = {}

    def __init__(self, service, name=None, executor=None):
        super().__init__(service, name)
        self._state = State.CREATE

        # A Task may want to run blocking calls in separate thread. To run a
        # method in separate thread, task can use the _run_in_executor() method.
        # User can create their own executor instead using the default one
        # created by the asyncio. This allows user control over the type of
        # executor (task/threads) and its properties (e.g. num_workers)
        self._executor = executor

        # _update_event can be used to notify coroutines about the change in
        # state in this service. e.g. run() has completed
        self.__update_event = None

        self.set_state(State.INIT)

        coro = self.start()
        # fixup task name to show actual task in logs
        coro.__qualname__ = self._objname
        self._task = self.loop.create_task(coro)

        self._ALL_TASKS[self._objname] = self

    @property
    def _update_event(self):
        # Hopefully this is only called in a running loop
        if self.__update_event is None:
            self.__update_event = asyncio.Condition()
        return self.__update_event

    @classmethod
    def all_tasks(cls):
        return cls._ALL_TASKS.items()

    def __await__(self):
        yield from self.wait().__await__()

    async def _run_in_executor(self, method, *args):
        return await self.loop.run_in_executor(self._executor, method, *args)

    async def wait(self):
        await self._update_event.acquire()
        await self._update_event.wait()
        self._update_event.release()

    def cancel(self):
        self._task.cancel()

    def set_state(self, state):
        self.logger.debug("%s: %s -> %s", self._objname, self._state, state)
        self._state = state

    @abc.abstractmethod
    async def run(self):
        """
        Services must provide this implementation
        """
        raise NotImplementedErrorException("run")

    async def cleanup(self):
        """
        Services can override this to free resources
        """
        pass

    async def start(self):

        self.set_state(State.RUN)

        try:
            await self._run()
        except asyncio.CancelledError:
            self.set_state(State.CANCELED)
        except Exception as e:
            self.logger.error("Exception: %s", e, exc_info=True)
            raise e
        finally:
            await self.cleanup()
            if self._executor is not None:
                self._executor.shutdown()
            self.set_state(State.STOP)
            del self._ALL_TASKS[self._objname]

    async def _run(self):
        await self.run()
        await self._notify()

    async def _notify(self):
        """
        Notify coroutines waiting on this service
        """
        await self._update_event.acquire()
        self._update_event.notify_all()
        self._update_event.release()


class PeriodicServiceTask(ServiceTask):
    """
    A periodic version of a ServiceTask

    It will call the run method, at specified intervals
    """

    PERIOD = 5 * 60

    def __init__(self, service, name=None, period=None, executor=None):
        super().__init__(service, name, executor=executor)
        self._period = period or self.PERIOD

    async def _run(self):
        while True:
            await self.run()
            await self._notify()
            await asyncio.sleep(self._period)

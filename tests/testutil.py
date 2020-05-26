#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) Facebook, Inc. and its affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import asyncio
import functools
import unittest


# `asyncio.events.AbstractEventLoop` to have type `float` but is never initialized.
# pyre-fixme[13]: Attribute `slow_callback_duration` inherited from abstract class
class FcrTestEventLoop(asyncio.SelectorEventLoop):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._counter_mgr = None

    def inc_counter(self, name):
        if self._counter_mgr:
            self._counter_mgr.incCounter(name)

    def set_counter_mgr(self, counter_mgr):
        self._counter_mgr = counter_mgr


def async_test(func):
    @functools.wraps(func)
    def _wrapper(self, *args, **kwargs):
        self._loop.run_until_complete(func(self, *args, **kwargs))

    return _wrapper


class AsyncTestCase(unittest.TestCase):
    def setUp(self):
        self._loop = FcrTestEventLoop()
        asyncio.set_event_loop(None)

    def tearDown(self):
        pending = [t for t in asyncio.Task.all_tasks(self._loop) if not t.done()]

        if pending:
            # give opportunity to pending tasks to complete
            res = self._run_loop(asyncio.wait(pending, timeout=1, loop=self._loop))
            done, pending = res[0]

            for p in pending:
                print("Task is still pending", p)

        self._loop.close()

    def wait_for_tasks(self, timeout=10):
        pending = asyncio.Task.all_tasks(self._loop)
        self._loop.run_until_complete(asyncio.gather(*pending, loop=self._loop))

    def _run_loop(self, *args):
        """
        Run a set of coroutines in a loop
        """
        finished, _ = self._loop.run_until_complete(asyncio.wait(args, loop=self._loop))
        return [task.result() for task in finished]

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# pyre-unsafe

# Copyright (c) Facebook, Inc. and its affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import gc
import os
import re
import threading
from collections import defaultdict

import psutil

from .base_service import ServiceObj
from .command_session import CommandSession


class Counters(ServiceObj):
    """
    A bare minimum counters implementation
    """

    _proc = psutil.Process(os.getpid())

    def __init__(self, service, name):
        super().__init__(service, name)

        self.initCounters()

    @classmethod
    def register_counters(cls, stats_mgr):
        stats_mgr.register_counter("sessions", CommandSession.get_session_count)
        stats_mgr.register_counter("gc.garbage", lambda: len(gc.garbage))
        stats_mgr.register_counter("active_threads", threading.activeCount)

        stats_mgr.register_counter(
            "cpu_usage_permille", lambda: round(cls._getCpuUsage() * 10)
        )

    @classmethod
    def _getCpuUsage(cls):
        return cls._proc.cpu_percent(interval=0)

    def initCounters(self):
        self.counters = defaultdict(int)

    def register_counter(self, name, value=0):
        if name not in self.counters:
            self.counters[name] = value

    def add_stats_counter(self, name, stats_types):
        # Currently this only support simple counter, stats parameter are
        # ignored
        self.logger.info("stats counter not supported: %s %r", name, stats_types)
        self.resetCounter(name)

    def incrementCounter(self, name):
        self.counters[name] += 1

    def incrementCounterBy(self, name, amount):
        self.counters[name] += amount

    def getCounter(self, name):
        v = self.counters[name]
        return v() if callable() else v

    def resetCounter(self, name, value=0):
        self.counters[name] = value

    def getCounters(self):
        retval = {}
        for k, v in self.counters.items():
            retval[k] = v() if callable(v) else v
        return retval

    def getRegexCounters(self, regex):
        rex = re.compile(regex)
        return {k: v for k, v in self.getCounters().items() if rex.match(k)}

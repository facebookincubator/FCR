#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) Facebook, Inc. and its affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import time

from fb303_asyncio.fb303 import FacebookService
from fb303_asyncio.fb303.ttypes import fb_status


class FacebookBase(FacebookService.Iface):
    """
    A bare minimum implementation of FB303
    """

    def __init__(self, name):
        self.name = name
        self.alive = int(time.time())

    def getName(self,):
        return self.name

    def getVersion(self,):
        return ""

    def getStatus(self,):
        return fb_status.ALIVE

    def getCounters(self):
        pass

    def getRegexCounter(self, regex):
        pass

    def resetCounter(self, key):
        pass

    def getCounter(self, key):
        pass

    def incrementCounter(self, key):
        pass

    def setOption(self, key, value):
        pass

    def getOption(self, key):
        return ""

    def getOptions(self):
        return {}

    def aliveSince(self):
        return self.alive

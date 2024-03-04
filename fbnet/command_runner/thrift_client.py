#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# pyre-unsafe

# Copyright (c) Facebook, Inc. and its affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import asyncio

from thrift.server.TAsyncioServer import ThriftClientProtocolFactory

from .base_service import ServiceObj


class AsyncioThriftClient(ServiceObj):
    """
    util class to get asyncio client for different services using asyncio
    get_hosts
    """

    _TIMEOUT = 60  # By default timeout after 60s

    def __init__(
        self, client_class, host, port, service=None, timeout=None, open_timeout=None
    ):
        super().__init__(service)

        self._client_class = client_class
        self._host = host
        self._port = port
        self._connected = False
        self._timeout = timeout
        self._open_timeout = open_timeout

        self._protocol = None
        self._transport = None
        self._client = None

        if self.service:
            self._register_counter("connected")
            self._register_counter("lookup.failed")

    def _format_counter(self, counter):
        return "thrift_client.{}.{}.{}".format(self._host, self._port, counter)

    def _inc_counter(self, counter):
        if self.service:
            c = self._format_counter(counter)
            self.inc_counter(c)

    def _register_counter(self, counter):
        c = self._format_counter(counter)
        self.service.stats_mgr.register_counter(c)

    async def _lookup_service(self):
        return self._host, self._port

    async def _get_timeouts(self):
        """Set the timeout for thrift calls"""
        return {"": self._timeout or self._TIMEOUT}

    async def open(self):
        host, port = await self._lookup_service()
        timeouts = await self._get_timeouts()

        conn_fut = self.loop.create_connection(
            ThriftClientProtocolFactory(self._client_class, timeouts=timeouts),
            host=host,
            port=port,
        )
        (transport, protocol) = await asyncio.wait_for(
            conn_fut, self._open_timeout, loop=self.loop
        )
        self._inc_counter("connected")
        self._protocol = protocol
        self._transport = transport

        self._client = protocol.client
        # hookup the close method to the client
        self._client.close = self.close

        self._connected = True
        return self._client

    def close(self):
        if self._protocol:
            self._protocol.close()

        if self._transport:
            self._transport.close()

    def __await__(self):
        return self.open().__await__()

    async def __aenter__(self):
        await self.open()
        return self._client

    async def __aexit__(self, exc_type, exc, tb):
        self.close()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio

from thrift.server.TAsyncioServer import ThriftClientProtocolFactory
from .base_service import ServiceObj


class AsyncioThriftClient(ServiceObj):
    '''
    util class to get asyncio client for different services using asyncio
    get_hosts
    '''

    _TIMEOUT = 60  # By default timeout after 60s

    def __init__(self, client_class, host, port,
                 app=None, timeout=None, open_timeout=None):
        super().__init__(app)

        self._client_class = client_class
        self._host = host
        self._port = port
        self._connected = False
        self._open_timeout = open_timeout

        self._protocol = None
        self._transport = None
        self._client = None

        # Set the timeout for thrift calls
        self._timeouts = {'': timeout or self._TIMEOUT}

        if self.app:
            self._register_counter('connected')
            self._register_counter('lookup.failed')

    def _format_counter(self, counter):
        return 'thrift_client.{}.{}.{}'.format(self._host, self._port, counter)

    def _inc_counter(self, counter):
        if self._app:
            c = self._format_counter(counter)
            self.inc_counter(c)

    def _register_counter(self, counter):
        c = self._format_counter(counter)
        self.app.stats_mgr.register_counter(c)

    async def _lookup_service(self):
        return self._host, self._port

    async def open(self):
        host, port = await self._lookup_service()

        conn_fut = self.loop.create_connection(
            ThriftClientProtocolFactory(self._client_class, timeouts=self._timeouts),
            host=host, port=port)
        (transport, protocol) = await asyncio.wait_for(conn_fut,
                                                       self._open_timeout,
                                                       loop=self.loop)
        self._inc_counter('connected')
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

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# pyre-unsafe

# Copyright (c) Facebook, Inc. and its affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

from fbnet.command_runner_asyncio.CommandRunner.Command import Processor
from thrift.server.TAsyncioServer import ThriftServerProtocolFactory
from thrift.server.TServer import TServerEventHandler
from thrift.Thrift import TProcessorEventHandler

from .base_service import ServiceTask
from .command_handler import CommandHandler
from .options import Option


class CommandServer(ServiceTask):
    """
    Command server for thrift commands.
    """

    PORT = Option(
        "-p", "--port", help="TCP port for FCR service", type=int, default=5000
    )

    def __init__(self, service, loop=None):
        super().__init__(service, "CommandServer")
        self._handler = None
        self._server = None
        self._backlog = 100

    def _get_processor_class(self):
        return Processor

    async def run(self):

        # Wait for FBNet to finish its run
        await self.service.device_db.wait_for_data()

        event_handler = self._create_thrift_event_handler()
        thrift_handler = self._create_thrift_handler(event_handler)

        self._handler = thrift_handler

        processor = self._get_processor_class()(self._handler, loop=self.loop)
        processor.setEventHandler(event_handler)

        pfactory = ThriftServerProtocolFactory(
            processor, self._create_server_event_handler(), loop=self.loop
        )

        self._server = await self.loop.create_server(
            pfactory, port=self.PORT, backlog=self._backlog
        )

        self.logger.info("server started: %d ", self.PORT)

        # Wait for the server to be closed. Typically this will never close.
        await self._server.wait_closed()

        self.logger.info("server done: %d", self.PORT)

        self._server = None

    def _create_thrift_handler(self, event_handler):
        return CommandHandler(self.service)

    def _create_server_event_handler(self):
        return TServerEventHandler()

    def _create_thrift_event_handler(self):
        return TProcessorEventHandler()

    async def cleanup(self):
        # Let the handler cleanup any relevent state
        self._handler.cleanup()
        self.close()

    def close(self):
        # close the server port
        if self._server:
            self.logger.info("closing the server")
            self._server.close()

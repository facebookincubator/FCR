#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) Facebook, Inc. and its affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import asyncio

import unittest.mock as mock

from fbnet.command_runner.base_service import PeriodicServiceTask, ServiceTask

from .testutil import AsyncTestCase


class TestService(AsyncTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._mock_service = mock.Mock(loop=self._loop)

    def test_abstract_service(self) -> None:
        with self.assertRaises(TypeError):
            ServiceTask("RunTest", service=self._mock_service)  # pyre-ignore

    def test_run(self) -> None:
        class DummyServiceTask(ServiceTask):
            _run_called = False
            _cleanup_called = False

            async def cleanup(self):
                self._cleanup_called = True

            async def run(self):
                self._run_called = True

        service = DummyServiceTask(self._mock_service, "RunTest")

        self.wait_for_tasks()
        self.assertTrue(service._run_called)
        self.assertTrue(service._cleanup_called)

    def test_cancel(self) -> None:
        class DummyServiceTask(ServiceTask):
            _run_called = False
            _run_complete = False
            _cleanup_called = False

            async def cleanup(self):
                self._cleanup_called = True

            async def run(self):
                self._run_called = True
                await asyncio.sleep(60, loop=self.service.loop)
                self._run_complete = True

        services = [
            DummyServiceTask(self._mock_service, "DummyServiceTask-%d" % (i))
            for i in range(3)
        ]

        async def cancel_services():
            asyncio.sleep(1)
            for svc in services:
                svc.cancel()

        asyncio.ensure_future(cancel_services(), loop=self._loop)

        self.wait_for_tasks()

        for svc in services:
            self.assertTrue(svc._run_called)
            self.assertFalse(svc._run_complete)
            self.assertTrue(svc._cleanup_called)

    def test_exception(self) -> None:
        class DummyServiceTask(ServiceTask):
            _run_called = False
            _run_complete = False
            _cleanup_called = False

            async def cleanup(self):
                self._cleanup_called = True

            async def run(self):
                self._run_called = True
                raise RuntimeError(self._objname)
                self._run_complete = True

        service = DummyServiceTask(self._mock_service, "DummyServiceTask")

        with self.assertRaises(RuntimeError) as ctx:
            self.wait_for_tasks()

        self.assertEqual(ctx.exception.args[0], service._objname)
        self.assertTrue(service._run_called)
        self.assertFalse(service._run_complete)
        self.assertTrue(service._cleanup_called)


class TestPeriodicService(AsyncTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._mock_service = mock.Mock(loop=self._loop)

    def test_abstract_service(self) -> None:
        with self.assertRaises(TypeError):
            PeriodicServiceTask(self._mock_service, "RunTest", 1)

    def test_run(self) -> None:
        class DummyServiceTask(PeriodicServiceTask):
            _run_called = 0
            _cleanup_called = False

            async def cleanup(self):
                self._cleanup_called = True

            async def run(self):
                assert self._run_called < 5
                self._run_called += 1
                if self._run_called == 5:
                    self.cancel()

        service = DummyServiceTask(self._mock_service, "RunTest", 0.1)

        self.wait_for_tasks()

        self.assertEqual(service._run_called, 5)
        self.assertTrue(service._cleanup_called)

    def test_exception(self) -> None:
        class DummyServiceTask(PeriodicServiceTask):
            _run_called = 0
            _cleanup_called = False

            async def cleanup(self):
                self._cleanup_called = True

            async def run(self):
                assert self._run_called < 3
                self._run_called += 1
                if self._run_called == 3:
                    raise RuntimeError(self._run_called)

        service = DummyServiceTask(self._mock_service, "RunTest", 0.1)

        with self.assertRaises(RuntimeError) as ctx:
            self.wait_for_tasks()

        self.assertEqual(ctx.exception.args[0], 3)
        self.assertEqual(service._run_called, 3)
        self.assertTrue(service._cleanup_called)

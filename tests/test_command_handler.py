#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) Facebook, Inc. and its affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

from fbnet.command_runner.command_handler import CommandHandler
from fbnet.command_runner.options import Option
from fbnet.command_runner_asyncio.CommandRunner import ttypes
from mock import Mock

from .mocks import MockService
from .testutil import AsyncTestCase, async_test


client_ip = "127.0.0.1"
client_port = 5000
uuid = ""


class TestCommandHandler(AsyncTestCase):
    def setUp(self):
        super().setUp()
        self.mock_options = {}
        self._mocks = MockService(self.mock_options, loop=self._loop)
        self.stats_mgr = Mock()
        self.cmd_handler = CommandHandler(self._mocks)

    def tearDown(self):
        self._mocks.tearDown()
        super().tearDown()

    def mock_device(self, name, console="", command_prompts=None):
        return Mock(hostname=name, console=console, command_prompts=command_prompts)

    @async_test
    async def test_run_success(self):
        device = self.mock_device("test-dev-1")
        result = await self.cmd_handler.run(
            "show version\n", device, 5, 5, client_ip, client_port, uuid
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(
            result.output, "$ show version\nMock response for show version"
        )

    @async_test
    async def test_run_no_device(self):
        device = self.mock_device("test-dev-100")

        with self.assertRaises(ttypes.SessionException) as exc:
            await self.cmd_handler.run(
                "show version\n", device, 5, 5, client_ip, client_port, uuid
            )

        self.assertIn(
            "KeyError('Device not found', 'test-dev-100')", exc.exception.message
        )

    @async_test
    async def test_run_connect_timeout(self):
        device = self.mock_device("test-dev-2")

        self.mock_options["connect_drop"] = True

        with self.assertRaises(ttypes.SessionException) as exc:
            await self.cmd_handler.run(
                "show version\n", device, 0, 0, client_ip, client_port, uuid
            )

        self.assertIn(
            "Failed (session: MockCommandSession, peer: (test-ip, 22)): "
            "TimeoutError()",
            exc.exception.message,
        )

    @async_test
    async def test_run_command_timeout(self):
        device = self.mock_device("test-dev-2")

        with self.assertRaises(ttypes.SessionException) as exc:
            await self.cmd_handler.run(
                "command timeout\n", device, 0, 0, client_ip, client_port, uuid
            )

        self.assertIn(
            "Failed (session: MockCommandSession, peer: (test-ip, 22)): "
            "TimeoutError()",
            exc.exception.message,
        )

    @async_test
    async def test_run_success_user_prompt(self):
        command_prompts = {"user prompt test": "<<<User Magic Prompt>>>"}
        device = self.mock_device("test-dev-1", command_prompts=command_prompts)
        result = await self.cmd_handler.run(
            "show version\n", device, 5, 5, client_ip, client_port, uuid
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(
            result.output, "$ show version\nMock response for show version"
        )

        result = await self.cmd_handler.run(
            "user prompt test\n", device, 5, 5, client_ip, client_port, uuid
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(
            result.output,
            "<<<User Magic Prompt>>> user prompt test\n" "Test for user prompts",
        )

    @async_test
    async def test_run_success_user_prompt_failed(self):
        command_prompts = {"user prompt test": "<<<XX User Magic Prompt>>>"}
        device = self.mock_device("test-dev-1", command_prompts=command_prompts)
        result = await self.cmd_handler.run(
            "show version\n", device, 5, 5, client_ip, client_port, uuid
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(
            result.output, "$ show version\nMock response for show version"
        )

        with self.assertRaises(ttypes.SessionException) as exc:
            result = await self.cmd_handler.run(
                "user prompt test\n", device, 1, 1, client_ip, client_port, uuid
            )

        self.assertIn(
            "Failed (session: MockCommandSession, peer: (test-ip, 22)): "
            "RuntimeError('Command Response Timeout', "
            "b'user prompt test\\nTest for user prompts\\n<<<User Magic Prompt>>>')",
            exc.exception.message,
        )

    @async_test
    async def test_open_session(self):
        device = self.mock_device("test-dev-1")

        session = await self.cmd_handler.open_session(
            device, 5, 5, client_ip, client_port, uuid
        )

        self.assertIsNotNone(session)
        self.assertEqual(session.name, device.hostname)
        self.assertEqual(session.hostname, device.hostname)

    @async_test
    async def test_open_session_no_device(self):
        device = self.mock_device("test-dev-10")

        with self.assertRaises(ttypes.SessionException) as exc:
            await self.cmd_handler.open_session(
                device, 0.01, 0.01, client_ip, client_port, uuid
            )

        self.assertIn(
            "open_session failed: KeyError('Device not found', 'test-dev-10')",
            exc.exception.message,
        )

    @async_test
    async def test_open_session_timeout(self):
        device = self.mock_device("test-dev-2")

        self.mock_options["connect_drop"] = True

        with self.assertRaises(ttypes.SessionException) as exc:
            await self.cmd_handler.open_session(
                device, 0.01, 0.01, client_ip, client_port, uuid
            )

        self.assertIn("open_session failed: TimeoutError()", exc.exception.message)

    @async_test
    async def test_run_session(self):
        device = self.mock_device("test-dev-1")

        session = await self.cmd_handler.open_session(
            device, 5, 5, client_ip, client_port, uuid
        )

        result = await self.cmd_handler.run_session(
            session, "show version\n", 5, client_ip, client_port, uuid
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(
            result.output, "$ show version\nMock response for show version"
        )

    @async_test
    async def test_run_session_invalid(self):
        session = Mock(id=1234)

        with self.assertRaises(ttypes.SessionException) as exc:
            await self.cmd_handler.run_session(
                session, "show version\n", 5, client_ip, client_port, uuid
            )

        self.assertIn(
            "run_session failed: KeyError('Session not found', "
            + "(1234, '127.0.0.1', 5000))",
            exc.exception.message,
        )

    @async_test
    async def test_run_session_command_timeout(self):
        device = self.mock_device("test-dev-1")

        session = await self.cmd_handler.open_session(
            device, 5, 5, client_ip, client_port, uuid
        )

        with self.assertRaises(ttypes.SessionException) as exc:
            await self.cmd_handler.run_session(
                session, "command timeout\n", 1, client_ip, client_port, uuid
            )

        self.assertIn(
            "run_session failed: RuntimeError('%s', b'%s')"
            % (
                "Command Response Timeout",
                "command timeout\\nMock response for command timeout",
            ),
            exc.exception.message,
        )

    @async_test
    async def test_close_session(self):
        device = self.mock_device("test-dev-1")

        session = await self.cmd_handler.open_session(
            device, 5, 5, client_ip, client_port, uuid
        )

        await self.cmd_handler.close_session(session, client_ip, client_port, uuid)

    @async_test
    async def test_close_session_invalid(self):
        session = Mock(id=1234)

        with self.assertRaises(ttypes.SessionException) as exc:
            await self.cmd_handler.close_session(session, client_ip, client_port, uuid)

        self.assertIn(
            "close_session failed: KeyError('Session not found', "
            + "(1234, '127.0.0.1', 5000))",
            exc.exception.message,
        )

    @async_test
    async def test_bulk_run_local(self):
        devices = ["test-dev-%d" % i for i in range(1, 5)]
        commands = {self.mock_device(name): ["show version\n"] for name in devices}

        all_results = await self.cmd_handler.bulk_run_local(
            commands, 1, 1, client_ip, client_port, uuid
        )

        for host in devices:
            for result in all_results[host]:
                self.assert_command_result(result)

    @async_test
    async def test_bulk_run_local_with_invalid_devices(self):
        devices = ["test-dev-%d" % i for i in range(0, 5)]
        commands = {self.mock_device(name): ["show version\n"] for name in devices}

        all_results = await self.cmd_handler.bulk_run_local(
            commands, 1, 1, client_ip, client_port, uuid
        )

        for host in devices:
            if host == "test-dev-0":
                result = all_results[host][0]
                self.assertIn(
                    "KeyError('%s', '%s')" % ("Device not found", "test-dev-0"),
                    result.status,
                )
                continue
            for result in all_results[host]:
                self.assert_command_result(result)
        Option.config.lb_threshold = 20

    @async_test
    async def test_bulk_run_local_with_command_timeout(self):
        devices = ["test-dev-%d" % i for i in range(0, 5)]
        commands = {self.mock_device(name): ["show version\n"] for name in devices}

        # pick a scapegoat
        onehost = next(iter(commands))
        commands[onehost] = ["command timeout\n"]

        all_results = await self.cmd_handler.bulk_run_local(
            commands, 1, 1, client_ip, client_port, uuid
        )

        for host in devices:
            if host == "test-dev-0":
                result = all_results[host][0]
                self.assertIn(
                    "KeyError('%s', '%s')" % ("Device not found", "test-dev-0"),
                    result.status,
                )
                continue
            for result in all_results[host]:
                self.assert_command_result(result)

    @async_test
    async def test_bulk_run_local_with_connect_timeout(self):
        devices = ["test-dev-%d" % i for i in range(0, 2)]
        commands = {self.mock_device(name): ["show version\n"] for name in devices}

        # pick a scapegoat
        onehost = next(iter(commands))
        commands[onehost] = ["command timeout\n"]

        self.mock_options["connect_drop"] = True

        all_results = await self.cmd_handler.bulk_run_local(
            commands, 1, 1, client_ip, client_port, uuid
        )

        for host in devices:
            if host == "test-dev-0":
                result = all_results[host][0]
                self.assertIn(
                    "KeyError('%s', '%s')" % ("Device not found", "test-dev-0"),
                    result.status,
                )
                continue
            for result in all_results[host]:
                self.assertIn(
                    "Failed (session: MockCommandSession, peer: (test-ip, 22)): "
                    "TimeoutError()",
                    result.status,
                )

    @async_test
    async def test_bulk_run_local_overload(self):
        devices = ["test-dev-%d" % i for i in range(1, 5)]
        commands = {self.mock_device(name): ["show version\n"] for name in devices}

        Option.config.bulk_session_limit = 4
        CommandHandler._bulk_session_count = 4

        with self.assertRaises(ttypes.InstanceOverloaded) as exc:
            await self.cmd_handler.bulk_run_local(
                commands, 1, 1, client_ip, client_port, uuid
            )

        self.assertIn("Too many session open: 4", exc.exception.message)

    @async_test
    async def test_bulk_run_load_balance(self):
        Option.config.lb_threshold = 2
        device_names = {"test-dev-%d" % i for i in range(0, 10)}

        commands = {self.mock_device(name): ["show version\n"] for name in device_names}

        command_chunks = []

        async def _bulk_run_remote(chunk, *args):
            command_chunks.append(chunk)
            return {dev: "%s: Success" % dev.hostname for dev in chunk.keys()}

        self.cmd_handler._bulk_run_remote = _bulk_run_remote

        all_results = await self.cmd_handler.bulk_run(
            commands, 10, 10, client_ip, client_port, uuid
        )

        self.assertEqual(len(command_chunks), 5, "Commands are run in chunks")

        devices = set(commands.keys())
        res_devices = set(all_results.keys())
        self.assertEqual(res_devices, devices, "Responses are received for all devices")

        # Make sure the responses are right from devices
        for dev, resp in all_results.items():
            self.assertEqual(
                resp, "%s: Success" % dev.hostname, "Correct response is received"
            )

    @async_test
    async def test_bulk_run_below_threshold(self):
        Option.config.lb_threshold = 20
        device_names = {"test-dev-%d" % i for i in range(0, 10)}

        commands = {self.mock_device(name): ["show version\n"] for name in device_names}

        command_chunks = []
        local_commands = []

        async def _bulk_run_remote(chunk, *args):
            command_chunks.append(chunk)
            return {dev: "%s: Success" % dev.hostname for dev in chunk.keys()}

        async def _bulk_run_local(chunk, *args):
            local_commands.append(chunk)
            return {dev: "%s: Success" % dev.hostname for dev in chunk.keys()}

        self.cmd_handler._bulk_run_remote = _bulk_run_remote
        self.cmd_handler.bulk_run_local = _bulk_run_local

        all_results = await self.cmd_handler.bulk_run(
            commands, 10, 10, client_ip, client_port, uuid
        )

        self.assertEqual(len(command_chunks), 0, "Commands are not run in chunks")
        self.assertEqual(len(local_commands), 1, "Commands are run locally")
        self.assertEqual(len(local_commands[0]), 10, "Commands are run locally")

        devices = set(commands.keys())
        res_devices = set(all_results.keys())
        self.assertEqual(res_devices, devices, "Responses are received for all devices")

        # Make sure the responses are right from devices
        for dev, resp in all_results.items():
            self.assertEqual(
                resp, "%s: Success" % dev.hostname, "Correct response is received"
            )

    def assert_command_result(self, result):
        if result.command == "show version\n":
            self.assertEqual(result.status, "success")
            self.assertEqual(
                result.output, "$ show version\nMock response for show version"
            )
        elif result.command == "command timeout\n":
            status_fmt = (
                "Failed (session: MockCommandSession, peer: "
                "(test-ip 22)): RuntimeError('{0}', b'{2}\\nMock response for {2}')"
            )
            self.assertEqual(
                result.status,
                status_fmt.format("Command Response Timeout", "command timeout"),
            )
        else:
            self.fail("unexpected result: %r" % result)

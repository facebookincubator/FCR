#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# pyre-unsafe

# Copyright (c) Facebook, Inc. and its affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import unittest
from typing import Dict, List, Optional

from fbnet.command_runner.exceptions import ValidationErrorException
from fbnet.command_runner.utils import (
    _check_device,
    _check_session,
    canonicalize,
    construct_netconf_capability_set,
    input_fields_validator,
)
from fbnet.command_runner_asyncio.CommandRunner import ttypes

from .testutil import async_test, AsyncTestCase


class CanonicalizeTest(unittest.TestCase):
    def test_canonicalize(self) -> None:
        self.assertEqual(canonicalize("abc"), b"abc")
        self.assertEqual(canonicalize(b"abc"), b"abc")
        self.assertEqual(canonicalize(["abc", "xyz", b"123"]), [b"abc", b"xyz", b"123"])


class InputFieldsValidatorTest(AsyncTestCase):
    def test_check_device(self) -> None:
        with self.assertRaises(ValidationErrorException) as ex:
            _check_device(device=None)

        self.assertEqual(
            str(ex.exception), "Required argument (device) cannot be None."
        )

        with self.assertRaises(ValidationErrorException) as ex:
            # pyre-fixme[6]: For 1st argument expected `Optional[types.Device]` but
            #  got `Device`.
            _check_device(device=ttypes.Device())

        missing_list = ["hostname", "username", "password"]
        for missing_field in missing_list:
            self.assertIn(missing_field, str(ex.exception))

    def test_check_session(self) -> None:
        with self.assertRaises(ValidationErrorException) as ex:
            _check_session(session=None)

        self.assertEqual(
            str(ex.exception), "Required argument (session) cannot be None."
        )

        with self.assertRaises(ValidationErrorException) as ex:
            # pyre-fixme[6]: For 1st argument expected `Optional[types.Session]` but
            #  got `Session`.
            _check_session(session=ttypes.Session())

        missing_list = ["hostname", "id", "name"]
        for missing_field in missing_list:
            self.assertIn(missing_field, str(ex.exception))

    def test_construct_capability_set(self) -> None:
        empty_hello_msg = ""
        res = construct_netconf_capability_set(empty_hello_msg)
        self.assertTrue(len(res) == 0)

        # Test hello msg in bytes with namespace
        hello_msg_with_namespace: bytes = b"""<?xml version="1.0" encoding="UTF-8" ?>
<hello xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">
  <capabilities>
    <capability>urn:ietf:params:netconf:base:1.0</capability>
    <capability>urn:ietf:params:netconf:capability:rollback-on-error:1.0</capability>
    <capability>urn:ietf:params:netconf:capability:validate:1.1</capability>
    <capability>urn:ietf:params:netconf:capability:confirmed-commit:1.1</capability>
  </capabilities>
</hello>
"""
        res = construct_netconf_capability_set(hello_msg_with_namespace)
        self.assertEqual(res, {"urn:ietf:params:netconf:base:1.0"})

        # Test hello msg in string with namespace
        # pyre-fixme[35]: Target cannot be annotated.
        hello_msg_with_namespace: str = """<?xml version="1.0" encoding="UTF-8" ?>
<hello xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">
  <capabilities>
    <capability>urn:ietf:params:netconf:base:1.0</capability>
    <capability>urn:ietf:params:netconf:capability:rollback-on-error:1.0</capability>
    <capability>urn:ietf:params:netconf:capability:validate:1.1</capability>
    <capability>urn:ietf:params:netconf:capability:confirmed-commit:1.1</capability>
  </capabilities>
</hello>
"""
        res = construct_netconf_capability_set(hello_msg_with_namespace)
        self.assertEqual(res, {"urn:ietf:params:netconf:base:1.0"})

        # Test hello msg in bytes without namespace
        hello_msg_without_namespace: bytes = b"""<?xml version="1.0" encoding="UTF-8" ?>
<hello>
  <capabilities>
    <capability>urn:ietf:params:netconf:base:1.0</capability>
    <capability>urn:ietf:params:netconf:capability:rollback-on-error:1.0</capability>
    <capability>urn:ietf:params:netconf:capability:validate:1.1</capability>
    <capability>urn:ietf:params:netconf:capability:confirmed-commit:1.1</capability>
  </capabilities>
</hello>
"""
        res = construct_netconf_capability_set(hello_msg_without_namespace)
        self.assertEqual(res, {"urn:ietf:params:netconf:base:1.0"})

    @async_test
    async def test_input_fields_validator(self) -> None:
        @input_fields_validator
        async def test_command(self, command: Optional[str]) -> None:
            return

        @input_fields_validator
        async def test_device(self, device: ttypes.Device) -> None:
            return

        @input_fields_validator
        async def test_session(self, session: ttypes.Session) -> None:
            return

        @input_fields_validator
        async def test_device_to_commands(
            self, device_to_commands: Dict[ttypes.Device, List[str]]
        ) -> None:
            return

        @input_fields_validator
        async def test_device_to_configlets(
            self, device_to_configlets: Dict[ttypes.Device, List[str]]
        ) -> None:
            return

        with self.assertRaises(ValidationErrorException):
            await test_command(self, command=None)

        with self.assertRaises(ValidationErrorException):
            await test_device(self, device=ttypes.Device(hostname="test-device"))

        with self.assertRaises(ValidationErrorException):
            await test_session(self, session=ttypes.Session(hostname="test-device"))

        with self.assertRaises(ValidationErrorException):
            await test_device_to_commands(
                self,
                device_to_commands={ttypes.Device(hostname="test-device"): ["command"]},
            )

        with self.assertRaises(ValidationErrorException):
            await test_device_to_configlets(
                self,
                device_to_configlets={
                    ttypes.Device(hostname="test-device"): ["configs"]
                },
            )

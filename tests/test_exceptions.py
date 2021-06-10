#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) Facebook, Inc. and its affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

from typing import List, Type

from fbnet.command_runner.exceptions import (
    FcrBaseException,
    UnknownException,
    ValidationErrorException,
    PermissionErrorException,
    ValueErrorException,
    RuntimeErrorException,
    DeviceErrorException,
    ConnectionErrorException,
)
from fbnet.command_runner_asyncio.CommandRunner import ttypes as fcr_ttypes

from .testutil import AsyncTestCase, async_test


class ExceptionTest(AsyncTestCase):
    FCR_EXCEPTIONS: List[Type[FcrBaseException]] = [
        UnknownException,
        ValidationErrorException,
        PermissionErrorException,
        ValueErrorException,
        RuntimeErrorException,
        DeviceErrorException,
        ConnectionErrorException,
    ]

    @async_test
    async def test_to_thrift_exception(self) -> None:
        """
        Test for the to_thrift_exception converter function
        The function should convert FcrBaseException types to Thrift defined SessionException
        """
        exc_msg = "This is an exception!"

        for exception_type in self.FCR_EXCEPTIONS:
            exc = exception_type(exc_msg)
            converted_exc = await FcrBaseException.to_thrift_exception(exc)

            # Make sure that the exception is Thrift-defined now
            self.assertIsInstance(converted_exc, fcr_ttypes.SessionException)
            self.assertEqual(exc._CODE, converted_exc.code)
            self.assertEqual(str(exc), converted_exc.message)

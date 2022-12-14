#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) Facebook, Inc. and its affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

from typing import Dict, List, Type

import asyncssh
from fbnet.command_runner.exceptions import (
    AssertionErrorException,
    AttributeErrorException,
    CommandExecutionErrorException,
    CommandExecutionTimeoutErrorException,
    ConnectionErrorException,
    ConnectionTimeoutErrorException,
    convert_to_fcr_exception,
    DeviceErrorException,
    ensure_thrift_exception,
    FcrBaseException,
    LookupErrorException,
    NotImplementedErrorException,
    PermissionErrorException,
    RuntimeErrorException,
    StreamReaderErrorException,
    TimeoutErrorException,
    TypeErrorException,
    UnknownException,
    UnsupportedCommandErrorException,
    UnsupportedDeviceErrorException,
    ValidationErrorException,
    ValueErrorException,
)
from fbnet.command_runner_asyncio.CommandRunner import ttypes as fcr_ttypes
from fbnet.command_runner_asyncio.CommandRunner.ttypes import FcrErrorCode

from .testutil import async_test, AsyncTestCase


class ExceptionTest(AsyncTestCase):
    # Defined FcrBaseException exceptions
    FCR_EXCEPTIONS: List[Type[FcrBaseException]] = [
        UnknownException,
        ValidationErrorException,
        PermissionErrorException,
        ValueErrorException,
        UnsupportedDeviceErrorException,
        UnsupportedCommandErrorException,
        RuntimeErrorException,
        AssertionErrorException,
        LookupErrorException,
        StreamReaderErrorException,
        CommandExecutionTimeoutErrorException,
        NotImplementedErrorException,
        TypeErrorException,
        AttributeErrorException,
        TimeoutErrorException,
        DeviceErrorException,
        CommandExecutionErrorException,
        ConnectionErrorException,
        ConnectionTimeoutErrorException,
    ]

    # Other non-FcrBaseException exceptions that FCR knows about
    # Preconstruct exception with args since different exceptions have different args
    # pyre-fixme[8]: Attribute has type `Dict[Type[Exception], FcrErrorCode]`; used
    #  as `Dict[Union[AssertionError, AttributeError, LookupError, PermissionError,
    #  RuntimeError, TimeoutError, TypeError, ValueError, DisconnectError],
    #  FcrErrorCode]`.
    KNOWN_EXCEPTIONS: Dict[Type[Exception], FcrErrorCode] = {
        PermissionError("This is a known exception!"): FcrErrorCode.PERMISSION_ERROR,
        ValueError("This is a known exception!"): FcrErrorCode.VALUE_ERROR,
        RuntimeError("This is a known exception!"): FcrErrorCode.RUNTIME_ERROR,
        AssertionError("This is a known exception!"): FcrErrorCode.ASSERTION_ERROR,
        LookupError("This is a known exception!"): FcrErrorCode.LOOKUP_ERROR,
        KeyError("This is a known exception!"): FcrErrorCode.LOOKUP_ERROR,
        NotImplementedError(
            "This is a known exception!"
        ): FcrErrorCode.NOT_IMPLEMENTED_ERROR,
        asyncssh.misc.DisconnectError(
            code=0, reason="This is a known exception!"
        ): FcrErrorCode.CONNECTION_ERROR,
        TypeError("This is a known exception!"): FcrErrorCode.TYPE_ERROR,
        AttributeError("This is a known exception!"): FcrErrorCode.ATTRIBUTE_ERROR,
        TimeoutError("This is a known exception!"): FcrErrorCode.TIMEOUT_ERROR,
    }

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

    def test_convert_to_fcr_exception(self) -> None:
        """
        Test for the convert_to_fcr_exception function
        The function should convert generic exception types to FcrBaseException types
        and leave FcrBaseException types unchanged
        """
        exc_msg = "This is an exception!"

        # Test that FcrBaseException types are unchanged
        for exception_type in self.FCR_EXCEPTIONS:
            exc = exception_type(exc_msg)
            converted_exc = convert_to_fcr_exception(exc)

            self.assertIsInstance(converted_exc, FcrBaseException)
            self.assertEqual(exc._CODE, converted_exc._CODE)
            self.assertEqual(str(exc), str(converted_exc))

        # Test that known exception types are converted correctly
        for exc in self.KNOWN_EXCEPTIONS:
            # pyre-fixme[6]: For 1st argument expected `Exception` but got
            #  `Type[Exception]`.
            converted_exc = convert_to_fcr_exception(exc)
            self.assertIsInstance(converted_exc, FcrBaseException)
            self.assertEqual(self.KNOWN_EXCEPTIONS[exc], converted_exc._CODE)
            self.assertEqual(str(exc), str(converted_exc))

        # Test that unknown Exceptions are converted correctly
        unknown_exc = Exception("This is an unknown exception!")
        converted_exc = convert_to_fcr_exception(unknown_exc)

        self.assertIsInstance(converted_exc, FcrBaseException)
        self.assertEqual(FcrErrorCode.UNKNOWN, converted_exc._CODE)
        self.assertEqual(repr(unknown_exc), str(converted_exc))

    @async_test
    async def test_ensure_thrift_exception(self) -> None:
        """
        Test for the ensure_thrift_exception decorator
        The decorator should catch all exceptions and convert to Thrift exceptions
        """

        @ensure_thrift_exception
        async def test_raise_no_exception(self, return_msg: str) -> str:
            return return_msg

        @ensure_thrift_exception
        async def test_raise_exception(self, exc: Exception, return_msg: str) -> str:
            raise exc

        return_msg = "A returned string"

        # Test normal case: no exception raised
        try:
            res = await test_raise_no_exception(self, return_msg=return_msg)
            self.assertEqual(res, return_msg)
        except Exception:
            self.fail("test_raise_no_exception raised an exception")

        # Test that FcrBaseException types are converted
        for exception_type in self.FCR_EXCEPTIONS:
            exc = exception_type("This is an FCR exception!")

            # Make sure that the exception is Thrift-defined now
            with self.assertRaises(fcr_ttypes.SessionException) as context:
                res = await test_raise_exception(self, exc=exc, return_msg=return_msg)

            converted_exc = context.exception
            self.assertIsInstance(converted_exc, fcr_ttypes.SessionException)
            self.assertEqual(exc._CODE, converted_exc.code)
            self.assertEqual(str(exc), converted_exc.message)

        # Test that all other known Exceptions are converted
        for exc in self.KNOWN_EXCEPTIONS:
            # Make sure that the exception is Thrift-defined now
            with self.assertRaises(fcr_ttypes.SessionException) as context:
                # pyre-fixme[6]: For 2nd argument expected `Exception` but got
                #  `Type[Exception]`.
                res = await test_raise_exception(self, exc=exc, return_msg=return_msg)

            converted_exc = context.exception
            self.assertIsInstance(converted_exc, fcr_ttypes.SessionException)
            self.assertEqual(self.KNOWN_EXCEPTIONS[exc], converted_exc.code)
            self.assertEqual(str(exc), converted_exc.message)

        # Test that all unknown Exceptions are converted
        unknown_exc = Exception("This is an unknown exception!")

        # Make sure that the exception is Thrift-defined now
        with self.assertRaises(fcr_ttypes.SessionException) as context:
            res = await test_raise_exception(
                self, exc=unknown_exc, return_msg=return_msg
            )

        converted_exc = context.exception
        self.assertIsInstance(converted_exc, fcr_ttypes.SessionException)
        self.assertEqual(FcrErrorCode.UNKNOWN, converted_exc.code)
        self.assertEqual(repr(unknown_exc), converted_exc.message)

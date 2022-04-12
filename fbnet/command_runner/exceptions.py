#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) Facebook, Inc. and its affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

from functools import wraps
from typing import Any, Callable, cast, ClassVar, TypeVar

import asyncssh
from fbnet.command_runner_asyncio.CommandRunner import ttypes as fcr_ttypes
from fbnet.command_runner_asyncio.CommandRunner.ttypes import FcrErrorCode


class FcrBaseException(Exception):
    """
    Base exception class, do not raise this class.
    - raise subclass referring to specific type of error
    - raise UnknownError if it's actually unknown
    """

    _CODE: ClassVar[FcrErrorCode] = FcrErrorCode.UNKNOWN

    async def to_thrift_exception(self) -> fcr_ttypes.SessionException:
        return fcr_ttypes.SessionException(
            message=str(self),
            code=self._CODE,
        )


class UnknownException(FcrBaseException):
    """
    an explicit unknown exception class
    """

    _CODE: ClassVar[FcrErrorCode] = FcrErrorCode.UNKNOWN


class ValidationErrorException(FcrBaseException):
    _CODE: ClassVar[FcrErrorCode] = FcrErrorCode.VALIDATION_ERROR


class PermissionErrorException(FcrBaseException):
    _CODE: ClassVar[FcrErrorCode] = FcrErrorCode.PERMISSION_ERROR


class ValueErrorException(FcrBaseException):
    _CODE: ClassVar[FcrErrorCode] = FcrErrorCode.VALUE_ERROR


class UnsupportedDeviceErrorException(FcrBaseException):
    _CODE: ClassVar[FcrErrorCode] = FcrErrorCode.UNSUPPORTED_DEVICE_ERROR


class UnsupportedCommandErrorException(FcrBaseException):
    _CODE: ClassVar[FcrErrorCode] = FcrErrorCode.UNSUPPORTED_COMMAND_ERROR


class RuntimeErrorException(FcrBaseException):
    _CODE: ClassVar[FcrErrorCode] = FcrErrorCode.RUNTIME_ERROR


class AssertionErrorException(FcrBaseException):
    _CODE: ClassVar[FcrErrorCode] = FcrErrorCode.ASSERTION_ERROR


class LookupErrorException(FcrBaseException):
    _CODE: ClassVar[FcrErrorCode] = FcrErrorCode.LOOKUP_ERROR


class StreamReaderErrorException(FcrBaseException):
    _CODE: ClassVar[FcrErrorCode] = FcrErrorCode.STREAM_READER_ERROR


class CommandExecutionTimeoutErrorException(FcrBaseException):
    _CODE: ClassVar[FcrErrorCode] = FcrErrorCode.COMMAND_EXECUTION_TIMEOUT_ERROR


class NotImplementedErrorException(FcrBaseException):
    _CODE: ClassVar[FcrErrorCode] = FcrErrorCode.NOT_IMPLEMENTED_ERROR


class TypeErrorException(FcrBaseException):
    _CODE: ClassVar[FcrErrorCode] = FcrErrorCode.TYPE_ERROR


class AttributeErrorException(FcrBaseException):
    _CODE: ClassVar[FcrErrorCode] = FcrErrorCode.ATTRIBUTE_ERROR


class TimeoutErrorException(FcrBaseException):
    _CODE: ClassVar[FcrErrorCode] = FcrErrorCode.TIMEOUT_ERROR


class DeviceErrorException(FcrBaseException):
    _CODE: ClassVar[FcrErrorCode] = FcrErrorCode.DEVICE_ERROR


class CommandExecutionErrorException(FcrBaseException):
    _CODE: ClassVar[FcrErrorCode] = FcrErrorCode.COMMAND_EXECUTION_ERROR


class ConnectionErrorException(FcrBaseException):
    _CODE: ClassVar[FcrErrorCode] = FcrErrorCode.CONNECTION_ERROR


class ConnectionTimeoutErrorException(FcrBaseException):
    _CODE: ClassVar[FcrErrorCode] = FcrErrorCode.CONNECTION_TIMEOUT_ERROR


def convert_to_fcr_exception(e: Exception) -> FcrBaseException:
    """
    Convert all generic exceptions to FcrBaseException types
    Leaves FcrBaseException types unchanged
    """
    if isinstance(e, FcrBaseException):
        return e
    elif isinstance(e, PermissionError):
        # use str(e) for known exceptions to keep exception messages clean
        return PermissionErrorException(str(e))
    elif isinstance(e, ValueError):
        return ValueErrorException(str(e))
    elif isinstance(e, AssertionError):
        return AssertionErrorException(str(e))
    elif isinstance(e, LookupError) or isinstance(e, KeyError):
        return LookupErrorException(str(e))
    elif isinstance(e, NotImplementedError):
        return NotImplementedErrorException(str(e))
    elif isinstance(e, asyncssh.misc.DisconnectError):
        return ConnectionErrorException(str(e))
    elif isinstance(e, TypeError):
        return TypeErrorException(str(e))
    elif isinstance(e, AttributeError):
        return AttributeErrorException(str(e))
    elif isinstance(e, TimeoutError):
        return TimeoutErrorException(str(e))
    elif isinstance(e, RuntimeError):
        # keep RuntimeError as last elif case to avoid interfering
        # with conversion of other RuntimeError-derived exceptions
        # and catch any unidentified RuntimeError-derived exceptions
        return RuntimeErrorException(str(e))
    else:
        # use repr(e) for unknown exceptions to preserve exception information
        return UnknownException(repr(e))


F = TypeVar("F", bound=Callable[..., Any])


def ensure_thrift_exception(fn: F) -> F:
    """
    Catch all FcrBaseExceptions and generic exception
    Convert to Thrift SessionException and raise
    """

    @wraps(fn)
    async def wrapper(self, *args, **kwargs):
        try:
            return await fn(self, *args, **kwargs)
        except Exception as e:
            if isinstance(e, fcr_ttypes.SessionException):
                raise e
            # Thrift defined InstanceOverloaded exceptions are only for internal use
            # so don't have to convert to Thrift defined SessionException
            elif isinstance(e, fcr_ttypes.InstanceOverloaded):
                raise e

            fcr_ex: fcr_ttypes.SessionException = await convert_to_fcr_exception(
                e
            ).to_thrift_exception()

            raise fcr_ex from e

    return cast(F, wrapper)

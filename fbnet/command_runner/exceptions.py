#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) Facebook, Inc. and its affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

from functools import wraps
from typing import ClassVar, Callable, Any, TypeVar, cast

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


class RuntimeErrorException(FcrBaseException):
    _CODE: ClassVar[FcrErrorCode] = FcrErrorCode.RUNTIME_ERROR


class DeviceErrorException(FcrBaseException):
    _CODE: ClassVar[FcrErrorCode] = FcrErrorCode.DEVICE_ERROR


class ConnectionErrorException(FcrBaseException):
    _CODE: ClassVar[FcrErrorCode] = FcrErrorCode.CONNECTION_ERROR


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

            fcr_ex: fcr_ttypes.SessionException
            if isinstance(e, FcrBaseException):
                fcr_ex = await e.to_thrift_exception()
            elif isinstance(e, PermissionError):
                # use str(e) for known exceptions to keep exception messages clean
                fcr_ex = await PermissionErrorException(str(e)).to_thrift_exception()
            elif isinstance(e, ValueError):
                fcr_ex = await ValueErrorException(str(e)).to_thrift_exception()
            elif isinstance(e, RuntimeError):
                fcr_ex = await RuntimeErrorException(str(e)).to_thrift_exception()
            else:
                # use repr(e) for unknown exceptions to preserve exception information
                fcr_ex = await UnknownException(repr(e)).to_thrift_exception()

            raise fcr_ex

    return cast(F, wrapper)

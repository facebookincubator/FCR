#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) Facebook, Inc. and its affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import re
import xml.etree.ElementTree as et
from functools import lru_cache, wraps
from typing import Optional, Set, Union

from fbnet.command_runner.exceptions import ValidationErrorException
from fbnet.command_runner_asyncio.CommandRunner import ttypes


_XML_NAMESPACE_REGEX: str = r"""\{[^}]*\}"""
_NETCONF_BASE_CAPABILITY_REGEX: str = ".*netconf:base:[0-9]+[.][0-9]+$"


def canonicalize(val):
    """
    A helper function to convert all 'str' to 'bytes' in given value. The
    values can either be a string or a list. We will recursively convert each
    member of the list.
    """
    if isinstance(val, list):
        return [canonicalize(v) for v in val]
    if isinstance(val, str):
        return val.encode("utf8")
    return val


def _check_device(device: Optional[ttypes.Device]) -> None:
    if not device:
        raise ValidationErrorException("Required argument (device) cannot be None.")

    missing_list = []
    if not device.hostname:
        missing_list.append("hostname")

    if not device.username:
        missing_list.append("username")

    # Here we check strictly whether the password is None. This is for
    # sometimes when the device is unprovisioned, it does not require
    # password to login. In this case, we allow user to enter an empty
    # string
    if device.password is None:
        missing_list.append("password")

    if missing_list:
        raise ValidationErrorException(
            f"Following required Device fields are missing: {missing_list}"
        )


def _check_session(session: Optional[ttypes.Session]) -> None:
    if not session:
        raise ValidationErrorException("Required argument (session) cannot be None.")

    missing_list = []
    if not session.hostname:
        missing_list.append("hostname")

    if not session.id:
        missing_list.append("id")

    if not session.name:
        missing_list.append("name")

    if missing_list:
        raise ValidationErrorException(
            f"Following required Session fields are missing: {missing_list}"
        )


# TODO: Expose cache size to cli option
@lru_cache(maxsize=128)
def construct_netconf_capability_set(
    netconf_hello_msg: Optional[Union[str, bytes]]
) -> Set[str]:
    """
    Given a str or a bytes of netconf hello message, return a set of netconf base
    capabilities in that hello message
    For example, given a netconf hello message:
    <?xml version="1.0" encoding="UTF-8" ?>
    <hello xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">
        <capabilities>
            <capability>urn:ietf:params:netconf:base:1.0</capability>
            <capability>urn:ietf:params:netconf:capability:rollback-on-error:1.0</capability>
            <capability>urn:ietf:params:netconf:capability:validate:1.1</capability>
            <capability>urn:ietf:params:netconf:capability:confirmed-commit:1.1</capability>
        </capabilities>
    </hello>
    This function will return {"urn:ietf:params:netconf:base:1.0"}
    """

    capabilities = set()
    if not netconf_hello_msg:
        return capabilities

    root = et.fromstring(netconf_hello_msg)

    # Retrieve the xml namespace from the tag of root of ElementTree
    # For later usage of the iter method that searches for capability
    namespace_match = re.search(_XML_NAMESPACE_REGEX, root.tag, re.IGNORECASE)
    ns = namespace_match.group(0) if namespace_match else ""

    # Iteratively look for element in the xml that has the tag that matches
    # the pattern 'namespace' + capability. For example, a typical Netconf 1.0
    # hello message would look like this after constructing the element tree:
    # <{urn:ietf:params:xml:ns:netconf:base:1.0}hello xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">
    #   <{urn:ietf:params:xml:ns:netconf:base:1.0}capabilities>
    #     <{urn:ietf:params:xml:ns:netconf:base:1.0}capability>urn:ietf:params:netconf:base:1.0</capability>
    #   </capabilities>
    # </hello>
    # In order to match capability items, we need to include the namespace while searching
    for capability in root.iter(f"{ns}capability"):
        if not capability.text:
            # sanity check
            continue
        elif re.search(
            _NETCONF_BASE_CAPABILITY_REGEX,
            capability.text,
            re.IGNORECASE,
        ):
            capabilities.add(capability.text)

    return capabilities


def input_fields_validator(fn):  # noqa C901
    @wraps(fn)
    async def wrapper(self, *args, **kwargs):

        for i, arg in enumerate(args):

            if arg is None:
                raise ValidationErrorException(
                    f"The ({i + 1})th argument cannot be None."
                )
            elif isinstance(arg, ttypes.Device):
                _check_device(arg)
            elif isinstance(arg, ttypes.Session):
                _check_session(arg)
            # This if-statememt will match device_to_commands or device_to_configlets
            elif isinstance(arg, dict):
                for device in arg:
                    _check_device(device)

        for argument, val in kwargs.items():
            if argument == "command" and not val:
                raise ValidationErrorException(
                    "Required argument (command) cannot be None."
                )
            elif argument == "device":
                _check_device(val)
            elif argument == "session":
                _check_session(val)
            elif argument == "device_to_commands" or argument == "device_to_configlets":
                if not val:
                    raise ValidationErrorException(
                        f"Required argument ({argument}) cannot be None."
                    )

                for device in val:
                    _check_device(device)

        return await fn(self, *args, **kwargs)

    return wrapper

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# pyre-unsafe

# Copyright (c) Facebook, Inc. and its affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import re
import xml.etree.ElementTree as et
from collections import namedtuple
from functools import lru_cache, wraps
from typing import Any, Dict, List, NamedTuple, Optional, Set, TYPE_CHECKING, Union

from fbnet.command_runner.exceptions import (
    LookupErrorException,
    ValidationErrorException,
)
from fbnet.command_runner_asyncio.CommandRunner import ttypes


if TYPE_CHECKING:
    from fbnet.command_runner.device_info import DeviceInfo
    from fbnet.command_runner.service import FcrServiceBase

_XML_NAMESPACE_REGEX: str = r"""\{[^}]*\}"""
_NETCONF_BASE_CAPABILITY_REGEX: str = ".*netconf:base:[0-9]+[.][0-9]+$"

CommandInfo = namedtuple("CommandInfo", "cmd precmd prompt_re")
DeviceIP = namedtuple("DeviceIP", ["name", "addr", "mgmt_ip"])
IPInfo = NamedTuple("IPInfo", [("addr", str), ("is_pingable", bool)])


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


class IPUtils:
    @classmethod
    def proxy_required(cls, ip: str) -> bool:
        """
        Returns a boolean stating whether an IP address requires proxy connectivity
        """

        return False

    @classmethod
    def should_nat(cls, ip: str, service: Optional["FcrServiceBase"] = None) -> bool:
        """
        Returns a boolean stating whether an IP address requires NAT connectivity
        """

        return False

    @classmethod
    async def translate_address(
        cls, ip: str, service: Optional["FcrServiceBase"] = None
    ) -> str:
        """
        Returns the translated address (NAT) for a given IP address
        """

        return ip

    @classmethod
    def check_ip(cls, ip: str, service: Optional["FcrServiceBase"] = None) -> bool:
        """
        Returns a boolean stating whether an IP address is good for use
        Common indicators are pingability / reachability
        """

        return True

    @classmethod
    def is_mgmt_ip(cls, ip: DeviceIP) -> bool:
        """
        Returns a boolean stating whether an IP address is a management IP or not
        """

        return False

    @classmethod
    def get_ip(
        cls, options: Dict[str, Any], devinfo: "DeviceInfo", service: "FcrServiceBase"
    ) -> List[IPInfo]:
        """
        Returns list of Tuple with IP address of the given DeviceInfo and whether it is pingable or not.

        first_ip = devinfo.get_ip(...)[0]
        ip_address = first_ip.addr
        is_pingable = first_ip.is_pingable
        """

        # If user specified an ip address, then use it directly
        ip_list: List[IPInfo] = []
        ip_address = options.get("ip_address")
        if ip_address:
            return [IPInfo(ip_address, cls.check_ip(ip_address, service))]

        # If use_mgmt_ip is True, then return list of MGMT IP addresses
        use_mgmt_ip = options.get("mgmt_ip", False)
        if use_mgmt_ip:
            devinfo.inc_counter("device_info.mgmt_ip")
            ip_list = cls._get_ip_list(
                use_mgmt_ip=True, service=service, devinfo=devinfo
            )
            if len(ip_list) == 0:
                # No valid MGMT IPs were found when user specifies use_mgmt_ip, raise
                # LookupError
                raise LookupErrorException(
                    "User has set 'mgmt_ip=True' in the request but no mgmt ip is "
                    f"found for {devinfo.hostname}"
                )
            return ip_list

        # Return all valid IP addresses sorted by pingability
        devinfo.inc_counter("device_info.default_ip")
        ip_list = cls._get_ip_list(
            use_mgmt_ip=use_mgmt_ip, service=service, devinfo=devinfo
        )
        if len(ip_list) == 0:
            # None of the IPs is valid, raise LookupError
            raise LookupErrorException(
                f"No Valid IP address was found for the device {devinfo.hostname}"
            )
        return ip_list

    @classmethod
    def _get_ip_list(
        cls, devinfo: "DeviceInfo", service: "FcrServiceBase", use_mgmt_ip: bool = False
    ) -> List[IPInfo]:
        """
        A helper method for get_ip method
        """

        pingable_list: List[IPInfo] = []
        non_pingable_list: List[IPInfo] = []
        for ip in devinfo._pref_ips + [devinfo._ip]:
            # ip.addr is None
            if not ip.addr:
                continue

            # Check if MGMT IP and go to the next IP if current IP is not MGMT
            if use_mgmt_ip and not cls.is_mgmt_ip(ip):
                continue

            # Check if its pingable
            if cls.check_ip(ip, service):
                pingable_list.append(IPInfo(ip.addr, True))
            else:
                if ip.addr == devinfo._ip.addr:
                    non_pingable_list = [IPInfo(ip.addr, False)] + non_pingable_list
                else:
                    non_pingable_list.append(IPInfo(ip.addr, False))
        # Give preference to IPs that are pingable
        return pingable_list + non_pingable_list

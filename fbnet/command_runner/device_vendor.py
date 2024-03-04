#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# pyre-unsafe

# Copyright (c) Facebook, Inc. and its affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import json
import os
import re

from fbnet.command_runner_asyncio.CommandRunner.ttypes import SessionType

from . import utils
from .base_service import ServiceObj
from .command_session import SSHCommandSession
from .options import Option
from .ssh_netconf import SSHNetconf


class VendorConfig:
    def __init__(self, defaults, session_names):
        self._cfg = {}
        self._session_names = session_names
        self.update(defaults)

    def __getattr__(self, attr):
        return self._cfg.get(attr)

    def update(self, cfg):
        for prop, val in cfg.items():
            self._cfg[prop] = utils.canonicalize(val)

        if "supported_sessions" in cfg:
            # Refresh supported_sessions only if it's updated
            self._cfg["supported_sessions"] = {
                self._session_names[s] for s in self._cfg["supported_sessions"]
            }
        if "session_type" in cfg:
            self._cfg["session_type"] = self._session_names[self._cfg["session_type"]]
            # Default session type should be supported
            self._cfg["supported_sessions"].add(self._cfg["session_type"])


class DeviceVendor(ServiceObj):

    _DEFAULTS = {
        "cli_setup": [b"term len 0", b"term width 511"],
        "prompt_regex": [rb"[\w.]+[>#$]"],
        "cmd_timeout_sec": 30,
        "clear_command": b"\x15",
        "session_type": b"ssh",
        "supported_sessions": {b"ssh", b"netconf"},
        "autocomplete": True,
        "port": 22,
    }

    _PROMPTS_RE = re.compile(
        # pyre-fixme[16]: `int` has no attribute `__iter__`.
        b"|".join([b"(%s)" % p for p in _DEFAULTS["prompt_regex"]]),
        re.M,
    )

    _SESSION_NAMES = {b"ssh": SessionType.SSH, b"netconf": SessionType.SSH_NETCONF}

    _SESSION_TYPES = {
        SessionType.SSH: SSHCommandSession,
        SessionType.SSH_NETCONF: SSHNetconf,
    }

    def __init__(self, vendor_name, service):
        super().__init__(service, "DeviceVendor")
        self._vendor_name = vendor_name
        self._config = VendorConfig(self._DEFAULTS, self._SESSION_NAMES)
        self._prompt_re = self._PROMPTS_RE

    def __repr__(self):
        props = {
            "cli_setup": self._config.cli_setup,
            "prompt_regex": self._config.prompt_regex,
            "cmd_timeout_sec": self._config.cmd_timeout_sec,
            "autocomplete": self._config.autocomplete,
        }
        return "DeviceVendor(%s) %s" % (self.vendor_name, props)

    @classmethod
    def register_counters(cls, stats_mgr):
        for session_type in cls._SESSION_TYPES.values():
            session_type.register_counters(stats_mgr)
        stats_mgr.register_counter("device_vendor.all_sessions")
        stats_mgr.register_counter("device_vendor.unsupported_session")

    def get_prompt_re(self, trailer=None):
        """
        Get prompt regex for the device. Optionally a trailer can be specified.
        This is extra text expected after the prompt. Mostly useful for
        interactive command. E.g. when we get a list of completion, the intial
        command is inserted after the prompt
        """
        if not trailer:
            return self._prompt_re
        return self._get_prompt_re(trailer)

    def get_port(self):
        return self._config.port

    @property
    def vendor_name(self):
        return self._vendor_name

    @property
    def cmd_timeout_sec(self):
        return self._config.cmd_timeout_sec

    @property
    def clear_command(self):
        return self._config.clear_command

    @property
    def exit_command(self):
        return self._config.exit_command

    @property
    def cli_setup(self):
        return self._config.cli_setup

    @property
    def session_type(self):
        return self._SESSION_TYPES[self._config.session_type]

    @property
    def autocomplete(self):
        return self._config.autocomplete

    def select_session_type(self, options):
        """
        Select session type for given set of options.
        Users can override session type here, by specifying session_type in
        options. This needs to be implemented for vendors supporting multiple
        session types
        """
        self.inc_counter("device_vendor.all_sessions")
        session_type = options.get("session_type", None)

        if session_type in self._config.supported_sessions:
            return self._SESSION_TYPES.get(session_type, self.session_type)
        else:
            if session_type is not None:
                self.logger.warning(
                    "Device vendor {} does not support session {}".format(
                        self._vendor_name, session_type
                    )
                )
                self.inc_counter("device_vendor.unsupported_session")
            return self.session_type

    def update_config(self, vendor_config):
        self._config.update(vendor_config)
        self._update_prompts_re()

    def set_user_prompts(self, prompts):
        self._config.update({"user_prompts": prompts})
        self._update_prompts_re()

    def _update_prompts_re(self):
        self._prompt_re = self._get_prompt_re()

    def _get_prompt_re(self, trailer=None):
        prompts = self._config.prompt_regex

        if self._config.shell_prompts:
            prompts += self._config.shell_prompts

        if self._config.user_prompts:
            prompts += self._config.user_prompts

        if self._config.bootstrap_prompts:
            prompts += self._config.bootstrap_prompts

        return self._build_prompt_re(prompts, trailer)

    @classmethod
    def _build_prompt_re(cls, prompts, trailer=None):
        all_prompts = (b"(%s)" % prompt for prompt in prompts)
        trailer = trailer or b""
        # the prompt must be at the start of the line.
        # Also since we are sending one command at a time, it must also be the
        # last text in the text. Although still not perfect, this greatly
        # reduces the probability of this matching some random text in the
        # output. Not that we are matching at end of the text, not at the end of
        # each line in text (re.M is not specified)
        return re.compile(
            b"(?<=[\n\r])(?P<prompt>"
            + b"|".join(all_prompts)
            + rb")\s*"
            + trailer
            + b"$",
            re.M,
        )


class DeviceVendors(ServiceObj):

    # User specified device vendor information
    device_vendors = Option(
        "--device_vendors",
        help="A JSON file containing vendor information",
        default=None,
    )

    def __init__(self, service, name=None):
        super().__init__(service, name)

        self._vendors = {}

        self._load_vendors_data()

    @classmethod
    def register_counters(cls, stats_mgr):
        DeviceVendor.register_counters(stats_mgr)

    def get(self, name):
        return self._vendors.get(name) or self._createVendor(name)

    def _update_user_prompts(self, path, cfg):
        if cfg is not None:
            for vendor, prompts in cfg["prompt_regexs"].items():
                self.get(vendor).set_user_prompts(prompts)

    def _update_device_vendors(self, path, cfg):
        # now load the vendor information
        for name, props in cfg["vendor_config"].items():
            vendor = self.get(name)
            vendor.update_config(props)

    def load_vendors(self, path, json_str):
        cfg = json.loads(json_str)
        return self._update_device_vendors(path, cfg)

    def _load_device_vendors(self):
        """
        Load device vendors specified on command line
        """
        if self.device_vendors and os.path.exists(self.device_vendors):
            self.logger.info("loading local file")
            with open(self.device_vendors, "rb") as fh:
                jsonb = fh.read()
            return self.load_vendors(self.device_vendors, jsonb.decode("utf-8"))

    def _load_vendors_data(self):
        """
        Load vendors information
        """
        self._load_device_vendors()

    def _createVendor(self, name):
        vendor = DeviceVendor(name, self.service)

        self._vendors[name] = vendor
        return vendor

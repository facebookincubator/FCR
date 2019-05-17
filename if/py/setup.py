#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) Facebook, Inc. and its affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

from setuptools import setup


setup(
    name="fcr-thrift",
    version="0.1.0a0",
    packages=["fbnet.command_runner_asyncio.CommandRunner"],
    package_dir={
        "fbnet.command_runner_asyncio.CommandRunner": "gen-py/fbnet/command_runner_asyncio/CommandRunner"
    },
    include_package_data=True,
    package_data={},
    entry_points={},
    test_suite="tests",
    license="MIT",
    description="FCR thrift interface",
    install_requires=[],
)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) Facebook, Inc. and its affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

from setuptools import setup


setup(
    name="fcr",
    version="0.1.0a0",
    packages=["fbnet.command_runner"],
    package_dir={},
    include_package_data=True,
    package_data={"fbnet.command_runner": ["*.json"]},
    entry_points={},
    test_suite="tests",
    license="MIT",
    description="Thrift Service to run commands on devices",
    long_description=open("README.md").read(),
    install_requires=["asyncssh", "future", "psutil"],
    setup_requires=["mock"],
)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Copyright (c) 2015-present, Facebook, Inc.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree. An additional grant
# of patent rights can be found in the PATENTS file in the same directory.

from setuptools import setup


setup(
    name='fcr',
    version='0.1.0a0',
    packages=[
        'fbnet.command_runner',
    ],
    package_dir={},
    include_package_data=True,
    package_data={},
    entry_points={},

    test_suite="tests",

    license='BSD+',
    description='Thrift Service to run commands on devices',

    long_description=open("README.md").read(),
    install_requires=[
        'asyncssh',
        'future',
    ]
)

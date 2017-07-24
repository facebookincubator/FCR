#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2017-present, Facebook, Inc.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree. An additional grant
# of patent rights can be found in the PATENTS file in the same directory.
#

from setuptools import setup


setup(
    name='fb303-py-asyncio',
    version='0.1.0a0',
    packages=[
        'fb303_asyncio',
        'fb303_asyncio.fb303',
    ],
    package_dir={
        'fb303_asyncio': '.',
        'fb303_asyncio.fb303': 'gen-py/fb303_asyncio/fb303',
    },
    include_package_data=True,
    package_data={},
    entry_points={},

    license='BSD+',
    description='Simple fb303 thrift interface',

    install_requires=[]
)

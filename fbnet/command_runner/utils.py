#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2017-present, Facebook, Inc.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree. An additional grant
# of patent rights can be found in the PATENTS file in the same directory.
#


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

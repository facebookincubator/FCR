#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) Facebook, Inc. and its affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import unittest

from fbnet.command_runner.utils import canonicalize


class CanonicalizeTest(unittest.TestCase):
    def test_canonicalize(self):
        self.assertEqual(canonicalize("abc"), b"abc")
        self.assertEqual(canonicalize(b"abc"), b"abc")
        self.assertEqual(canonicalize(["abc", "xyz", b"123"]), [b"abc", b"xyz", b"123"])

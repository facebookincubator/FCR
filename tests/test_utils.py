# Copyright (c) Facebook, Inc. and its affiliates. All Rights Reserved

import unittest

from fbnet.command_runner.utils import canonicalize


class CanonicalizeTest(unittest.TestCase):
    def test_canonicalize(self):
        self.assertEqual(canonicalize("abc"), b"abc")
        self.assertEqual(canonicalize(b"abc"), b"abc")
        self.assertEqual(canonicalize(["abc", "xyz", b"123"]), [b"abc", b"xyz", b"123"])

#!/usr/bin/env python3

import sys
import os
import unittest

import bcrypt

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from app.utils import bytesToHexString, hexStringToBytes


class TestUser(unittest.TestCase):
    def test_bytes_conversion(self):
        salt = bcrypt.gensalt()
        bytes = bcrypt.hashpw("pw123".encode("utf-8"), salt)
        hexString = bytesToHexString(bytes)
        newBytes = hexStringToBytes(hexString)
        self.assertEqual(bytes, newBytes)

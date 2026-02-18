#!/usr/bin/env python3

import logging
import sys
import os
import unittest

import bcrypt

# Add the src directory to the path so we can import the user module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src', 'bartenders-of-corfu'))

from app.utils import bytesToHexString, hexStringToBytes

class TestUser(unittest.TestCase):

    def test_bytes_conversion(self):
        salt = bcrypt.gensalt()
        bytes = bcrypt.hashpw("pw123".encode('utf-8'), salt)
        hexString = bytesToHexString(bytes)
        newBytes = hexStringToBytes(hexString)
        self.assertEqual(bytes, newBytes)
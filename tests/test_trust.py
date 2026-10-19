import ssl
import sys
import unittest
from unittest import mock

import truststore

from harness_discussion import __main__ as entry


class SystemTrustTest(unittest.TestCase):
    def tearDown(self):
        truststore.extract_from_ssl()

    def test_main_verifies_tls_with_the_system_trust_store(self):
        platform = "harness_discussion.mac.main" if sys.platform == "darwin" else "harness_discussion.win.main"
        with mock.patch(f"{platform}.main"):
            entry.main()
        self.assertIs(ssl.SSLContext, truststore.SSLContext)


if __name__ == "__main__":
    unittest.main()

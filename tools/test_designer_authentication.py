import unittest
from verified_yaxunit import designer_authentication


class DesignerAuthenticationTests(unittest.TestCase):
    def test_named_stand_credentials_reach_designer(self):
        self.assertEqual(designer_authentication('Srvr="localhost";Ref="isolated";Usr="stand-admin";Pwd="synthetic";'),
                         ['/Nstand-admin', '/Psynthetic'])

    def test_empty_password_does_not_consume_next_designer_key(self):
        self.assertEqual(designer_authentication('File="F:/fixture";Usr="tester";Pwd="";'), ['/Ntester'])

    def test_anonymous_connection_needs_no_authentication_keys(self):
        self.assertEqual(designer_authentication('Srvr="localhost";Ref="isolated";'), [])


if __name__ == '__main__':
    unittest.main()

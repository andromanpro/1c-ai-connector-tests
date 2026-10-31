import unittest

from check_saved_dialog_access import connection_for_user


class ConnectionTests(unittest.TestCase):
    def test_separators_and_old_credentials(self):
        expected = 'Srvr="localhost";Ref="test";Usr="reader";Pwd="synthetic";'
        for tail in ['', ';', ';;', ';  ', ';Usr="admin";Pwd="old";', ';usr=admin;pwd=old']:
            with self.subTest(tail=tail):
                actual = connection_for_user('Srvr="localhost";Ref="test"' + tail, 'reader', 'synthetic')
                self.assertEqual(expected, actual)
                self.assertNotIn(';;', actual)

    def test_quoted_values_are_preserved(self):
        actual = connection_for_user('File="C:/semi;colon";Usr="old";Pwd="a""b";', 'a"b', 'c"d')
        self.assertEqual('File="C:/semi;colon";Usr="a""b";Pwd="c""d";', actual)


if __name__ == '__main__':
    unittest.main()

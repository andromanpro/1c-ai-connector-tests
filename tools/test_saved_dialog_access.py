import unittest
from unittest.mock import patch
from contextlib import redirect_stderr
from pathlib import Path
from tempfile import TemporaryDirectory
import io
import sys

from check_saved_dialog_access import connection_for_user
import check_saved_dialog_access


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


class NativeDispatchTests(unittest.TestCase):
    def test_default_entry_uses_native_runner(self):
        with patch('run_saved_dialog_rights.main', return_value=7) as native:
            self.assertEqual(check_saved_dialog_access.main(), 7)
            native.assert_called_once_with()

    def test_incomplete_legacy_command_refuses_before_creating_output(self):
        with TemporaryDirectory() as folder:
            output = Path(folder) / 'must-not-exist'
            arguments = ['check_saved_dialog_access.py', '--output', str(output), '--mcp-helper', 'unused']
            with patch.object(sys, 'argv', arguments), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    check_saved_dialog_access.main()
            self.assertEqual(raised.exception.code, 2)
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from export_verified_sources import snapshot_project_name


class ProjectSnapshot(unittest.TestCase):
    def test_uses_declared_name_for_an_arbitrarily_named_source_directory(self):
        descriptor = '<projectDescription><name>ИИКона_разработки.Тесты</name></projectDescription>'.encode('utf-8')
        self.assertEqual(snapshot_project_name(descriptor), 'ИИКона_разработки.Тесты')

    def test_refuses_missing_name(self):
        with self.assertRaises(RuntimeError):
            snapshot_project_name(b'<projectDescription/>')

    def test_refuses_path_instead_of_project_name(self):
        for name in ['../outside', 'parent/child', 'parent\\child', 'C:outside', '.', '..']:
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                snapshot_project_name(('<projectDescription><name>' + name + '</name></projectDescription>').encode())


if __name__ == '__main__':
    unittest.main(verbosity=2)

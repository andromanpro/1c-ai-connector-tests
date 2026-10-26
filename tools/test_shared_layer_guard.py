from pathlib import Path
import json
import tempfile
import unittest

from shared_layer_guard import fingerprint, verify_shared_layer


class SharedLayerProvenance(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.path = self.root / 'shared-layer.json'
        self.roots = {}
        self.manifest = {'schema_version': 1}
        for scope in ('product', 'shared_tests'):
            canonical = self.root / scope / 'canonical'
            examiner = self.root / scope / 'examiner'
            canonical.mkdir(parents=True)
            examiner.mkdir()
            for root in (canonical, examiner):
                (root / 'Module.bsl').write_text('Возврат Результат;\n', encoding='utf-8')
            self.roots[scope] = {'canonical': canonical, 'examiner': examiner}
            self.manifest[scope] = {'canonical_files': {'Module.bsl': fingerprint(canonical / 'Module.bsl')},
                                    'permitted_differences': {}, 'examiner_only_files': []}
        self.save()

    def save(self):
        self.path.write_text(json.dumps(self.manifest), encoding='utf-8')

    def verify(self):
        return verify_shared_layer(self.path, self.roots)

    def test_identical_is_read_only(self):
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertTrue(self.verify()['passed'])
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_stale_examiner_code_is_rejected(self):
        (self.roots['product']['examiner'] / 'Module.bsl').write_text('Возврат СтарыйРезультат;', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Undeclared shared-layer difference'):
            self.verify()

    def test_new_canonical_file_cannot_be_omitted(self):
        (self.roots['product']['canonical'] / 'New.bsl').write_text('Возврат 1;', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Canonical file set'):
            self.verify()

    def test_missing_shared_test_is_rejected(self):
        (self.roots['shared_tests']['examiner'] / 'Module.bsl').unlink()
        with self.assertRaisesRegex(ValueError, 'Missing shared file'):
            self.verify()

    def test_undeclared_addition_is_rejected(self):
        (self.roots['product']['examiner'] / 'Unexpected.bsl').write_text('Возврат 1;', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'undeclared examiner file'):
            self.verify()

    def test_both_sides_of_allowed_difference_are_bound(self):
        path = self.roots['product']['examiner'] / 'Module.bsl'
        path.write_text('Возврат УчебныйРезультат;', encoding='utf-8')
        self.manifest['product']['permitted_differences']['Module.bsl'] = {
            'canonical_sha256': self.manifest['product']['canonical_files']['Module.bsl']['normalized_sha256'],
            'examiner_sha256': fingerprint(path)['normalized_sha256'], 'reason': 'Educational consumer keeps its own label'}
        self.save()
        self.assertTrue(self.verify()['passed'])
        path.write_text('Возврат НеобъявленныйРезультат;', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Examiner side'):
            self.verify()

    def test_empty_reason_cannot_allow_arbitrary_change(self):
        self.manifest['product']['permitted_differences']['Module.bsl'] = {'reason': ' '}
        self.save()
        with self.assertRaisesRegex(ValueError, 'concrete reason'):
            self.verify()

    def test_only_bom_and_line_endings_are_transport_differences(self):
        path = self.roots['product']['examiner'] / 'Module.bsl'
        path.write_bytes(b'\xef\xbb\xbf' + 'Возврат Результат;\r\n'.encode('utf-8'))
        self.assertTrue(self.verify()['passed'])
        path.write_text('Возврат  Результат;\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Undeclared shared-layer difference'):
            self.verify()

    def test_binary_template_cannot_be_normalized_as_text(self):
        canonical = self.roots['product']['canonical'] / 'Template.bin'
        examiner = self.roots['product']['examiner'] / 'Template.bin'
        canonical.write_bytes(b'opaque\r\nbytes')
        examiner.write_bytes(b'opaque\nbytes')
        self.manifest['product']['canonical_files']['Template.bin'] = fingerprint(canonical)
        self.save()
        with self.assertRaisesRegex(ValueError, 'Undeclared shared-layer difference'):
            self.verify()


if __name__ == '__main__':
    unittest.main(verbosity=2)

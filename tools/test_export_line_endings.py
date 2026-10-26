"""Keep compiler input text identical; cover the actual CR-only region header."""
from pathlib import Path
import tempfile
import unittest

from export_verified_sources import normalize_export_module


class ExportLineEndingTests(unittest.TestCase):
    def test_cr_only_region_header_becomes_explicit_lines(self):
        raw = '#Область ПрограммныйИнтерфейс\r\rФункция Пример() Экспорт\r\tВозврат "цитата";\rКонецФункции\r#КонецОбласти\r'
        expected = '#Область ПрограммныйИнтерфейс\r\n\r\nФункция Пример() Экспорт\r\n\tВозврат "цитата";\r\nКонецФункции\r\n#КонецОбласти\r\n'
        with tempfile.TemporaryDirectory(prefix='iikona-export-eol-') as directory:
            path = Path(directory) / 'Module.bsl'
            path.write_bytes(b'\xef\xbb\xbf' + raw.encode('utf-8'))
            proof = normalize_export_module(path)
            self.assertEqual(path.read_bytes(), b'\xef\xbb\xbf' + expected.encode('utf-8'))
            self.assertNotEqual(proof['before_sha256'], proof['after_sha256'])
            self.assertIsNone(normalize_export_module(path))

    def test_lf_keeps_utf8_text_quotes_and_bom_absence(self):
        raw = 'Текст = "\"\"цитата\"\"";\nПуть = "C:\\temp";\n'
        with tempfile.TemporaryDirectory(prefix='iikona-export-eol-') as directory:
            path = Path(directory) / 'Module.bsl'
            path.write_bytes(raw.encode('utf-8'))
            normalize_export_module(path)
            self.assertEqual(path.read_bytes(), raw.replace('\n', '\r\n').encode('utf-8'))


if __name__ == '__main__':
    unittest.main()

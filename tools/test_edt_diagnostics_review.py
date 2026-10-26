from pathlib import Path
import tempfile
import unittest

from export_verified_sources import review_cli_diagnostics


class DiagnosticReview(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.log = self.root / 'workspace/.metadata/.log'
        self.log.parent.mkdir(parents=True)

    def test_shutdown_failure_stays_visible_as_incomplete(self):
        self.log.write_text('!ENTRY com._1c.g5.v8.dt.core 1 0 2026-01-01 00:00:00\n'
            '!MESSAGE Project context is being stopped: Base (IDE_SHUTDOWN)\n'
            '!ENTRY com.e1c.g5.v8.dt.check 4 0 2026-01-01 00:00:01\n'
            '!MESSAGE Delegated check thrown an exception\n!STACK 0\n'
            'java.lang.NullPointerException\n at BmModelManager.getDtProject\n', encoding='utf-8')
        result = review_cli_diagnostics(self.root, {})
        self.assertFalse(result['all_edt_checks_clean'])
        self.assertEqual(result['classified_events']['open_vendor_shutdown_failure'], 1)

    def test_same_failure_before_shutdown_is_rejected(self):
        self.log.write_text('!ENTRY com.e1c.g5.v8.dt.check 4 0 2026-01-01 00:00:01\n'
            '!MESSAGE Delegated check thrown an exception\n!STACK 0\n'
            'java.lang.NullPointerException\n at BmModelManager.getDtProject\n', encoding='utf-8')
        with self.assertRaisesRegex(Exception, 'Unexpected EDT'):
            review_cli_diagnostics(self.root, {})

    def test_successful_process_cannot_hide_product_compilation_error(self):
        self.log.write_text('', encoding='utf-8')
        report = self.root / 'product.tsv'
        report.write_text('date\tОшибка конфигурации\tcategory\tProduct\t\tModule\t1\tSyntax error\n',
                          encoding='utf-8')
        with self.assertRaisesRegex(Exception, 'Unexpected EDT'):
            review_cli_diagnostics(self.root, {'Product': {'edt_validation': str(report)}})


if __name__ == '__main__':
    unittest.main()

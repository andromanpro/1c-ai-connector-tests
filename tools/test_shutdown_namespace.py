from pathlib import Path
import tempfile
import unittest

from export_verified_sources import review_cli_diagnostics

STOP = ('!ENTRY com._1c.g5.v8.dt.core 1 0 2026-10-29 09:30:58\n'
        '!MESSAGE Project context is being stopped: Base (IDE_SHUTDOWN)\n')
FAILURE = ('!ENTRY com.e1c.g5.v8.dt.check 4 0 2026-10-29 09:31:00\n'
           '!MESSAGE Delegated check thrown an exception\n!STACK 0\n'
           "com._1c.g5.v8.bm.core.BmNamespaceInactiveException: The namespace 'Base' is not active\n"
           ' at com._1c.g5.v8.bm.core.BmObject.checkEngineRunningIfNecessary(BmObject.java:1146)\n'
           ' at com.e1c.g5.v8.dt.bsl.check.DocumentationCommentBasicDelegateCheck.check(Check.java:104)\n')

class NamespaceAtShutdown(unittest.TestCase):
    def check(self, content):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            log = root / 'workspace/.metadata/.log'
            log.parent.mkdir(parents=True)
            log.write_text(content, encoding='utf-8')
            return review_cli_diagnostics(root, {})

    def test_stopped_exact_namespace_is_visible_shutdown_failure(self):
        result = self.check(STOP + FAILURE)
        self.assertFalse(result['all_edt_checks_clean'])
        self.assertEqual(result['classified_events']['open_vendor_shutdown_failure'], 1)

    def test_before_shutdown_still_rejected(self):
        with self.assertRaisesRegex(Exception, 'Unexpected EDT'):
            self.check(FAILURE + STOP)

    def test_another_namespace_still_rejected(self):
        with self.assertRaisesRegex(Exception, 'Unexpected EDT'):
            self.check(STOP + FAILURE.replace("namespace 'Base'", "namespace 'Other'"))

    def test_different_cause_still_rejected(self):
        with self.assertRaisesRegex(Exception, 'Unexpected EDT'):
            self.check(STOP + FAILURE.replace('BmNamespaceInactiveException', 'IllegalStateException'))

    def test_without_engine_guard_still_rejected(self):
        with self.assertRaisesRegex(Exception, 'Unexpected EDT'):
            self.check(STOP + FAILURE.replace('BmObject.checkEngineRunningIfNecessary', 'DifferentCheck.check'))

if __name__ == '__main__':
    unittest.main()

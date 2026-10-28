import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import export_verified_sources
from edt_export_retention import compact_export, remove_cache


class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.cache = self.root / 'cli-configuration/org.eclipse.osgi'
        self.model = self.root / 'workspace/.metadata/.plugins/com._1c.g5.v8.dt.core/bm-model-manager'
        for folder in (self.cache, self.model):
            folder.mkdir(parents=True)
            (folder / 'regenerable.bin').write_bytes(b'cache')
        self.evidence = {
            'sources.zip': b'frozen sources', 'snapshot/Module.bsl': b'source',
            'extension/Configuration.xml': b'export', 'cli.log': b'cli log',
            'workspace/.metadata/.log': b'failure stack',
            'cli-configuration/config.ini': b'profile',
            'workspace/.metadata/.plugins/other/state': b'other diagnostics'}
        for name, data in self.evidence.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

    def test_removes_only_regenerable_caches_and_preserves_failure_evidence(self):
        result = compact_export(self.root)
        self.assertEqual(len(result['removed']), 2)
        self.assertEqual(result['errors'], [])
        for name, data in self.evidence.items():
            self.assertEqual((self.root / name).read_bytes(), data)
        self.assertFalse(self.cache.exists())
        self.assertFalse(self.model.exists())

    def test_explicit_keep_preserves_both_environments(self):
        result = compact_export(self.root, keep_workspace=True)
        self.assertTrue(self.cache.exists())
        self.assertTrue(self.model.exists())
        self.assertEqual(result['removed'], [])

    def test_repeated_cleanup_is_harmless(self):
        compact_export(self.root)
        self.assertEqual(compact_export(self.root)['removed'], [])

    def test_refuses_root_unrecognized_path_and_escape(self):
        for target in (self.root, self.root / 'snapshot', self.root / '../cli-configuration/org.eclipse.osgi'):
            with self.subTest(target=target), self.assertRaises(ValueError):
                remove_cache(target, self.root)
        self.assertTrue(self.cache.exists())

    def test_link_cannot_redirect_deletion(self):
        outside = self.root / 'unrelated'
        outside.mkdir()
        (outside / 'keep').write_bytes(b'untouched')
        link = self.cache / 'link'
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError as error:
            self.skipTest(str(error))
        with self.assertRaises(ValueError):
            remove_cache(self.cache, self.root)
        self.assertEqual((outside / 'keep').read_bytes(), b'untouched')

    def run_export_wrapper(self, *, exited, error=None, keep=False):
        export_root = self.root / 'export'
        export_root.mkdir()
        for name in ('cli-configuration', 'workspace'):
            (self.root / name).rename(export_root / name)
        class Receipt:
            folder = self.root
            def record(inner, name, data):
                inner.recorded = (name, data)
        receipt = Receipt()
        def fake_export(*args, execution):
            execution['exited'] = exited
            if error:
                raise error
            return {'verified': True}
        with patch.object(export_verified_sources, '_export', side_effect=fake_export):
            result = export_verified_sources.export(receipt, {}, Path('unused'), keep_workspace=keep)
        return result, receipt, export_root

    def test_export_success_compacts_only_after_exit(self):
        result, receipt, root = self.run_export_wrapper(exited=True)
        self.assertEqual(result, {'verified': True})
        self.assertFalse((root / 'cli-configuration/org.eclipse.osgi').exists())
        self.assertEqual((root / 'workspace/.metadata/.log').read_bytes(), b'failure stack')
        self.assertEqual(receipt.recorded[0], 'edt-export-retention')

    def test_validation_failure_retains_original_error_and_log(self):
        with self.assertRaisesRegex(RuntimeError, 'original validation error'):
            self.run_export_wrapper(exited=True, error=RuntimeError('original validation error'))
        self.assertFalse((self.root / 'export/cli-configuration/org.eclipse.osgi').exists())
        self.assertEqual((self.root / 'export/workspace/.metadata/.log').read_bytes(), b'failure stack')

    def test_interrupted_export_keeps_potentially_live_cache(self):
        with self.assertRaises(KeyboardInterrupt):
            self.run_export_wrapper(exited=False, error=KeyboardInterrupt())
        self.assertTrue((self.root / 'export/cli-configuration/org.eclipse.osgi').exists())

    def test_export_keep_option_preserves_environment(self):
        result, receipt, root = self.run_export_wrapper(exited=True, keep=True)
        self.assertTrue((root / 'cli-configuration/org.eclipse.osgi').exists())
        self.assertEqual(receipt.recorded[1]['policy'], 'explicit_keep_workspace')

    @unittest.skipUnless(__import__('os').name == 'nt', 'Windows sharing lock')
    def test_live_workspace_lock_prevents_model_cache_removal(self):
        import win32con
        import win32file
        lock = self.root / 'workspace/.metadata/.lock'
        handle = win32file.CreateFile(str(lock), win32con.GENERIC_READ | win32con.GENERIC_WRITE,
                                     0, None, win32con.CREATE_ALWAYS, 0, None)
        try:
            result = compact_export(self.root)
            self.assertTrue(self.model.exists())
            self.assertEqual(len(result['errors']), 1)
            self.assertEqual((self.model / 'regenerable.bin').read_bytes(), b'cache')
        finally:
            handle.Close()


if __name__ == '__main__':
    unittest.main()

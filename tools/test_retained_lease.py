"""A stuck child remains a blocker after its runner releases the OS lock."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('lease_runner', Path(__file__).with_name('run-query-rights-tests.py'))
legacy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(legacy)


class RetainedLeaseTests(unittest.TestCase):
    def test_ordinary_release_allows_the_next_operation(self):
        with tempfile.TemporaryDirectory() as directory:
            lease = legacy.Lease('synthetic-base', directory=directory)
            lease.release()
            following = legacy.Lease('synthetic-base', directory=directory)
            following.release()

    def test_attention_blocks_the_next_operation_after_runner_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            lease = legacy.Lease('synthetic-base', directory=directory)
            lease.retain({'state': 'needs_attention', 'pid': 999, 'recovery_required': True})
            lease.release()
            with self.assertRaisesRegex(RuntimeError, 'verified recovery'):
                legacy.Lease('synthetic-base', directory=directory)
            # Unrelated test bases retain their own independent lease.
            other = legacy.Lease('another-synthetic-base', directory=directory)
            other.release()


if __name__ == '__main__':
    unittest.main()

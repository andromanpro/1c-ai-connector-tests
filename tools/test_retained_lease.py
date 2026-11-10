"""A stuck child remains a blocker after its runner releases the OS lock."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import patch

import psutil

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


class VerifiedRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.folder = self.directory / 'retained-run'
        self.folder.mkdir()
        self.marker = {
            'state': 'needs_attention', 'pid': 321, 'process_created_at': 123.5,
            'run_folder': str(self.folder), 'target': 'server:localhost/test',
            'reason': 'timeout', 'force_kill': False, 'recovery_required': True}
        inputs = {'run_id': self.folder.name, 'target': self.marker['target'], 'source_hash': 'a' * 64}
        raw = json.dumps(inputs).encode()
        (self.folder / 'inputs.json').write_bytes(raw)
        (self.folder / 'inputs.sha256').write_text(hashlib.sha256(raw).hexdigest())
        (self.folder / 'client-needs-attention.json').write_text(
            json.dumps(dict(self.marker, run_id=self.folder.name, source_hash=inputs['source_hash'])))
        lease = legacy.Lease('recovery-base', directory=self.directory)
        self.block = lease.block_path
        lease.retain(self.marker)
        lease.release()
        self.dead = patch('psutil.Process', side_effect=psutil.NoSuchProcess(self.marker['pid']))
        self.dead.start()
        self.addCleanup(self.dead.stop)
        self.restored = dict(target=self.marker['target'], source_hash=inputs['source_hash'],
                             cleanup_complete=True, policy_restored=True, scheduler_restored=True,
                             preservation=dict(users=True, constants=True, model_keys=True, tables=True))

    def acquire(self):
        lease = legacy.Lease('recovery-base', directory=self.directory, recovery_run_folder=self.folder)
        self.addCleanup(lease.release)
        return lease

    def test_marker_stays_until_verified_restoration_and_blocks_other_operations(self):
        lease = self.acquire()
        self.assertTrue(self.block.exists())
        with self.assertRaises(RuntimeError):
            legacy.Lease('recovery-base', directory=self.directory)
        proof = self.folder / 'recovered.json'
        lease.complete_recovery(proof, self.restored)
        self.assertFalse(self.block.exists())
        self.assertTrue(json.loads(proof.read_bytes())['recovered'])
        lease.release()
        following = legacy.Lease('recovery-base', directory=self.directory)
        following.release()

    def test_incomplete_restoration_cannot_unblock(self):
        lease = self.acquire()
        for field in ('cleanup_complete', 'policy_restored', 'scheduler_restored', 'preservation'):
            with self.subTest(field=field):
                state = dict(self.restored)
                state.pop(field)
                with self.assertRaisesRegex(RuntimeError, 'restoration are required'):
                    lease.complete_recovery(self.folder / 'recovered.json', state)
                self.assertTrue(self.block.exists())

    def test_wrong_source_or_target_cannot_unblock(self):
        lease = self.acquire()
        for field in ('source_hash', 'target'):
            with self.subTest(field=field), self.assertRaisesRegex(RuntimeError, 'restoration are required'):
                lease.complete_recovery(self.folder / 'recovered.json', dict(self.restored, **{field: 'wrong'}))
        self.assertTrue(self.block.exists())

    def test_live_owned_process_refuses_recovery(self):
        alive = SimpleNamespace(create_time=lambda: self.marker['process_created_at'])
        with patch('psutil.Process', return_value=alive):
            with self.assertRaisesRegex(RuntimeError, 'still running'):
                self.acquire()
        self.assertTrue(self.block.exists())
        self.acquire()

    def test_reused_pid_does_not_block_or_terminate_an_unrelated_process(self):
        unrelated = SimpleNamespace(create_time=lambda: self.marker['process_created_at'] + 1)
        with patch('psutil.Process', return_value=unrelated):
            self.acquire()
        self.assertTrue(self.block.exists())

    def test_corrupt_receipt_is_refused(self):
        (self.folder / 'inputs.json').write_text('{}')
        with self.assertRaisesRegex(RuntimeError, 'digest differs'):
            self.acquire()
        self.assertTrue(self.block.exists())

    def test_wrong_run_is_refused(self):
        other = self.directory / 'another-run'
        other.mkdir()
        with self.assertRaisesRegex(RuntimeError, 'identity differs'):
            legacy.Lease('recovery-base', directory=self.directory, recovery_run_folder=other)
        self.assertTrue(self.block.exists())

    def test_changed_retained_identity_is_refused(self):
        path = self.folder / 'client-needs-attention.json'
        data = json.loads(path.read_bytes())
        data['pid'] += 1
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(RuntimeError, 'receipts differ'):
            self.acquire()

    def test_marker_changes_are_refused_at_completion(self):
        lease = self.acquire()
        self.block.write_text(json.dumps(dict(self.marker, reason='changed')))
        with self.assertRaisesRegex(RuntimeError, 'marker changed'):
            lease.complete_recovery(self.folder / 'recovered.json', self.restored)
        self.assertTrue(self.block.exists())

    def test_released_lease_cannot_complete_recovery(self):
        lease = self.acquire()
        lease.release()
        with self.assertRaisesRegex(RuntimeError, 'active verified'):
            lease.complete_recovery(self.folder / 'recovered.json', self.restored)
        self.assertTrue(self.block.exists())


if __name__ == '__main__':
    unittest.main()

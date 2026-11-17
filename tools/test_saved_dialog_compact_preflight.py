import argparse
import ast
import contextlib
import gc
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import uuid


class CompactPreflightReport(unittest.TestCase):
    def test_report_and_lease_survive_failed_preflight_and_disconnect(self):
        source = Path(__file__).with_name('check_saved_dialog_compact.py')
        tree = ast.parse(source.read_text(encoding='utf-8-sig'))
        main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'main')
        suite = Mock()
        suite.connect.side_effect = RuntimeError('preflight refused')
        suite.disconnect.side_effect = RuntimeError('disconnect refused')
        lease = Mock()
        actors = SimpleNamespace(C={'password': ''}, Actors=Mock(return_value=suite),
                                 lease=Mock(return_value=lease), O=None)

        def evidence_factory(output):
            evidence = Mock()

            def record(name, value):
                (output / (name + '.json')).write_text(json.dumps(value), encoding='utf-8')

            evidence.record.side_effect = record
            return evidence

        namespace = dict(argparse=argparse, Path=Path, sys=sys, json=json, gc=gc, uuid=uuid,
                         actors=actors, Evidence=evidence_factory, Mcp=Mock(),
                         edt_agent_provider=Mock(), Client=Mock())
        exec(compile(ast.Module(body=[main], type_ignores=[]), str(source), 'exec'), namespace)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'result'
            arguments = ['compact', '--output', str(output), '--mcp-helper', 'unused-helper']
            with patch.object(sys, 'argv', arguments), contextlib.redirect_stdout(io.StringIO()):
                code = namespace['main']()
            self.assertEqual(code, 1)
            report = json.loads((output / 'result.json').read_bytes())
            self.assertEqual(report['error'], 'preflight refused')
            self.assertEqual(report['disconnect_error'], 'disconnect refused')
            self.assertFalse(report['cleanup_complete'])
        lease.release.assert_called_once()
        namespace['Client'].assert_not_called()

"""Regression controls for compiler evidence, including the real HTTP-response failure."""
import json
from pathlib import Path
import tempfile
import unittest
from subprocess import TimeoutExpired
from unittest.mock import Mock
from platform_config_check import classify_check, record_check, wait_for_compiler
from verification_receipt import Receipt


class CompilerEvidenceTest(unittest.TestCase):
    def test_compiler_wait_is_bounded_by_total_deadline(self):
        process = Mock()
        process.wait.side_effect = TimeoutExpired('test', 30)
        process.poll.return_value = None
        clock = iter((0, 0, 30, 35)).__next__
        self.assertIsNone(wait_for_compiler(process, 35, clock))
        self.assertEqual([call.kwargs['timeout'] for call in process.wait.call_args_list], [30, 5])
        process.poll.assert_called_once_with()

    def test_compiler_wait_captures_normal_exit(self):
        process = Mock()
        process.wait.return_value = 0
        self.assertEqual(wait_for_compiler(process, 5, lambda: 0), 0)
        process.wait.assert_called_once_with(timeout=5)
        process.poll.assert_not_called()

    def test_clean_native_completion(self):
        self.assertTrue(classify_check(0, True, 'Проверка конфигурации завершена.\n')['passed'])

    def test_real_external_connection_failure(self):
        text = ('{ИИКона ОбщийМодуль.КИИ_СерверMCPДиспетчер.Модуль(168,17)}: '
                'Тип не определен (HTTPСервисОтвет)\n')
        self.assertFalse(classify_check(101, True, text)['passed'])

    def test_false_zero_exit_does_not_hide_native_diagnostic(self):
        text = '{ИИКона ОбщийМодуль.Модуль.Модуль(1,1)}: Переменная не определена\n'
        self.assertFalse(classify_check(0, True, text)['passed'])

    def test_test_extension_compilation_failure_is_also_rejected(self):
        text = ('{Тесты ОбщийМодуль.Тесты_КИИ_МониторингОшибок.Модуль(112,89)}: '
                "Ожидается символ ','\n")
        self.assertFalse(classify_check(0, True, text)['passed'])

    def test_missing_log_is_not_success(self):
        self.assertFalse(classify_check(0, False, '')['passed'])

    def test_nonzero_without_diagnostics_is_not_success(self):
        self.assertFalse(classify_check(1, True, '')['passed'])

    def test_real_receipt_binds_identity_once(self):
        with tempfile.TemporaryDirectory(prefix='iikona-compiler-receipt-') as directory:
            root = Path(directory).resolve()
            self.assertTrue(root.is_relative_to(Path(tempfile.gettempdir()).resolve()))
            source = root/'source'
            source.mkdir()
            (source/'fixture.bsl').write_text('// Compiler evidence fixture\n', encoding='utf-8')
            receipt = Receipt.begin(root/'runs', {'fixture': source}, 'file:compiler-fixture', ['Tests.Compiler'])
            record_check(receipt, 'compiler-test', {'run_id': 'untrusted', 'source_hash': 'untrusted', 'passed': True})
            saved = json.loads((receipt.folder/'compiler-test.json').read_text(encoding='utf-8'))
            self.assertEqual(saved['run_id'], receipt.spec['run_id'])
            self.assertEqual(saved['source_hash'], receipt.spec['source_hash'])
            self.assertTrue(saved['passed'])


if __name__ == '__main__':
    unittest.main()

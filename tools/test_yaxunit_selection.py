"""Registered method paths are separate from exact expected JUnit cases."""
import unittest

import verified_yaxunit as runner
from verification_receipt import VerificationError


class SelectionTests(unittest.TestCase):
    def test_date_and_dotted_parameter_values_are_not_filter_path_parts(self):
        cases = [
            'Тесты_Банк.НеМеняется(ДатаСоздания, 01.01.2020 0:00:00)',
            'Тесты_Банк.НеМеняется(Адрес, example.org)',
            'Тесты_Форма.Открывается',
        ]
        original = list(cases)
        result = runner.registered_test_filter(cases)
        self.assertEqual(result, {'modules': ['Тесты_Банк', 'Тесты_Форма'],
                                  'tests': ['Тесты_Банк.НеМеняется', 'Тесты_Форма.Открывается']})
        self.assertEqual(cases, original)

    def test_invalid_selection_is_refused_before_launch(self):
        for case in ['', 'Module', 'Module.Method.Context', 'Module.Bad name',
                     '.Method', 'Module.Method(', 'Module.Method(value)trailing']:
            with self.subTest(case=case), self.assertRaises(VerificationError):
                runner.registered_test_filter([case])

    def test_empty_and_duplicate_exact_cases_are_not_accepted(self):
        for cases in [[], ['Module.Method', 'Module.Method']]:
            with self.subTest(cases=cases), self.assertRaises(VerificationError):
                runner.registered_test_filter(cases)


if __name__ == '__main__':
    unittest.main()

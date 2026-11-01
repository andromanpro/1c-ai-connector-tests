import unittest
from run_saved_dialog_rights import MODULE, select_role_cases


def plan(*names):
    tests = [MODULE + '.' + name for name in names]
    return {'tests': tests, 'test_contexts': {name: 'Сервер' for name in tests}}


class RoleSelectionTests(unittest.TestCase):
    def test_admin_storage_assertions_are_not_executed_by_limited_role(self):
        admin = ['УдалениеУбираетВсеДанныеБеседы', 'ГрупповоеУдалениеСохраняетНевыбраннуюБеседу',
                 'ГрупповоеУдалениеНеОбходитЧужогоВладельца', 'ЧужаяБеседаЗащищенаОтУдаления']
        selected = select_role_cases(plan('УдалениеСохраняетДругуюБеседу', *admin))
        self.assertEqual(len(selected), 5)
        self.assertFalse({MODULE + '.' + name for name in admin}.intersection(selected))

    def test_unclassified_case_refuses_instead_of_guessing_rights(self):
        with self.assertRaisesRegex(Exception, 'Unclassified'):
            select_role_cases(plan('НовыйНепроверенныйТест'))

    def test_wrong_context_refuses(self):
        value = plan('УдалениеСохраняетДругуюБеседу')
        value['test_contexts'][value['tests'][0]] = 'КлиентУправляемоеПриложение'
        with self.assertRaisesRegex(Exception, 'context'):
            select_role_cases(value)

    def test_duplicate_selection_refuses(self):
        with self.assertRaisesRegex(Exception, 'Duplicate'):
            select_role_cases(plan('УдалениеСохраняетДругуюБеседу', 'УдалениеСохраняетДругуюБеседу'))

    def test_own_limited_probes_are_not_duplicated(self):
        value = plan('УдалениеСохраняетДругуюБеседу', 'КонтекстОграниченнойРоли')
        selected = select_role_cases(value)
        self.assertEqual(selected.count(MODULE + '.КонтекстОграниченнойРоли'), 1)

    def test_admin_only_plan_is_not_a_meaningful_role_suite(self):
        with self.assertRaisesRegex(Exception, 'No selected'):
            select_role_cases(plan('УдалениеУбираетВсеДанныеБеседы'))


if __name__ == '__main__':
    unittest.main()

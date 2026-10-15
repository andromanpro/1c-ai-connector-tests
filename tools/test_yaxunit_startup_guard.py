import unittest
from verification_receipt import VerificationError
from yaxunit_startup_guard import require_startup_roles, startup_failure


class StartupGuardTests(unittest.TestCase):
    def test_basic_profile_cannot_launch_yaxunit(self):
        with self.assertRaisesRegex(VerificationError, 'SaveUserData'):
            require_startup_roles(['БазовыеПраваБСП', 'КИИ_БазовыеПрава'])

    def test_standard_saving_role_suffices_without_administration(self):
        require_startup_roles(['БазовыеПраваБСП', 'КИИ_БазовыеПрава', 'СохранениеДанныхПользователя'])

    def test_stand_administrator_can_initialize(self):
        require_startup_roles(['ПолныеПрава'])

    def test_current_platform_error_is_fatal_before_test(self):
        result = startup_failure('Инициализация: Ошибка при вызове метода контекста (Сохранить)\r\n'
                                 '{YAXUNIT ОбщийМодуль.ЮТКонтекстСлужебныйВызовСервера.Модуль(25)}\r\n'
                                 '[НарушениеПравДоступа]\r\n')
        self.assertEqual(result['kind'], 'access-denied')
        self.assertFalse(result['test_execution_proven'])

    def test_partial_error_is_detected_without_waiting_for_stack(self):
        self.assertIsNotNone(startup_failure('Инициализация: Ошибка при вызове метода контекста'))

    def test_other_initialization_error_is_classified(self):
        self.assertEqual(startup_failure('Инициализация: Ошибка загрузки компоненты')['kind'],
                         'initialization-error')

    def test_expected_access_exception_in_a_test_is_not_startup_failure(self):
        self.assertIsNone(startup_failure('Проверка чужой записи: [НарушениеПравДоступа]'))

    def test_normal_initialization_is_not_failure(self):
        self.assertIsNone(startup_failure('Инициализация: выполнена\nТесты запущены'))

    def test_no_error_summary_does_not_trigger_failure(self):
        self.assertIsNone(startup_failure('Инициализация: ошибок нет'))


if __name__ == '__main__':
    unittest.main()

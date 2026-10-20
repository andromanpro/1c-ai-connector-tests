import unittest
import mcp_database_fixtures as fixture


class SelectionTests(unittest.TestCase):
    def test_isolated_agent_database_cases_require_the_http_server(self):
        for name in ['Базы_ДваИсточникаПетля', 'Базы_КонтрольПДКаталогаИРезультатов',
                     'Базы_ОтключениеМеждуВызовами', 'Базы_УдаленныйПользовательНеПередается']:
            with self.subTest(name=name):
                self.assertTrue(fixture.requires_database_fixture(['Тесты_КИИ_АгентАнализа.'+name]))

    def test_transport_catalog_and_profile_suites_require_the_http_server(self):
        for module in ['Тесты_КИИ_УдаленныеБазыMCP', 'Тесты_КИИ_ПодключенияКБазам',
                       'Тесты_КИИ_ПраваПодключенийКБазам']:
            with self.subTest(module=module):
                self.assertTrue(fixture.requires_database_fixture([module+'.ЛичныйИнструментДоступен']))

    def test_unrelated_empty_and_similar_module_names_do_not_bind_the_port(self):
        for selection in [[], ['Тесты_КИИ_Ядро.Ответ'],
                          ['Тесты_КИИ_ПодключенияКБазамСтарые.Проба'],
                          ['Тесты_КИИ_АгентАнализа.БазовыйЗапрос']]:
            with self.subTest(selection=selection):
                self.assertFalse(fixture.requires_database_fixture(selection))

    def test_mixed_selection_still_starts_one_fixture(self):
        self.assertTrue(fixture.requires_database_fixture([
            'Тесты_КИИ_Ядро.Ответ', 'Тесты_КИИ_ПраваПодключенийКБазам.СлужебныйИнструментДоступен']))


if __name__=='__main__':unittest.main()

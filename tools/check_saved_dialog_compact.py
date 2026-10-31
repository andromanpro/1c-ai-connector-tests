"""Capture the real chat at a physical window size and native 1C form scale.

Uses the configured administrator only for visual verification and the Testpilot
helper. Access checks belong to run_saved_dialog_rights.py. Creates one explicitly
tracked conversation; cleanup refuses to touch any pre-existing conversation.
"""
import argparse
import gc
import json
import os
from pathlib import Path
import sys
import traceback
import uuid

os.environ['TC1C_SCREENSHOTS'] = 'true'
sys.path.insert(0, 'F:/WorkAI/tools/1c-testpilot/app')
from testpilot import Client
import bsp_test_users as actors
from check_saved_dialog_access import Evidence, REGISTERS, register_snapshot, query
from check_saved_dialog_forms import resize_owned_client
from edt_yaxunit import Mcp, edt_agent_provider


def check_feedback_pages(client, identity, options, evidence):
    """Exercise preview, this conversation's journal, list sizing and parameter flow."""
    form_code = '''
ПараметрыОткрытия = Новый Структура("Диалог", Параметры["dialogue"]);
Форма = ПолучитьФорму("Обработка.КИИ_ТестИИ.Форма.Форма", ПараметрыОткрытия, , Параметры["dialogue"]);
'''
    value = client.execute_code(context='client', parameters={'dialogue': identity}, code=form_code + '''
Форма.Элементы.МатериалыБеседы.Видимость = Истина;
Результат = Форма.Элементы.ТаблицаВложенийТаблицаВложений2.ТолькоПросмотр
    И Не Форма.Элементы.ТаблицаВложенийОтправлять.ТолькоПросмотр;
''')
    assert value.get('result') is True, 'Material descriptions must be read-only while selection remains editable'
    evidence.record('dialogue-materials', client.get_context(result_mode='full', include_tables=True))
    options.output.joinpath('dialogue-materials.png').write_bytes(client.get_screenshot().png)
    client.execute_code(context='client', parameters={'dialogue': identity}, code=form_code + '''
Форма.Элементы.МатериалыБеседы.Видимость = Ложь;
Результат = Истина;
''')
    value = client.execute_code(context='client', parameters={'dialogue': identity}, code=form_code + '''
Форма.Элементы.ГруппаСтраницы.ТекущаяСтраница = Форма.Элементы.НастройкиДиалога;
Результат = Форма.Элементы.Найти("ВыполнитьВФоне") = Неопределено;
''')
    assert value.get('result') is True, 'A background-execution switch must not be offered when execution is always asynchronous'
    evidence.record('settings', client.get_context(result_mode='full', include_tables=True))
    options.output.joinpath('settings.png').write_bytes(client.get_screenshot().png)
    for page in ['СоставПросмотра', 'СообщенияПросмотра', 'ИнструментыПросмотра', 'ВложенияПросмотра']:
        value = client.execute_code(context='client', parameters={'dialogue': identity, 'page': page}, code=form_code + '''
Форма.Элементы.ГруппаСтраницы.ТекущаяСтраница = Форма.Элементы.СтраницаПередОтправкой;
Форма.Элементы.СтраницыПросмотра.ТекущаяСтраница = Форма.Элементы.Найти(Параметры["page"]);
Результат = Форма.Элементы.ПросмотрВложения.ТолькоПросмотр И ЗначениеЗаполнено(Форма.ПросмотрВложения);
''')
        assert value.get('result') is True, 'Preview must be read-only with a meaningful initial state'
        evidence.record(page, client.get_context(result_mode='full', include_tables=True))
        options.output.joinpath(page + '.png').write_bytes(client.get_screenshot().png)
    value = client.execute_code(context='client', parameters={'dialogue': identity}, code=form_code + '''
Форма.Элементы.ГруппаСтраницы.ТекущаяСтраница = Форма.Элементы.СтраницаЖурналДиалога;
Результат = Форма.Элементы.Найти("ИдентификаторДиалога") = Неопределено
    И Форма.Элементы.Найти("ДиалогЖурнала") = Неопределено
    И ЗначениеЗаполнено(Форма.СостояниеЖурналаДиалога);
''')
    assert value.get('result') is True, 'Journal must identify its conversation without editable GUID fields'
    evidence.record('journal', client.get_context(result_mode='full', include_tables=True))
    options.output.joinpath('journal.png').write_bytes(client.get_screenshot().png)
    value = client.execute_code(context='client', parameters={'scale': options.scale}, code='''
Форма = ПолучитьФорму("Обработка.КИИ_ТестИИ.Форма.Диалоги");
Форма.Масштаб = Параметры["scale"];
Форма.Открыть();
Результат = Форма.ИмяФормы;
''')
    assert value.get('result', '').endswith('.Диалоги'), 'Saved conversation list did not open'
    evidence.record('dialogue-list', client.get_context(result_mode='full', include_tables=True))
    options.output.joinpath('dialogue-list.png').write_bytes(client.get_screenshot().png)
    client.execute_code(context='client', code='''
Форма = ПолучитьФорму("Обработка.КИИ_ТестИИ.Форма.Диалоги");
Форма.Закрыть();
Результат = Истина;
''')
    value = client.execute_code(context='client', parameters={'dialogue': identity}, code=form_code + '''
ПараметрыСписка = Новый Структура("РежимВыбора", "Открытие");
Список = ПолучитьФорму("Обработка.КИИ_ТестИИ.Форма.Диалоги", ПараметрыСписка, Форма);
Список.Открыть();
ПараметрыКонтекста = Новый Структура("РежимВыбора", "Контекст");
Контекст = ПолучитьФорму("Обработка.КИИ_ТестИИ.Форма.Диалоги", ПараметрыКонтекста, Форма);
Контекст.Открыть();
Результат = Список <> Контекст И Не Список.Элементы.Материалы.Видимость И Контекст.Элементы.Материалы.Видимость;
Контекст.Закрыть();
Если Список.Открыта() Тогда
    Список.Закрыть();
КонецЕсли;
''')
    evidence.record('selector-identities', value)
    assert value.get('result') is True, 'Opening and material-selection modes must be independent for the same owner'
    for page in ['СтраницаСообщения', 'СтраницаФайлы']:
        value = client.execute_code(context='client', parameters={'scale': options.scale, 'page': page}, code='''
ПараметрыВыбора = Новый Структура("РежимВыбора", "Контекст");
Форма = ПолучитьФорму("Обработка.КИИ_ТестИИ.Форма.Диалоги", ПараметрыВыбора);
Форма.Масштаб = Параметры["scale"];
Форма.Открыть();
Форма.Элементы.СтраницыМатериалов.ТекущаяСтраница = Форма.Элементы.Найти(Параметры["page"]);
Результат = Форма.ИмяФормы;
''')
        assert value.get('result', '').endswith('.Диалоги'), 'Material-selection form did not open'
        evidence.record(page, client.get_context(result_mode='full', include_tables=True))
        options.output.joinpath(page + '.png').write_bytes(client.get_screenshot().png)
    # Temporary rows in this owned selection form only: never confirm their import.
    selector_code = '''
ПараметрыВыбора = Новый Структура("РежимВыбора", "Контекст");
Форма = ПолучитьФорму("Обработка.КИИ_ТестИИ.Форма.Диалоги", ПараметрыВыбора);
'''
    client.execute_code(context='client', code=selector_code + '''
СтрокаСообщения = Форма.Сообщения.Добавить();
СтрокаСообщения.Текст = "Временная проверка выбора строки";
СтрокаФайла = Форма.Файлы.Добавить();
СтрокаФайла.Имя = "temporary-ui-selection-check.txt";
Форма.Элементы.СтраницыМатериалов.ТекущаяСтраница = Форма.Элементы.СтраницаФайлы;
Результат = Истина;
''')
    client.find_object(name='ОтметитьСообщения').click()
    value = client.execute_code(context='client', code=selector_code + '''
Результат = Форма.Файлы[Форма.Файлы.Количество() - 1].Выбор
    И Не Форма.Сообщения[Форма.Сообщения.Количество() - 1].Выбор;
''')
    evidence.record('select-all-files', value)
    assert value.get('result') is True, 'Select all on the Files page must select files, leaving messages untouched'
    client.execute_code(context='client', code=selector_code + '''
Форма.Элементы.СтраницыМатериалов.ТекущаяСтраница = Форма.Элементы.СтраницаСообщения;
Результат = Истина;
''')
    client.find_object(name='ОтметитьСообщения').click()
    value = client.execute_code(context='client', code=selector_code + '''
Результат = Форма.Сообщения[Форма.Сообщения.Количество() - 1].Выбор;
''')
    evidence.record('select-all-messages', value)
    assert value.get('result') is True, 'Select all on the Messages page must select messages'
    client.find_object(name='СнятьВыбор').click()
    value = client.execute_code(context='client', code=selector_code + '''
Результат = Не Форма.Сообщения[Форма.Сообщения.Количество() - 1].Выбор
    И Не Форма.Файлы[Форма.Файлы.Количество() - 1].Выбор;
''')
    evidence.record('clear-all-selection', value)
    assert value.get('result') is True, 'Clear all must clear both pages without importing rows'
    client.execute_code(context='client', code='''
ПараметрыВыбора = Новый Структура("РежимВыбора", "Контекст");
Форма = ПолучитьФорму("Обработка.КИИ_ТестИИ.Форма.Диалоги", ПараметрыВыбора);
Форма.Закрыть();
Результат = Истина;
''')
    value = client.execute_code(context='client', parameters={'dialogue': identity, 'scale': options.scale}, code=form_code + '''
ПараметрыПодбора = Новый Структура("ЭкспертПоиска", Форма.Эксперт);
ФормаПодбора = ПолучитьФорму("Обработка.КИИ_ПроверкаПоискаЗнаний.Форма.Форма", ПараметрыПодбора);
ФормаПодбора.Масштаб = Параметры["scale"];
ФормаПодбора.Открыть();
Результат = ЗначениеЗаполнено(Форма.Эксперт) И ФормаПодбора.ЭкспертПоиска = Форма.Эксперт;
''')
    assert value.get('result') is True, 'Knowledge search must receive the selected expert'
    evidence.record('knowledge-expert', client.get_context(result_mode='full', include_tables=True))
    options.output.joinpath('knowledge-expert.png').write_bytes(client.get_screenshot().png)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--mcp-helper', type=Path, required=True)
    parser.add_argument('--size', type=int, nargs=2, default=[1280, 768])
    parser.add_argument('--scale', type=int, choices=range(50, 101), default=80)
    parser.add_argument('--feedback', action='store_true', help='Also check preview, journal, list and expert propagation')
    options = parser.parse_args()
    options.output.mkdir(exist_ok=False, parents=True)
    actors.O = options.output
    evidence = Evidence(options.output)
    actors.C['_edt_agent_provider'] = edt_agent_provider(Mcp(options.mcp_helper, evidence), actors.C)
    suite = actors.Actors()
    lease = actors.lease()
    identity = None
    before = None
    result = {'passed': False, 'cleanup_complete': False, 'scope': 'administrator visual verification',
              'requested_form_scale': options.scale}
    try:
        suite.connect()
        suite.baseline = suite.snapshot()
        before = register_snapshot(suite.base)
        evidence.record('baseline-dialogues', before)
        existing = {str(row.Диалог) for row in query(suite.base,
            'ВЫБРАТЬ Диалоги.Диалог ИЗ РегистрСведений.КИИ_ДиалогиЧата КАК Диалоги')}
        expert = suite.base.Справочники.КИИ_ЭкспертыИИ.ПустаяСсылка()
        if options.feedback:
            experts = suite.base.Справочники.КИИ_ЭкспертыИИ.Выбрать()
            assert experts.Следующий(), 'A configured expert is required for the feedback check'
            expert = experts.Ссылка
            experts = None
        identity = str(suite.base.КИИ_ХранениеДиалогов.СоздатьДиалог(expert))
        expert = None
        uuid.UUID(identity)
        assert identity not in existing, 'Visual fixture already existed'
        evidence.record('fixture', {'dialogue': identity, 'absent_before_creation': True})
        suite.disconnect()
        with Client() as client:
            launched = client.launch_client(base='localhost\\iikona_perf_20261011', server=True,
                user=actors.C['username'], password=actors.C['password'],
                exe=str(Path(actors.C['platform_bin']) / '1cv8c.exe'), version='8.3.27.1989',
                desktop='isolated', extra_args=['/RunModeManagedApplication'], wait=150,
                code_epf='F:/WorkAI/tools/1c-testpilot/onec/Testpilot/Testpilot.epf')
            evidence.record('launch', launched)
            value = client.execute_code(context='client', parameters={'dialogue': identity, 'scale': options.scale}, code='''
ПараметрыОткрытия = Новый Структура("Диалог", Параметры["dialogue"]);
Форма = ПолучитьФорму("Обработка.КИИ_ТестИИ.Форма.Форма", ПараметрыОткрытия, , Параметры["dialogue"]);
Форма.Масштаб = Параметры["scale"];
Форма.Открыть();
Результат = Форма.Масштаб;
''')
            evidence.record('native-scale', value)
            assert value.get('result') == options.scale, 'The native form scale was not confirmed'
            evidence.record('window-size', resize_owned_client(client, launched['pid'], *options.size))
            evidence.record('dialogue', client.get_context(result_mode='full', include_tables=True))
            options.output.joinpath('dialogue.png').write_bytes(client.get_screenshot().png)
            assert client.find_object(name='Промпт').get_data_presentation() == ''
            if options.feedback:
                check_feedback_pages(client, identity, options, evidence)
            result['passed'] = True
    except Exception as error:
        result['error'] = str(error).replace(str(actors.C['password']), '[password]') if actors.C['password'] else str(error)
        result['error_type'] = type(error).__name__
    finally:
        gc.collect()
        try:
            suite.connect()
            if identity is not None:
                uuid.UUID(identity)
                assert identity not in existing, 'Cleanup refuses a pre-existing identifier'
                for name in reversed(REGISTERS):
                    records = getattr(suite.base.РегистрыСведений, name).СоздатьНаборЗаписей()
                    records.Отбор.Диалог.Установить(identity)
                    records.Записать()
                    records = None
            assert register_snapshot(suite.base) == before, 'Dialogue data were not restored'
            suite.cleanup_generated_service_user()
            suite.cleanup()
            result['cleanup_complete'] = True
        except Exception as error:
            result['cleanup_error'] = str(error)
        finally:
            suite.disconnect()
            lease.release()
            evidence.record('result', result)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['passed'] and result['cleanup_complete'] else 1


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
    raise SystemExit(main())

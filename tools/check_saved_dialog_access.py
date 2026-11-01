"""Real BSP accounts: own dialogue operations and denial of foreign data, with exact cleanup."""
import argparse
import gc
import json
import re
from pathlib import Path
import sys

import win32com.client
import bsp_test_users as actors
from edt_yaxunit import Mcp, edt_agent_provider
from verification_receipt import require, digest
from verified_yaxunit import public_base

REGISTERS = ['КИИ_ДиалогиЧата', 'КИИ_СообщенияЧата', 'КИИ_МатериалыЧата', 'КИИ_ЗапросыЧата']
BASE_ROLES = ['БазовыеПраваБСП', '_ДемоБазовыеПраваБСП', 'ЗапускТолстогоКлиента',
              'ЗапускТонкогоКлиента', 'ЗапускВнешнегоСоединения', 'КИИ_БазовыеПрава']


def connection_for_user(connection, user, password):
    fields = re.sub(r'(?i)(?:Usr|Pwd)\s*=\s*(?:"(?:[^"]|"")*"|[^;]*);?', '', connection)
    fields = fields.rstrip('; \t\r\n')
    user = user.replace('"', '""')
    password = password.replace('"', '""')
    return fields + ';Usr="' + user + '";Pwd="' + password + '";'


class Evidence:
    def __init__(self, folder): self.folder = folder
    def record(self, name, value):
        actors.atomic(self.folder / (name + '.json'), value)
        return value


def structure(base, **values):
    result = base.NewObject('Структура')
    for name, value in values.items(): result.Вставить(name, value)
    return result


def array(base, values):
    result = base.NewObject('Массив')
    for value in values: result.Добавить(value)
    return result


def query(base, text, **parameters):
    request = base.NewObject('Запрос', text)
    for name, value in parameters.items(): request.УстановитьПараметр(name, value)
    return request.Выполнить().Выгрузить()


def register_snapshot(base):
    result = {}
    for name in REGISTERS:
        rows = query(base, 'ВЫБРАТЬ Данные.* ИЗ РегистрСведений.' + name + ' КАК Данные')
        rows.Сортировать('Диалог')
        result[name] = {'count': int(rows.Количество()),
                        'sha256': digest(str(base.ЗначениеВСтрокуВнутр(rows)).encode('utf-8'))}
    return result


def remove_actor_dialogues(suite, records, before):
    owned = array(suite.base, [record['ib_uid'] for record in records])
    rows = query(suite.base, 'ВЫБРАТЬ Диалоги.Диалог ИЗ РегистрСведений.КИИ_ДиалогиЧата КАК Диалоги ГДЕ Диалоги.Владелец В (&Владельцы)', Владельцы=owned)
    identities = [str(row.Диалог) for row in rows]
    require(not (set(record['ib_uid'] for record in records) & {user['uid'] for user in suite.baseline['ib_users'].values()}), 'Cleanup owner existed before this suite')
    for identity in identities:
        for name in reversed(REGISTERS):
            records_to_delete = getattr(suite.base.РегистрыСведений, name).СоздатьНаборЗаписей()
            records_to_delete.Отбор.Диалог.Установить(identity)
            records_to_delete.Записать()
    require(register_snapshot(suite.base) == before, 'Dialogue register baseline was not restored')


def _legacy_com_probe():
    sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--mcp-helper', type=Path, required=True)
    options = parser.parse_args()
    options.output.mkdir(parents=True, exist_ok=False)
    evidence = Evidence(options.output)
    actors.O = options.output
    mcp = Mcp(options.mcp_helper, evidence)
    actors.C['_edt_agent_provider'] = edt_agent_provider(mcp, actors.C)
    suite = actors.Actors()
    lease = actors.lease()
    result = {'kind': 'real-bsp-user-access', 'passed': False, 'checks': [], 'cleanup_complete': False}
    clients = {}
    records = {}
    before = None

    def save(): evidence.record('access-result', result)
    def check(name, value):
        result['checks'].append({'name': name, 'passed': bool(value)})
        save()
        require(value, name)
    def denied(name, call, fragment):
        try: call()
        except Exception as error:
            message = str(error)
            check(name, fragment in message)
        else: check(name, False)

    try:
        suite.connect()
        suite.baseline = suite.snapshot()
        before = register_snapshot(suite.base)
        result['before_registers'] = before
        for kind in ['a', 'b', 'viewer']:
            extra = ['КИИ_ОбщийЖурналЗапросовИИПросмотр'] if kind == 'viewer' else []
            records[kind] = suite.create(kind, BASE_ROLES + extra)
        result['actors'] = records
        save()
        suite.disconnect()

        for kind, record in records.items():
            connector = win32com.client.Dispatch('V83.COMConnector')
            connection = actors.C['connection']
            base = connector.Connect(connection_for_user(connection, record['name'], '123456'))
            clients[kind] = (connector, base)
            check(kind + '.target', public_base(str(base.СтрокаСоединенияИнформационнойБазы())) == actors.out['target'])
            check(kind + '.identity', str(base.XMLСтрока(base.ПользователиИнформационнойБазы.ТекущийПользователь().УникальныйИдентификатор)) == record['ib_uid'])
            check(kind + '.not_privileged', not base.ПривилегированныйРежим())

        a, b, viewer = [clients[k][1] for k in ['a', 'b', 'viewer']]
        api = a.КИИ_ХранениеДиалогов
        settings = a.КИИ_КонтекстДиалога.НастройкиПоУмолчанию()
        settings.ИспользоватьВложения = False
        settings.ИспользоватьЗнания = False
        first = str(api.СоздатьДиалог(a.Справочники.КИИ_ЭкспертыИИ.ПустаяСсылка(), settings))
        second = str(api.СоздатьДиалог(a.Справочники.КИИ_ЭкспертыИИ.ПустаяСсылка(), settings))
        foreign = str(b.КИИ_ХранениеДиалогов.СоздатьДиалог(b.Справочники.КИИ_ЭкспертыИИ.ПустаяСсылка()))
        result['dialogues'] = {'a': [first, second], 'b': [foreign]}
        save()
        own = api.Диалог(first)
        saved = api.СохранитьЧерновик(first, 'Own draft', a.Справочники.КИИ_ЭкспертыИИ.ПустаяСсылка(), settings, own.Версия)
        check('a.own_draft', api.Диалог(first).Черновик == 'Own draft')
        payload = a.ПолучитьДвоичныеДанныеИзСтроки('Synthetic owned attachment', 'UTF-8', False)
        material = str(api.ДобавитьФайл(first, structure(a, Имя='access-probe.txt', MIME='text/plain'), payload))
        check('a.own_attachment', api.СодержимоеМатериала(first, material).Размер() == payload.Размер())
        linked = str(api.ДобавитьИсточник(second, structure(a, Диалог=first, Материал=material)))
        check('a.own_cross_dialog_attachment', api.СодержимоеМатериала(second, linked).Размер() == payload.Размер())
        prepared = api.ДанныеДляОтправки(first, structure(a, Вопрос='Synthetic access check'), settings)
        request = str(api.НачатьЗапрос(first, prepared, structure(a, АдресПодготовки='', Диалог=first)))
        answer = structure(a, ЭтоОшибка=False, ТекстОтвета='Synthetic saved response', ВложенияОтвета=array(a, []))
        api.СохранитьИтогЗапроса(first, request, structure(a, Ответ=answer), '')
        check('a.own_messages', api.СообщенияДиалога(first).Количество() == 2)
        check('a.own_request', bool(api.СостояниеЗапроса(first, request)))
        check('a.own_list', {str(row.Диалог) for row in api.МоиДиалоги()} == {first, second})
        check('b.own_list', {str(row.Диалог) for row in b.КИИ_ХранениеДиалогов.МоиДиалоги()} == {foreign})
        check('viewer.empty_own_list', viewer.КИИ_ХранениеДиалогов.МоиДиалоги().Количество() == 0)
        expected_draft = str(api.Диалог(first).Черновик)

        for kind, base in [('b', b), ('viewer', viewer)]:
            foreign_api = base.КИИ_ХранениеДиалогов
            calls = {
                'read': lambda: foreign_api.Диалог(first),
                'messages': lambda: foreign_api.СообщенияДиалога(first),
                'materials': lambda: foreign_api.МатериалыДиалога(first),
                'content': lambda: foreign_api.СодержимоеМатериала(first, material),
                'rename': lambda: foreign_api.ПереименоватьДиалог(first, 'Forbidden rename'),
                'draft': lambda: foreign_api.СохранитьЧерновик(first, 'Forbidden draft', base.Справочники.КИИ_ЭкспертыИИ.ПустаяСсылка(), base.КИИ_КонтекстДиалога.НастройкиПоУмолчанию(), 1),
                'request': lambda: foreign_api.СостояниеЗапроса(first, request),
                'packet': lambda: foreign_api.ПакетДляВыполнения(first, request),
                'execute': lambda: foreign_api.ВыполнитьЗапрос(first, request),
                'mark': lambda: foreign_api.ОтметитьМатериал(first, material, False),
                'complete': lambda: foreign_api.СохранитьИтогЗапроса(first, request, None, 'Forbidden completion'),
                'startup': lambda: foreign_api.ЗаписатьСостояниеЗапуска(first, request, None, True),
                'refresh_source': lambda: foreign_api.ОбновитьИсточник(first, material),
                'delete': lambda: foreign_api.УдалитьДиалог(first, 1),
                'delete_many': lambda: foreign_api.УдалитьДиалоги(
                    array(base, [structure(base, Диалог=first, Версия=1)])),
            }
            for name, call in calls.items():
                denied(kind + '.foreign.' + name, call, 'Диалог недоступен текущему пользователю')
                check(kind + '.privilege_restored.' + name, not base.ПривилегированныйРежим())
            for name in REGISTERS:
                denied(kind + '.direct_register.' + name,
                       lambda name=name: query(base, 'ВЫБРАТЬ Данные.* ИЗ РегистрСведений.' + name + ' КАК Данные'),
                       'прав')
        denied('b.import_foreign_attachment', lambda: b.КИИ_ХранениеДиалогов.ДобавитьИсточник(foreign, structure(b, Диалог=first, Материал=material)), 'Диалог недоступен текущему пользователю')
        mixed = array(b, [structure(b, Диалог=foreign, Версия=1), structure(b, Диалог=first, Версия=1)])
        denied('b.mixed_delete_preserves_own', lambda: b.КИИ_ХранениеДиалогов.УдалитьДиалоги(mixed),
               'Диалог недоступен текущему пользователю')
        check('b.own_survives_mixed_delete', b.КИИ_ХранениеДиалогов.ДиалогДоступен(foreign))
        check('b.privilege_restored.mixed_delete', not b.ПривилегированныйРежим())
        check('a.not_modified_by_foreign_probes', api.Диалог(first).Черновик == expected_draft and api.СообщенияДиалога(first).Количество() == 2)
        result['probes_passed'] = True
        save()
    except Exception as error:
        result['error'] = str(error).replace('123456', '[test-password]')
        save()
    finally:
        api = foreign_api = base = a = b = viewer = own = saved = settings = payload = prepared = answer = connector = mixed = None
        clients.clear()
        gc.collect()
        try:
            suite.connect()
            owned = array(suite.base, [record['ib_uid'] for record in records.values()])
            rows = query(suite.base, 'ВЫБРАТЬ Диалоги.Диалог ИЗ РегистрСведений.КИИ_ДиалогиЧата КАК Диалоги ГДЕ Диалоги.Владелец В (&Владельцы)', Владельцы=owned)
            identities = [str(row.Диалог) for row in rows]
            require(not (set(record['ib_uid'] for record in records.values()) & {user['uid'] for user in suite.baseline['ib_users'].values()}), 'Cleanup owner existed before this suite')
            for identity in identities:
                for name in reversed(REGISTERS):
                    records_to_delete = getattr(suite.base.РегистрыСведений, name).СоздатьНаборЗаписей()
                    records_to_delete.Отбор.Диалог.Установить(identity)
                    records_to_delete.Записать()
                    records_to_delete = None
            rows = owned = None
            check('cleanup.exact_registers', register_snapshot(suite.base) == before)
            suite.cleanup()
            result['cleanup_complete'] = True
        except Exception as error:
            result['cleanup_error'] = str(error).replace('123456', '[test-password]')
        finally:
            suite.disconnect()
            lease.release()
        result['passed'] = result.get('probes_passed', False) and result['cleanup_complete']
        save()
    print(json.dumps({'passed': result['passed'], 'checks': len(result['checks']),
                      'cleanup_complete': result['cleanup_complete'], 'error': result.get('error'),
                      'cleanup_error': result.get('cleanup_error')}, ensure_ascii=False))
    return 0 if result['passed'] else 1


def main():
    """Use managed-client checks; restricted COM startup is not a valid BSP probe."""
    from run_saved_dialog_rights import main as run_native_rights
    return run_native_rights()


if __name__ == '__main__': raise SystemExit(main())

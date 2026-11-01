"""Run native YAxUnit storage checks under real restricted BSP profiles, without export."""
import argparse
import gc
import json
from pathlib import Path
import subprocess
import sys
import uuid

import bsp_test_users as actors
from check_saved_dialog_access import BASE_ROLES, Evidence, register_snapshot, remove_actor_dialogues
from edt_yaxunit import Mcp, edt_agent_provider, installed_artifacts
from verification_receipt import Receipt, require
from run_bsp_journal_rights import structure

MODULE = 'Тесты_КИИ_ХранениеДиалогов'
LIMITED_CASES = frozenset('''БинарныйФайлИсторииНеПересылаетсяНеявно
ВИсторииСохраняетсяТекстДляЧеловека
ВложенияИсторииУчитываютНастройки
ВыключенноеВложениеОстаетсяВЧерновике
ГрупповоеУдалениеОтклоняетПовторДиалога
ГрупповоеУдалениеПроверяетВсеВерсииДоЗаписи
ГрупповоеУдалениеСохраняетНаборПриАктивномЗапросе
ИзменениеМатериаловОтменяетСтарыйСнимок
ИсторияЧитаетсяПорциями
КонтекстОграниченнойРоли
НазваниеИзВопросаСохраняетИсходныйТекст
НазванияБеседОднострочные
НезавершенныйЗапросЗащищаетОтУдаления
НеизвестныйРезультатНеРазрешаетПовтор
НеизменныйЧерновикСохраняетВерсиюСнимка
ОдинАктивныйЗапросВБеседе
ОтветыДвухБеседНеСмешиваются
ОшибкаЗапросаСохраняетсяБезДублей
ПакетЗапросаНеМеняетсяСЧерновиком
ПовторныйИсточникНеДублируетКонтекст
ПрямоеЧтениеХранилищаЗапрещено
РазныеБеседыХранятСвоиЧерновики
РезультатСохраняетсяБезФормыИДублей
СвязанныйФайлЗащищаетИсходнуюБеседу
ТекстФайлаСохраняетсяВКонтекстеПродолжения
УдалениеОтклоняетУстаревшееПодтверждение
УдалениеСохраняетДругуюБеседу
УдаленнаяБеседаНеВозрождаетсяСЧерновиком
УстаревшаяВерсияНеЗатираетЧерновик
ФайлДоступенПослеПовторногоЧтения
ФайлДругойБеседыНеТребуетПовторнойЗагрузки
ЦитатаСохраняетсяВКонтекстеПродолжения
ЧужаяОперацияСохраняетВнешнююТранзакцию
ЧужиеОперацииОграниченнойРолиЗапрещены'''.splitlines())
# These tests prepare foreign rows or inspect raw registers as an administrator.
ADMIN_CASES = frozenset(['ИсполнительОбращаетсяКМоделиБезПривилегии',
    'ЧужаяБеседаИМатериалЗапрещены', 'КонтекстДругойБеседыСодержитСнимок',
    'УдалениеУбираетВсеДанныеБеседы', 'ГрупповоеУдалениеСохраняетНевыбраннуюБеседу',
    'ГрупповоеУдалениеНеОбходитЧужогоВладельца', 'ЧужаяБеседаЗащищенаОтУдаления'])
ROLE_PROBES = ['КонтекстОграниченнойРоли', 'ЧужиеОперацииОграниченнойРолиЗапрещены',
              'ПрямоеЧтениеХранилищаЗапрещено', 'ЧужаяОперацияСохраняетВнешнююТранзакцию']


def select_role_cases(plan):
    cases = [name for name in plan['tests'] if name.startswith(MODULE + '.')]
    require(len(cases) == len(set(cases)), 'Duplicate role selection')
    for name in cases:
        short = name.removeprefix(MODULE + '.')
        require(short in LIMITED_CASES or short in ADMIN_CASES, 'Unclassified role case: ' + name)
        require(plan['test_contexts'].get(name) == 'Сервер', 'Wrong role case context: ' + name)
    methods = [name for name in cases if name.removeprefix(MODULE + '.') in LIMITED_CASES]
    require(methods, 'No selected limited-role cases')
    return list(dict.fromkeys(methods + [MODULE + '.' + name for name in ROLE_PROBES]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--mcp-helper', type=Path, required=True)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--delivery-job', nargs=2, action='append', required=True, metavar=('EXTENSION', 'JOB'))
    options = parser.parse_args()
    plan = json.loads(options.plan.read_text(encoding='utf-8'))
    methods = select_role_cases(plan)
    options.output.mkdir(parents=True, exist_ok=False)
    actors.O = options.output
    evidence = Evidence(options.output)
    evidence.record('role-selection', {'tests': methods,
        'excluded_administrator_cases': [name for name in plan['tests']
            if name.startswith(MODULE + '.') and name.removeprefix(MODULE + '.') in ADMIN_CASES]})
    mcp = Mcp(options.mcp_helper, evidence)
    actors.C['_edt_agent_provider'] = edt_agent_provider(mcp, actors.C)
    result = {'passed': False, 'cleanup_complete': False, 'runs': []}
    suite = actors.Actors()
    records = {}
    before = None
    lease = actors.lease()
    try:
        parent = Receipt.begin(options.output / 'receipts', plan['roots'], actors.out['target'], methods)
        files = installed_artifacts(parent, actors.C, ['ИИКона', 'Тесты'])
        delivery = {}
        for name, job in options.delivery_job:
            status = mcp.call('update_infobase_status', {'job_id': job})
            require(status.get('state') == 'DONE', 'Delivery job has not completed')
            delivery[name] = json.loads(status['result'])
        parent.live_build('ИИКона_разработки', delivery, files)
        suite.connect()
        suite.baseline = suite.snapshot()
        evidence.record('baseline', suite.baseline)
        before = register_snapshot(suite.base)
        evidence.record('baseline-dialogues', before)
        for kind in ['a', 'b', 'viewer']:
            extra = ['КИИ_ОбщийЖурналЗапросовИИПросмотр'] if kind == 'viewer' else []
            records[kind] = suite.create(kind, BASE_ROLES + ['СохранениеДанныхПользователя'] + extra)
        identities = {kind: str(uuid.uuid4()) for kind in records}
        base = suite.base
        for kind, actor in records.items():
            entry = base.РегистрыСведений.КИИ_ДиалогиЧата.СоздатьМенеджерЗаписи()
            entry.Диалог = identities[kind]
            entry.Владелец = actor['ib_uid']
            entry.Заголовок = actors.PREFIX + '_' + kind
            entry.Версия = 1
            entry.Записать()
            foreign = 'b' if kind == 'a' else 'a'
            fixture = {'СвойВладелец': actor['ib_uid'], 'СвойДиалог': identities[kind],
                       'ЧужойДиалог': identities[foreign], 'Материал': str(uuid.uuid4()), 'Запрос': str(uuid.uuid4())}
            base.Тесты_КИИ_ПраваЖурнала.УстановитьФикстуру(actor['name'], structure(base, fixture))
        entry = base = None
        gc.collect()
        suite.disconnect()
        lease.release()
        lease = None
        for kind, actor in records.items():
            parent.unchanged()
            child = Receipt.begin(options.output / 'receipts', plan['roots'], actors.out['target'], methods)
            build = json.loads((parent.folder / 'build.json').read_text(encoding='utf-8'))
            child.record('build', {key: value for key, value in build.items() if key not in ['run_id', 'source_hash']})
            config = {key: value for key, value in actors.C.items() if not key.startswith('_')}
            config.update(run_mode='managed', user_provisioning='BSP', username=actor['name'], password='123456', expected_test_roles=actor['roles'])
            config_path = actors.PRIVATE.with_name(actors.PREFIX + '-' + kind + '-native.json')
            actors.atomic(config_path, config)
            print('Native role check', kind, len(methods), child.folder, flush=True)
            command = [sys.executable, '-X', 'utf8', str(Path(__file__).with_name('verified_yaxunit.py')),
                       '--run-folder', str(child.folder), '--base-config', str(config_path),
                       '--mcp-helper', str(options.mcp_helper), '--timeout', '150']
            with (child.folder / 'role-runner.log').open('wb') as log:
                process = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
            verified = child.folder / 'junit-verified.json'
            observation = {'actor': kind, 'folder': str(child.folder), 'exit_code': process.returncode,
                           'junit': json.loads(verified.read_text(encoding='utf-8')) if verified.exists() else None}
            result['runs'].append(observation)
            evidence.record('result', result)
            require(process.returncode == 0 and observation['junit']['passed'], 'Native limited-role tests failed; inspect saved JUnit/log')
        result['passed'] = True
    except Exception as error:
        result['error'] = str(error).replace('123456', '[test-password]')
    finally:
        try:
            if lease is None:
                lease = actors.lease()
            if suite.base is None:
                suite.connect()
            for actor in records.values():
                suite.base.Тесты_КИИ_ПраваЖурнала.УдалитьФикстуру(actor['name'])
            remove_actor_dialogues(suite, list(records.values()), before)
            suite.cleanup_generated_service_user()
            suite.cleanup()
            result['cleanup_complete'] = True
        except Exception as error:
            result['cleanup_error'] = str(error)
        finally:
            try:
                suite.disconnect()
            except Exception as error:
                result['disconnect_error'] = str(error)
            if lease is not None:
                lease.release()
            evidence.record('result', result)
    print(json.dumps({'passed': result['passed'], 'cleanup_complete': result['cleanup_complete'],
                      'error': result.get('error'), 'cleanup_error': result.get('cleanup_error')}, ensure_ascii=False))
    return 0 if result['passed'] and result['cleanup_complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

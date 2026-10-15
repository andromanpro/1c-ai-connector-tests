"""Sequential managed YAxUnit rights suite. BSP accounts, test-owned data only."""
from pathlib import Path
import argparse, json, sys, uuid, gc, subprocess, datetime
from verification_receipt import Receipt, require, digest
from verified_yaxunit import idle
import bsp_test_users as h

sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
MODULE = 'Тесты_КИИ_ПраваЖурнала'
TESTS = ['КонтекстОграниченногоПользователя', 'ЧтениеСвоейЗаписи',
         'ЧтениеЧужойИИсторическойЗаписи', 'ИзменениеСвоейЗаписи', 'УдалениеСвоейЗаписи',
         'ИзменениеЧужойЗаписиЗапрещено', 'УдалениеЧужойЗаписиЗапрещено',
         'СозданиеЧужойЗаписиЗапрещено', 'ПодменаВладельцаСвоейЗаписиЗапрещена',
         'ПодменаВладельцаПараметраЗапрещена', 'ПраваМетодовHTTPСоответствуютПрофилю',
         'АутентификацияMCPВПрофиле',
         'ОбычныйВызовМоделиЗаписываетВладельца']
BASE_ROLES = ['БазовыеПраваБСП', '_ДемоБазовыеПраваБСП', 'ЗапускТолстогоКлиента',
              'ЗапускТонкогоКлиента', 'ЗапускВнешнегоСоединения', 'СохранениеДанныхПользователя']


def structure(base, value):
    if isinstance(value, dict):
        result = base.NewObject('Структура')
        for name, item in value.items():
            result.Вставить(name, structure(base, item))
        return result
    if isinstance(value, list):
        result = base.NewObject('Массив')
        for item in value:
            result.Добавить(structure(base, item))
        return result
    return value


class Suite:
    def __init__(self, parent):
        self.parent = parent
        self.actors = h.Actors()
        self.lock = None
        self.records = {}
        self.settings_users = []
        self.preparation_attempted = False
        self.api_recovery = None
        self.api_changed = False
        self.out = {'prefix': h.PREFIX, 'target': parent.spec['target'], 'runs': {},
                    'passed': False, 'cleanup_complete': False}
        self.admin_name = h.C['username']

    def save(self):
        h.atomic(h.O / (h.PREFIX + '-rights.json'), self.out)

    def connect(self):
        self.lock = h.lease()
        self.actors.connect()

    def disconnect(self):
        try:
            self.actors.disconnect()
        finally:
            self.lock.release()
            self.lock = None

    def prepare_users(self):
        self.connect()
        self.actors.baseline = self.actors.snapshot()
        self.out['before'] = self.actors.baseline
        self.save()
        for kind, extra in [('a', ['КИИ_БазовыеПрава']), ('b', ['КИИ_БазовыеПрава']),
                            ('viewer', ['КИИ_БазовыеПрава', 'КИИ_ОбщийЖурналЗапросовИИПросмотр']),
                            ('diagnostic', ['КИИ_СерверMCPДиагностика'])]:
            self.records[kind] = self.actors.create(kind, BASE_ROLES + extra)
        owner = 'КИИ_СерверMCPПользовательAPI'
        secure = self.actors.base.ОбщегоНазначения.ПрочитатьДанныеИзБезопасногоХранилища(owner, None)
        self.api_recovery = {
            'username': str(getattr(self.actors.base.Константы, owner).Получить()),
            'secure_internal': str(self.actors.base.ЗначениеВСтрокуВнутр(secure))}
        secure = None
        h.private['mcp_auth_recovery'] = self.api_recovery
        h.save()
        require(json.loads(h.PRIVATE.read_text(encoding='utf-8'))['mcp_auth_recovery'] == self.api_recovery,
                'MCP credentials recovery was not persisted')
        api_username = 'DSH_API_' + h.PREFIX
        self.api_changed = True
        getattr(self.actors.base.Константы, owner).Установить(api_username)
        self.actors.base.ОбщегоНазначения.ЗаписатьДанныеВБезопасноеХранилище(owner, '123456', 'Пароль')
        ids = {kind: str(uuid.uuid4()) for kind in self.records}
        ids['legacy'] = str(uuid.uuid4())
        date_ms = int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000)
        model_uid = str(uuid.uuid4())
        settings = {'Режим': 'подготовка', 'Метка': h.PREFIX, 'ПользовательAPI': api_username,
                    'ИдентификаторМодели': model_uid, 'ДатаЗаписи': date_ms,
                    'Записи': [{'Идентификатор': ids[kind], 'Владелец': record['ib_uid']}
                               for kind, record in self.records.items()] +
                              [{'Идентификатор': ids['legacy'], 'Владелец': ''}],
                    'Испытуемые': [record['name'] for record in self.records.values()]}
        base = self.actors.base
        module = getattr(base, MODULE)
        require(module.ПрочитатьФикстуру(self.admin_name) is None,
                'Existing admin fixture must be reviewed, not overwritten')
        self.settings_users.append(self.admin_name)
        module.УстановитьФикстуру(self.admin_name, structure(base, settings))
        for kind, record in self.records.items():
            foreign = 'b' if kind == 'a' else 'a'
            fixture = {'Режим': kind, 'Метка': h.PREFIX, 'ПользовательAPI': api_username,
                       'ИдентификаторМодели': model_uid, 'ДатаЗаписи': date_ms,
                       'СвояЗапись': ids[kind], 'СвойВладелец': record['ib_uid'],
                       'ЧужаяЗапись': ids[foreign], 'ЧужойВладелец': self.records[foreign]['ib_uid'],
                       'ИсторическаяЗапись': ids['legacy'], 'НоваяЗапись': str(uuid.uuid4()),
                       'ОбщийПросмотр': kind == 'viewer',
                       'ЗаписьРазрешена': 'КИИ_БазовыеПрава' in record['roles'],
                       'ПрямоеЧтениеПараметра': 'КИИ_БазовыеПрава' in record['roles']}
            require(module.ПрочитатьФикстуру(record['name']) is None, 'Existing actor fixture')
            self.settings_users.append(record['name'])
            module.УстановитьФикстуру(record['name'], structure(base, fixture))
        self.out.update(actors=self.records, fixtures=settings)
        module = base = None
        gc.collect()
        self.save()
        self.disconnect()

    def run(self, label, kind, methods):
        self.parent.unchanged()
        require(self.lock is None and self.actors.base is None, 'Administrative COM still open')
        actor = self.records[kind] if kind else None
        config = dict(h.C)
        config.update(run_mode='managed', user_provisioning='BSP')
        if actor:
            config.update(username=actor['name'], password='123456', expected_test_roles=actor['roles'])
        receipt = Receipt.begin(self.parent.folder.parent, self.parent.spec['roots'],
                                self.parent.spec['target'], [MODULE + '.' + name for name in methods])
        build = json.loads((self.parent.folder / 'build.json').read_text(encoding='utf-8'))
        receipt.record('build', {k: v for k, v in build.items() if k not in ['run_id', 'source_hash']})
        receipt.record('inherited-build', {'parent_run': self.parent.spec['run_id'],
                                          'exact_live_sources_equal': True,
                                          'parent_build_sha256': digest((self.parent.folder / 'build.json').read_bytes())})
        receipt.record('bsp-actor', {'label': label, 'actor': actor,
                                    'data_preparation': 'separate administrative YAxUnit',
                                    'administrative_com_closed_before_client': True})
        config_path = h.PRIVATE.with_name(h.PREFIX + '-' + label + '-runner.json')
        h.atomic(config_path, config)
        self.out['runs'][label] = {'folder': str(receipt.folder), 'expected': len(methods), 'passed': False}
        self.save()
        print('Managed YAxUnit', label, receipt.folder, 'tests', len(methods), flush=True)
        result = subprocess.run([sys.executable, '-X', 'utf8',
                                 str(Path(__file__).with_name('verified_yaxunit.py')),
                                 '--run-folder', str(receipt.folder), '--base-config', str(config_path),
                                 '--timeout', '120'], capture_output=True)
        text = (result.stdout + result.stderr).decode('utf-8-sig', errors='replace').replace('123456', '[test-password]')
        (receipt.folder / 'bsp-rights-runner.log').write_text(text, encoding='utf-8')
        report = self.out['runs'][label]
        report['runner_exit_code'] = result.returncode
        if (receipt.folder / 'junit-verified.json').exists():
            report['junit'] = json.loads((receipt.folder / 'junit-verified.json').read_text(encoding='utf-8'))
            report['passed'] = report['junit']['passed']
        self.save()
        print(label, 'passed=', report['passed'], flush=True)
        return report['passed']

    def cleanup_users_and_settings(self):
        self.connect()
        base = self.actors.base
        module = getattr(base, MODULE)
        for username in self.settings_users:
            module.УдалитьФикстуру(username)
        module = base = None
        gc.collect()
        if self.api_changed:
            owner = 'КИИ_СерверMCPПользовательAPI'
            self.actors.base.ОбщегоНазначения.УдалитьДанныеИзБезопасногоХранилища(owner)
            original = self.actors.base.ЗначениеИзСтрокиВнутр(self.api_recovery['secure_internal'])
            if original is not None and original.Количество() > 0:
                self.actors.base.ОбщегоНазначения.ЗаписатьДанныеВБезопасноеХранилище(owner, original, None)
            original = None
            getattr(self.actors.base.Константы, owner).Установить(self.api_recovery['username'])
            secure = self.actors.base.ОбщегоНазначения.ПрочитатьДанныеИзБезопасногоХранилища(owner, None)
            require(str(self.actors.base.ЗначениеВСтрокуВнутр(secure)) == self.api_recovery['secure_internal'],
                    'MCP secure storage was not restored')
            secure = None
            self.api_changed = False
            self.out['mcp_auth_fixture_restored'] = True
        self.actors.cleanup_generated_service_user()
        self.actors.cleanup()
        self.out['after'] = h.out['after']
        self.out['cleanup_complete'] = h.out['cleanup_complete']
        self.save()
        self.disconnect()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-run', type=Path, required=True)
    parser.add_argument('--evidence-dir', type=Path)
    parser.add_argument('--http-only', action='store_true',
                        help='Run HTTP method-rights and authentication assertions for each BSP profile, with normal setup and cleanup.')
    options = parser.parse_args()
    if options.evidence_dir is not None:
        h.O = options.evidence_dir.resolve()
        h.O.mkdir(parents=True, exist_ok=True)
    suite = Suite(Receipt(options.build_run))
    suite.parent.unchanged()
    try:
        suite.prepare_users()
        suite.preparation_attempted = True
        if suite.run('prepare', None, ['ПодготовитьДанныеЖурнала']):
            for kind in ['a', 'b', 'viewer', 'diagnostic']:
                selected = (['ПраваМетодовHTTPСоответствуютПрофилю', 'АутентификацияMCPВПрофиле'] if options.http_only else
                            TESTS if 'КИИ_БазовыеПрава' in suite.records[kind]['roles'] else TESTS[:-1])
                suite.run(kind, kind, selected)
    except Exception as exc:
        suite.out['error'] = str(exc).replace('123456', '[test-password]')
        suite.save()
    finally:
        if suite.lock is not None:
            suite.disconnect()
        try:
            if suite.preparation_attempted:
                suite.run('data-cleanup', None, ['ОчиститьДанныеЖурнала'])
            suite.cleanup_users_and_settings()
        except Exception as exc:
            suite.out['cleanup_error'] = str(exc).replace('123456', '[test-password]')
            suite.save()
        finally:
            if suite.lock is not None:
                suite.disconnect()
    wanted = ['prepare', 'a', 'b', 'viewer', 'diagnostic', 'data-cleanup']
    suite.out['passed'] = (suite.out['cleanup_complete'] and
                           all(suite.out['runs'].get(name, {}).get('passed') for name in wanted))
    suite.save()
    print(json.dumps(suite.out['runs'], ensure_ascii=False, indent=2))
    print('All profile rights behavior proved:', suite.out['passed'], '; cleanup:', suite.out['cleanup_complete'])
    return 0 if suite.out['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

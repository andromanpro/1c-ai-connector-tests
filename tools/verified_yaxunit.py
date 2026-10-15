"""Run frozen server/managed-client tests; refuse a different base or CFE.

Usage: py verified_yaxunit.py --run-folder RECEIPT --base-config PRIVATE_JSON
The private JSON has connection, cluster, infobase, lease_key and
platform_bin. SQL sessions must be empty. No updates or forced termination.
"""
import argparse
import collections
import gc
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import time

from verification_receipt import Receipt, require, digest


def public_base(connection):
    fields = {k.lower(): v.strip('"') for k, v in re.findall(r'(\w+)\s*=\s*("[^"]*"|[^;]*)', connection)}
    if 'srvr' in fields and 'ref' in fields:
        return 'server:' + fields['srvr'].lower() + '/' + fields['ref'].lower()
    require('file' in fields, 'Unknown connection type')
    return 'file:' + str(Path(fields['file']).resolve()).replace('\\', '/').casefold()


def launch_argument(connection):
    fields = {k.lower(): v.strip('"') for k, v in re.findall(r'(\w+)\s*=\s*("[^"]*"|[^;]*)', connection)}
    public_base(connection)
    if 'srvr' in fields:
        return '/S' + fields['srvr'] + '\\' + fields['ref']
    return '/F' + str(Path(fields['file']).resolve())


def designer_authentication(connection):
    """Use the administrative connection credentials without printing them."""
    fields = {k.lower(): v.strip('"') for k, v in re.findall(r'(\w+)\s*=\s*("[^"]*"|[^;]*)', connection)}
    public_base(connection)
    if not fields.get('usr'):
        return []
    arguments = ['/N' + fields['usr']]
    if fields.get('pwd'):
        arguments.append('/P' + fields['pwd'])
    return arguments


def idle(config):
    from runtime_session_guard import check_sessions
    args = [str(Path(config['platform_bin']) / 'rac.exe'), 'session', 'list',
            '--cluster=' + config['cluster'], '--infobase=' + config['infobase'],
            config.get('rac_address', 'localhost:1545')]
    result = subprocess.run(args, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    require(result.returncode == 0, 'Cannot verify target sessions')
    state = check_sessions(result.stdout.decode('utf-8-sig'), config.get('disconnected_session_allowlist', []),
                           public_base(config['connection']))
    if state['evidenced_disconnected_sessions']:
        import psutil
        target = public_base(config['connection']).split('/', 1)[1].casefold()
        for process in psutil.process_iter(['pid', 'name']):
            if (process.info['name'] or '').casefold().startswith('1cv8'):
                try:
                    require(not any(target in arg.casefold() for arg in process.cmdline()),
                            'A live target client exists despite a disconnected session')
                except psutil.NoSuchProcess:
                    continue
    return state


def capture_runtime(receipt, config, stage):
    import win32com.client
    receipt.record('session-guard-' + stage + '-before', idle(config))
    folder = receipt.folder / ('installed-' + stage)
    folder.mkdir(exist_ok=False)
    connector = win32com.client.Dispatch('V83.COMConnector')
    base = connector.Connect(config['connection'])
    entry = None
    try:
        actual = public_base(str(base.СтрокаСоединенияИнформационнойБазы()))
        if config.get('username'):
            receipt.record('bsp-provisioning-' + stage, bsp_provisioning(base, config))
        build = json.loads((receipt.folder / 'build.json').read_text(encoding='utf-8'))
        extensions, dependencies = {}, {}
        for entry in base.РасширенияКонфигурации.Получить():
            name = str(entry.Имя)
            path = folder / (name + '.cfe')
            entry.ПолучитьДанные().Записать(str(path))
            item = {'file': str(path), 'active': bool(entry.Активно), 'version': str(entry.Версия)}
            if name in build['artifacts']:
                extensions[name] = item
            else:
                dependencies[name] = {'sha256': digest(path.read_bytes()), 'active': item['active'],
                                      'version': item['version']}
        dependencies['base'] = {'name': str(base.Метаданные.Имя), 'version': str(base.Метаданные.Версия)}
        if stage == 'after':
            before = json.loads((receipt.folder / 'dependencies-before.json').read_text(encoding='utf-8'))
            require(before['dependencies'] == dependencies, 'Base or dependency extensions changed')
        receipt.record('dependencies-' + stage, {'dependencies': dependencies})
        receipt.runtime(stage, actual, extensions)
    finally:
        entry = None
        base = None
        connector = None
        gc.collect()
    idle(config)


def bsp_provisioning(base, config):
    """Verify current catalog/group/profile links and actual native roles."""
    require(config.get('user_provisioning') == 'BSP', 'Named test users must be provisioned through BSP')
    reference = base.Пользователи.НайтиПоИмени(config['username'])
    require(reference is not None and not reference.Пустая(), 'No BSP catalog link for the test user')
    native = base.Пользователи.НайтиПоСсылке(reference)
    require(native is not None and str(native.Имя) == config['username'], 'BSP/native test user differs')
    query = base.NewObject('Запрос')
    query.Текст = ('ВЫБРАТЬ Состав.Ссылка, Состав.Ссылка.Профиль КАК Профиль '
                   'ИЗ Справочник.ГруппыДоступа.Пользователи КАК Состав '
                   'ГДЕ Состав.Пользователь = &Пользователь')
    query.УстановитьПараметр('Пользователь', reference)
    groups = query.Выполнить().Выгрузить()
    require(groups.Количество() > 0, 'No BSP access-group membership for the test user')
    links = []
    for row in groups:
        require(not row.Профиль.Пустая(), 'Test user group has no access profile')
        links.append({'group_uuid': str(base.XMLСтрока(row.Ссылка.УникальныйИдентификатор())),
                      'profile_uuid': str(base.XMLСтрока(row.Профиль.УникальныйИдентификатор()))})
    roles = sorted(str(role.Имя) for role in native.Роли)
    if config.get('expected_test_roles') is not None:
        require(roles == sorted(config['expected_test_roles']), 'Actual test-user roles differ from preparation')
    from yaxunit_startup_guard import require_startup_roles
    require_startup_roles(roles)
    return {'username': config['username'],
            'catalog_uuid': str(base.XMLСтрока(reference.УникальныйИдентификатор())),
            'native_uuid': str(base.XMLСтрока(native.УникальныйИдентификатор)),
            'groups': links, 'actual_roles': roles, 'verified_from_current_database': True}


def client_arguments(config, configuration, platform_log):
    require(config.get('run_mode', 'managed') == 'managed', 'Only managed application mode is authorized')
    auth_args = []
    if config.get('username'):
        require(config.get('user_provisioning') == 'BSP', 'Named test users must be provisioned through BSP')
        auth_args = ['/N' + config['username'], '/P' + config.get('password', '')]
    result = [str(Path(config['platform_bin']) / '1cv8.exe'), 'ENTERPRISE', launch_argument(config['connection']),
              *auth_args, '/RunModeManagedApplication',
              '/DisableStartupDialogs', '/DisableStartupMessages', '/Out', str(platform_log),
              '/C', 'RunUnitTests=' + str(configuration), '/WA-']
    require('/RunModeManagedApplication' in result and '/RunModeOrdinaryApplication' not in result,
            'Client arguments are not in the authorized managed mode')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-folder', type=Path, required=True)
    parser.add_argument('--base-config', type=Path, required=True)
    parser.add_argument('--timeout', type=int, default=600)
    options = parser.parse_args()
    require(options.timeout > 0, 'Timeout must be positive')
    receipt = Receipt(options.run_folder)
    config = json.loads(options.base_config.read_text(encoding='utf-8'))
    require(public_base(config['connection']) == receipt.spec['target'], 'Wrong configured base')
    # Reuse the established shared base lease, without rewriting runner source.
    spec = importlib.util.spec_from_file_location('base_runner', Path(__file__).with_name('run-query-rights-tests.py'))
    legacy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(legacy)
    lease = legacy.Lease(config['lease_key'])
    process = None
    try:
        capture_runtime(receipt, config, 'before')
        selection = receipt.spec['tests']
        cfg = receipt.folder / 'yaxunit.json'
        cfg.write_text(json.dumps({'filter': {'modules': sorted({x.split('.')[0] for x in selection}),
                                             'tests': selection},
                                  'reportFormat': 'jUnit', 'reportPath': str(receipt.folder / 'junit.xml'),
                                  'closeAfterTests': True, 'showReport': False,
                                  'logging': {'file': str(receipt.folder / 'yaxunit-debug.log'),
                                              'enable': True, 'console': False, 'level': 'debug'}},
                                 ensure_ascii=False, indent=2), encoding='utf-8')
        receipt.prepare_test(cfg)
        args = client_arguments(config, cfg, receipt.folder / 'platform.log')
        receipt.record('client-preflight', {'application_mode': 'managed',
                       'named_test_user': bool(config.get('username')),
                       'user_provisioning': config.get('user_provisioning', 'anonymous'),
                       'startup_command': 'RunUnitTests', 'close_after_tests': True})
        started = time.monotonic()
        close_requested = False
        initialization_error = None
        from qdrant_fixture import local_fixture
        from diagram_fixture import local_diagram_fixture
        from legacy_model_fixture import local_model_fixture
        with local_fixture(), local_diagram_fixture(), local_model_fixture() as events:
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = 0
            process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       creationflags=subprocess.CREATE_NO_WINDOW, startupinfo=startup)
            receipt.record('client-started', {'pid': process.pid})
            print('Run', receipt.spec['run_id'], 'PID', process.pid, 'tests', len(selection), flush=True)
            notice = started + 45
            while process.poll() is None:
                elapsed = time.monotonic() - started
                if initialization_error is None:
                    from yaxunit_startup_guard import startup_failure
                    platform_log = receipt.folder / 'platform.log'
                    if platform_log.exists():
                        initialization_error = startup_failure(platform_log.read_text(encoding='utf-8-sig', errors='replace'))
                    if initialization_error:
                        receipt.record('startup-failure', initialization_error)
                        print('YAxUnit initialization failed; tests did not start:',
                              initialization_error['kind'], flush=True)
                if (initialization_error is not None or elapsed > options.timeout) and not close_requested:
                    import win32gui
                    for hwnd in legacy.own_windows(process.pid):
                        win32gui.PostMessage(hwnd, 0x0010, 0, 0)
                    close_requested = True
                if time.monotonic() > notice:
                    print('Test client running:', round(elapsed), 's', flush=True)
                    notice = time.monotonic() + 45
                time.sleep(1)
        receipt.record('client-exited', {'pid': process.pid, 'exit_code': process.returncode,
                                        'elapsed_s': round(time.monotonic() - started, 1),
                                        'normal_close_requested': close_requested,
                                        'initialization_error': initialization_error is not None,
                                        'fixture_requests': len(events),
                                        'fixture_scenarios': dict(collections.Counter(e['scenario'] for e in events))})
        capture_runtime(receipt, config, 'after')
        result = receipt.junit(process.returncode, process.poll() is not None, close_requested)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    finally:
        # Keep ownership and lease if the caller is interrupted. Never leave a
        # running client behind and then let another updater enter the base.
        if process is not None and process.poll() is None:
            process.wait()
        lease.release()


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
    raise SystemExit(main())

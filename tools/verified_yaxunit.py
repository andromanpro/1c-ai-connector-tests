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


def wait_for_owned_client_cleanup(config, process, close_requested, timeout_s=90):
    """Recheck an empty stand after this client exited; never allow an unknown session."""
    require(process.poll() is not None, 'Owned client is still running')
    started = time.monotonic()
    deadline = started + timeout_s
    notice = started + 20
    while True:
        try:
            return idle(config)
        except Exception as error:
            if str(error) != 'Target has an unknown session' or time.monotonic() >= deadline:
                raise
            if time.monotonic() >= notice:
                print('Owned client exited; still requiring an empty target before readback', flush=True)
                notice = time.monotonic() + 20
            time.sleep(2)


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
            item = {'file': str(path), 'active': bool(entry.Активно), 'version': str(entry.Версия),
                    'safe_mode': entry.БезопасныйРежим}
            if name in build['artifacts']:
                extensions[name] = item
            else:
                dependencies[name] = {'sha256': digest(path.read_bytes()), 'active': item['active'],
                                      'version': item['version'], 'safe_mode': item['safe_mode']}
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


def registered_test_filter(selection):
    """Only module/method names go to YAxUnit; case labels stay in the receipt."""
    require(isinstance(selection, list) and selection, 'Empty test selection')
    require(all(isinstance(name, str) for name in selection), 'Invalid test selection')
    require(len(selection) == len(set(selection)), 'Duplicate expected test cases')
    methods = set()
    for case in selection:
        match = re.fullmatch(r'([^\W\d]\w*)\.([^\W\d]\w*)(?:\(.*\))?', case)
        require(match is not None, 'Invalid expected test case: ' + case)
        methods.add(match[1] + '.' + match[2])
    return {'modules': sorted({name.split('.')[0] for name in methods}), 'tests': sorted(methods)}


def fatal_client_log(folder, allow_busy=True, include_debug=False):
    from yaxunit_startup_guard import startup_failure
    # YAxUnit repeatedly opens its own log exclusively. A concurrent reader can
    # prevent the next write even when it allows sharing on its own handle.
    names = ('platform.log', 'yaxunit-debug.log') if include_debug else ('platform.log',)
    for name in names:
        path = folder / name
        if path.exists():
            try:
                raw = path.read_bytes()
            except PermissionError:
                if not allow_busy:
                    raise
                # The writer can hold an exclusive Windows handle between flushes.
                # Retry on the next poll; timeout and normal-close grace still apply.
                continue
            for encoding in ('utf-8-sig', 'cp1251'):
                result = startup_failure(raw.decode(encoding, errors='replace'))
                if result:
                    return dict(result, log=name)
    return None


def wait_for_client(process, folder, timeout_s, request_close, close_grace_s=30,
                    clock=time.monotonic, sleep=time.sleep):
    """Return attention after bounded normal-close grace, without killing the client."""
    started = clock()
    close_at = None
    close_windows = 0
    initialization_error = None
    failure_reason = None
    notice = started + 45
    while process.poll() is None:
        now = clock()
        if initialization_error is None:
            initialization_error = fatal_client_log(folder)
        if close_at is None and (initialization_error is not None or now - started >= timeout_s):
            failure_reason = initialization_error['kind'] if initialization_error else 'timeout'
            close_at = now
            close_windows = request_close(process.pid)
            print('Requested normal close of owned client:', failure_reason,
                  'windows:', close_windows, flush=True)
        if close_at is not None and now - close_at >= close_grace_s:
            return {'state': 'needs_attention', 'pid': process.pid, 'failure_reason': failure_reason,
                    'normal_close_requested': True, 'close_windows': close_windows,
                    'initialization_error': initialization_error, 'elapsed_s': round(now - started, 1)}
        if now >= notice:
            print('Test client running:', round(now - started), 's', flush=True)
            notice = now + 45
        sleep(1)
    initialization_error = initialization_error or fatal_client_log(folder, allow_busy=False, include_debug=True)
    return {'state': 'exited', 'pid': process.pid, 'exit_code': process.returncode,
            'elapsed_s': round(clock() - started, 1), 'normal_close_requested': close_at is not None,
            'close_windows': close_windows, 'initialization_error': initialization_error,
            'failure_reason': failure_reason or (initialization_error or {}).get('kind')}


def request_owned_close(legacy, pid):
    import win32gui
    windows = legacy.own_windows(pid)
    for hwnd in windows:
        win32gui.PostMessage(hwnd, 0x0010, 0, 0)
    return len(windows)


def retain_live_client(lease, receipt, process, reason):
    import psutil
    evidence = {'state': 'needs_attention', 'pid': process.pid,
                'process_created_at': psutil.Process(process.pid).create_time(),
                'run_folder': str(receipt.folder), 'target': receipt.spec['target'],
                'reason': reason, 'force_kill': False, 'recovery_required': True}
    lease.retain(evidence)
    if not (receipt.folder / 'client-needs-attention.json').exists():
        receipt.record('client-needs-attention', evidence)
    print('Client needs attention; base remains blocked for recovery:', process.pid, flush=True)


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
    selected_filter = registered_test_filter(receipt.spec['tests'])
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
        cfg.write_text(json.dumps({'filter': selected_filter,
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
        from expert_tools_fixture import local_expert_fixture
        from mcp_database_fixtures import local_database_fixture, require_clean_events, requires_database_fixture
        from dsml_fixture import local_reproduction_fixture, require_clean_dsml_events
        dsml_enabled = any(name.startswith("Тесты_КИИ_АгентАнализа.DSML_") for name in selection)
        database_enabled = requires_database_fixture(selection)
        with (local_fixture(), local_diagram_fixture(), local_model_fixture() as events,
              local_expert_fixture() as expert_events,
              local_database_fixture(enabled=database_enabled) as database_events,
              local_reproduction_fixture(receipt.folder, enabled=dsml_enabled) as dsml_events):
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = 0
            process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       creationflags=subprocess.CREATE_NO_WINDOW, startupinfo=startup)
            receipt.record('client-started', {'pid': process.pid})
            print('Run', receipt.spec['run_id'], 'PID', process.pid, 'tests', len(selection), flush=True)
            lifecycle = wait_for_client(process, receipt.folder, options.timeout,
                                        lambda pid: request_owned_close(legacy, pid))
            close_requested = lifecycle['normal_close_requested']
            initialization_error = lifecycle['initialization_error']
            if initialization_error:
                receipt.record('startup-failure', initialization_error)
            if lifecycle['state'] == 'needs_attention':
                retain_live_client(lease, receipt, process, lifecycle['failure_reason'])
                return 2
        (receipt.folder / 'expert-fixture-events.json').write_text(
            json.dumps(expert_events, ensure_ascii=False, indent=2), encoding='utf-8')
        expert_checks_passed = (not any('fixture_error' in event for event in expert_events)
                                and all(check['passed'] for event in expert_events for check in event.get('checks', [])))
        receipt.record('expert-fixture-result', {'requests': len(expert_events),
                       'scenarios': dict(collections.Counter(event['scenario'] for event in expert_events)),
                       'checks_passed': expert_checks_passed})
        (receipt.folder / 'database-fixture-events.json').write_text(
            json.dumps(database_events, ensure_ascii=False, indent=2), encoding='utf-8')
        receipt.record('database-fixture-result', {'requests': len(database_events),
                       'scenarios': dict(collections.Counter(event['scenario'] for event in database_events)),
                       'checks_passed': not any(event.get('fixture_error') for event in database_events)})
        receipt.record('client-exited', {'pid': process.pid, 'exit_code': process.returncode,
                                        'elapsed_s': round(time.monotonic() - started, 1),
                                        'normal_close_requested': close_requested,
                                        'initialization_error': initialization_error is not None,
                                        'fixture_requests': len(events),
                                        'fixture_scenarios': dict(collections.Counter(e['scenario'] for e in events))})
        # A failed client also needs server-session cleanup before readback. The exit
        # status and missing/failed JUnit are still rejected by receipt.junit below.
        receipt.record('owned-client-cleanup', wait_for_owned_client_cleanup(config, process, close_requested))
        capture_runtime(receipt, config, 'after')
        require(initialization_error is None, 'YAxUnit fatal startup error; run rejected')
        require(expert_checks_passed, 'Expert HTTP fixture checks failed')
        require_clean_events(database_events)
        require_clean_dsml_events(dsml_events)
        result = receipt.junit(process.returncode, process.poll() is not None, close_requested)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    finally:
        # A live child blocks later operations persistently, even if this runner exits.
        if process is not None and process.poll() is None:
            if not lease.block_path.exists():
                error = sys.exc_info()[1]
                reason = 'runner-error:' + type(error).__name__ if error is not None else 'runner-interrupted'
                retain_live_client(lease, receipt, process, reason)
        lease.release()


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
    raise SystemExit(main())

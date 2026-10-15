"""Local audited build/check entry points. No dynamic rewriting of older scripts."""
from pathlib import Path
import gc
import importlib.util
import json
import subprocess
import shutil
import sys
import uuid

sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
ROOT = Path(__file__).resolve().parent
TOOLS = Path('F:/temp/iikona-tests-github-public/tools')
sys.path.insert(0, str(TOOLS))
from verification_receipt import Receipt, require, exported_tree, compare_files, digest
from export_verified_sources import export
from verified_yaxunit import idle, public_base, launch_argument, designer_authentication

PROJECTS = {
    'ИИКона': {'project': 'F:/EDT_Workspace/ИИКона_разработки.ИИКона', 'source_label': 'product', 'dt_label': 'product_dt'},
    'Тесты': {'project': 'F:/EDT_Workspace/ИИКона_разработки.Тесты', 'source_label': 'tests', 'dt_label': 'tests_dt'},
}
PRIVATE = Path('F:/private/iikona-audit-20261013/base.json')
EDT = Path('C:/Program Files/1C/1CE/components/1c-edt-2025.2.3+30-x86_64/1cedtcli.exe')


def initialize():
    registration = ROOT.parent / 'Реализация_2026-10-06/iicona-debt-20261010/release-1.6.3-20261011/sql-stand-20261011/registered.json'
    old = json.loads(registration.read_text(encoding='utf-8'))
    config = {k: old[k] for k in ('connection', 'cluster', 'infobase')}
    config.update(platform_bin='C:/Program Files/1cv8/8.3.27.1989/bin',
                  lease_key='F:/temp/iicona-sql-stand-20261011/sql-operation-key')
    require(public_base(config['connection']) == 'server:localhost/iikona_perf_20261011', 'Wrong stand')
    PRIVATE.parent.mkdir(parents=True, exist_ok=True)
    with PRIVATE.open('x', encoding='utf-8') as stream:
        json.dump(config, stream, ensure_ascii=False, indent=2)
    print('Private SQL descriptor prepared; credentials not printed')


def begin():
    roots = {'verification_tools': str(TOOLS)}
    orchestration = Path('F:/temp/iikona-orchestrator-snapshots') / uuid.uuid4().hex
    orchestration.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(__file__, orchestration / 'pipeline.py')
    roots['verification_orchestrator'] = str(orchestration)
    for item in PROJECTS.values():
        roots[item['source_label']] = str(Path(item['project']) / 'src')
        roots[item['dt_label']] = str(Path(item['project']) / 'DT-INF')
    selected = json.loads((TOOLS / 'legacy-regression-selection.json').read_text(encoding='utf-8'))['included']
    for name in ('queue-regression-selection.json', 'rag-policy-regression-selection.json'):
        selected += json.loads((TOOLS / name).read_text(encoding='utf-8'))
    contexts = None
    if len(sys.argv) > 2:
        selection = json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'))
        if isinstance(selection, dict):
            require(set(selection) == {'tests', 'test_contexts'}, 'Invalid explicit test selection')
            selected = selection['tests']
            contexts = selection['test_contexts']
        else:
            selected = selection
    receipt = Receipt.begin(Path('F:/temp/iikona-audit-20261013/runs'), roots,
                            'server:localhost/iikona_perf_20261011', selected, test_contexts=contexts)
    (ROOT / 'active-run.txt').write_text(str(receipt.folder), encoding='utf-8')
    print('Frozen run:', receipt.folder, 'expected tests:', len(selected))


def current():
    receipt = Receipt((ROOT / 'active-run.txt').read_text(encoding='utf-8'))
    require(digest(Path(__file__).read_bytes()) ==
            receipt.spec['source_files']['verification_orchestrator/pipeline.py'],
            'Build orchestrator changed after source capture')
    return receipt


def export_current():
    print(json.dumps(export(current(), PROJECTS, EDT), ensure_ascii=False))


def capture():
    """Read-only round trip from an idle SQL database, before starting any test."""
    import win32com.client
    receipt = current()
    receipt.unchanged()
    config = json.loads(PRIVATE.read_text(encoding='utf-8'))
    sp = importlib.util.spec_from_file_location('lease', TOOLS / 'run-query-rights-tests.py')
    legacy = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(legacy)
    lease = legacy.Lease(config['lease_key'])
    base = connector = entry = None
    try:
        folder = receipt.folder / 'build-runtime'
        folder.mkdir(exist_ok=False)
        idle(config)
        connector = win32com.client.Dispatch('V83.COMConnector')
        base = connector.Connect(config['connection'])
        require(public_base(str(base.СтрокаСоединенияИнформационнойБазы())) == receipt.spec['target'], 'Wrong actual base')
        artifacts = {}
        for entry in base.РасширенияКонфигурации.Получить():
            name = str(entry.Имя)
            if name in PROJECTS:
                path = folder / (name + '.cfe')
                entry.ПолучитьДанные().Записать(str(path))
                artifacts[name] = path
        entry = base = connector = None
        gc.collect()
        idle(config)
        expected, actual = {}, {}
        for name in PROJECTS:
            target = folder / name
            log = folder / (name + '-dump.log')
            args = [str(Path(config['platform_bin']) / '1cv8.exe'), 'DESIGNER', launch_argument(config['connection']),
                    *designer_authentication(config['connection']),
                    '/DumpConfigToFiles', str(target), '-Extension', name, '/Out', str(log),
                    '/DisableStartupDialogs', '/DisableStartupMessages']
            print('Reading installed XML:', name, flush=True)
            process = subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     creationflags=subprocess.CREATE_NO_WINDOW)
            require(process.returncode == 0 and (target / 'Configuration.xml').exists(), 'Installed XML dump failed')
            expected[name] = receipt.folder / 'export' / name
            actual[name] = target
            idle(config)
        result = receipt.build(expected, actual, artifacts)
        print('Installed XML and CFE bound to run:', receipt.spec['run_id'], 'extensions:', list(result['artifacts']))
    finally:
        entry = base = connector = None
        gc.collect()
        lease.release()


def deploy():
    """Install the frozen export into the explicit isolated SQL test stand."""
    receipt = current()
    receipt.unchanged()
    require(receipt.spec['target'] == 'server:localhost/iikona_perf_20261011', 'Not the isolated stand')
    exported = json.loads((receipt.folder / 'edt-export.json').read_text(encoding='utf-8'))
    names = ['Тесты'] if len(sys.argv) > 2 and sys.argv[2] == 'tests' else list(PROJECTS)
    config = json.loads(PRIVATE.read_text(encoding='utf-8'))
    sp = importlib.util.spec_from_file_location('lease', TOOLS / 'run-query-rights-tests.py')
    legacy = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(legacy)
    lease = legacy.Lease(config['lease_key'])
    try:
        for name in names:
            xml = receipt.folder / 'export' / name
            from verification_receipt import tree_hash
            require(tree_hash(exported_tree(xml)) == exported['projects'][name]['xml_hash'], 'Export was modified')
            for action, operation in [('load', ['/LoadConfigFromFiles', str(xml), '-Extension', name]),
                                      ('apply', ['/UpdateDBCfg', '-Extension', name])]:
                receipt.unchanged()
                idle(config)
                log = receipt.folder / (name + '-' + action + '-' + uuid.uuid4().hex[:8] + '.log')
                print('Isolated SQL', name, action, flush=True)
                args = [str(Path(config['platform_bin']) / '1cv8.exe'), 'DESIGNER', launch_argument(config['connection']),
                        *designer_authentication(config['connection']),
                        *operation, '/Out', str(log), '/DisableStartupDialogs', '/DisableStartupMessages']
                result = subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                        creationflags=subprocess.CREATE_NO_WINDOW)
                text = log.read_text(encoding='utf-8-sig') if log.exists() else ''
                receipt.record('designer-result-' + name + '-' + action, {'extension': name, 'action': action,
                               'exit_code': result.returncode, 'log': str(log)})
                require(result.returncode == 0 and log.exists() and not any(x in text for x in ('Ошибка', 'неудач', 'не выполн')),
                        'Designer operation failed: ' + str(log))
                receipt.record('deployment-' + name + '-' + action, {'extension': name, 'action': action,
                               'xml_hash': exported['projects'][name]['xml_hash'], 'exit_code': result.returncode})
        idle(config)
    finally:
        lease.release()


def build():
    begin()
    export_current()
    deploy()
    capture()


if __name__ == '__main__':
    {'initialize': initialize, 'begin': begin, 'export': export_current, 'capture': capture,
     'deploy': deploy, 'build': build}[sys.argv[1]]()

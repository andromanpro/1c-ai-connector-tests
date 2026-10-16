from pathlib import Path
import sys, json, shutil, subprocess, collections, hashlib, uuid, xml.etree.ElementTree as ET
sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
T = Path('F:/temp/iikona-tests-github-public/tools')
sys.path.insert(0, str(T))
from verification_receipt import Receipt
R = Path('D:/home/Хобби/!ТекущиеПроекты/Проект тестирование/Исправления_аудита_2026-10-13')
O = R/'expert-tools/live-chat-20261016/logging'
target_label = sys.argv[1] if len(sys.argv)>1 else 'green2'
output_label = sys.argv[2] if len(sys.argv)>2 else 'full'
old = Receipt(Path((O/(target_label+'-run.txt')).read_text().strip()))
old.unchanged()
accepted = json.loads((old.folder/'junit-verified.json').read_text(encoding='utf-8'))
assert accepted['passed']
before = json.loads((old.folder/'runtime-before.json').read_text(encoding='utf-8'))
after = json.loads((old.folder/'runtime-after.json').read_text(encoding='utf-8'))
assert before['extensions'] == after['extensions']
selection = json.loads((O/'full-selection.json').read_text(encoding='utf-8'))
assert len(selection['tests']) == len(set(selection['tests'])) == 832
assert set(selection['test_contexts']) == set(selection['tests'])
assert collections.Counter(selection['test_contexts'].values()) == {'Сервер': 830, 'КлиентУправляемоеПриложение': 2}
orchestration = Path('F:/temp/iikona174-full-orchestrator')/uuid.uuid4().hex
orchestration.mkdir(parents=True, exist_ok=False)
shutil.copyfile(__file__, orchestration/'full.py')
roots = {**old.spec['roots'], 'full_test_orchestrator':str(orchestration)}
receipt = Receipt.begin(old.folder.parent, roots, old.spec['target'], selection['tests'], test_contexts=selection['test_contexts'])
assert all(receipt.spec['source_files'].get(k) == v for k,v in old.spec['source_files'].items())
assert set(receipt.spec['source_files'])-set(old.spec['source_files']) == {'full_test_orchestrator/full.py'}
assert receipt.spec['source_files']['full_test_orchestrator/full.py'] == hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
receipt.record('source-provenance', {'targeted_run':str(old.folder),'targeted_source_hash':old.spec['source_hash'],
                                    'same_product_tests_verifier_and_pipeline':True,
                                    'additional_frozen_file':'full_test_orchestrator/full.py'})
shutil.copytree(old.folder/'export', receipt.folder/'export')
export = json.loads((old.folder/'edt-export.json').read_text(encoding='utf-8'))
data = {k:v for k,v in export.items() if k not in ('run_id','source_hash')}
data['reused_from'] = str(old.folder)
for name, item in data['projects'].items():
    item['xml'] = str(receipt.folder/'export'/name)
receipt.record('edt-export', data)
expected = {n:receipt.folder/'export'/n for n in data['projects']}
actual = {n:old.folder/'build-runtime'/n for n in data['projects']}
artifacts = {n:old.folder/'build-runtime'/(n+'.cfe') for n in data['projects']}
build = receipt.build(expected, actual, artifacts)
old_build = json.loads((old.folder/'build.json').read_text(encoding='utf-8'))
assert build['artifacts'] == old_build['artifacts']
receipt.record('build-provenance', {'reused_from':str(old.folder),'same_source':True,'same_cfe':True,
                                  'runtime_after_verified':True,'no_rebuild_or_database_update':True})
(O/(output_label+'-run.txt')).write_text(str(receipt.folder), encoding='utf-8')
print('FULL832', receipt.folder, 'same product/tests/verifier and CFE as accepted5; full orchestrator additionally frozen', flush=True)
p = subprocess.run([sys.executable,'-X','utf8',str(T/'run_expert_tools_suite.py'),'--run-folder',str(receipt.folder),
                    '--base-config','F:/private/iikona-audit-20261013/base.json','--timeout','600'])
root = ET.parse(receipt.folder/'junit.xml').getroot()
cases = list(root.iter('testcase'))
failed = [c.attrib for c in cases if any(list(c.iter(tag)) for tag in ['failure','error','skipped'])]
events = json.loads((receipt.folder/'expert-fixture-events.json').read_text(encoding='utf-8'))
result = {'run':str(receipt.folder),'source_hash':receipt.spec['source_hash'],'same_cfe_as_targeted':True,
          'runner_exit':p.returncode,'total':len(cases),'failed':failed,
          'contexts':dict(collections.Counter(receipt.spec['test_contexts'].values())),
          'fixture_requests':len(events),'fixture_scenarios':dict(collections.Counter(x['scenario'] for x in events)),
          'fixture_checks_passed':all(c['passed'] for x in events for c in x.get('checks',[])) and not any('fixture_error' in x for x in events),
          'junit_sha256':hashlib.sha256((receipt.folder/'junit.xml').read_bytes()).hexdigest()}
(O/(output_label+'-independent.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
assert p.returncode == 0 and len(cases) == 832 and not failed and result['fixture_checks_passed']

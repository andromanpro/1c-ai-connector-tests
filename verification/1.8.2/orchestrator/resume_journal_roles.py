"""Resume known BSP actors; finish strict after-check only once the stand is idle."""
from pathlib import Path
import copy
import importlib.util
import json
import sys
import time
import xml.etree.ElementTree as ET

sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
TOOLS = Path('F:/temp/iikona-tests-github-public/tools')
sys.path.insert(0, str(TOOLS))
import run_bsp_journal_rights as journal
import bsp_test_users as h
from verified_yaxunit import idle, capture_runtime
from verification_receipt import Receipt, require, digest

ROOT = Path(__file__).parent
PREFIX = 'K09_bsp_9af26186ad'
ORIGINAL = ROOT/'roles-final/journal'/(PREFIX+'-rights.json')
RESUMED = ROOT/'roles-recovered/journal'
RESUMED.mkdir(parents=True, exist_ok=False)
old = json.loads(ORIGINAL.read_text(encoding='utf-8'))
private_path = Path('F:/private/iikona-audit-20261013/k09-probes')/(PREFIX+'.json')
private = json.loads(private_path.read_text(encoding='utf-8'))
require(private['target'] == old['target'] == 'server:localhost/iikona_perf_20261011', 'Wrong target')
require(private['prefix'] == PREFIX and len(private['objects']) == 12, 'Unexpected recovery objects')
parent = Receipt((ROOT/'active-run.txt').read_text(encoding='utf-8').strip())
parent.unchanged()


def wait_idle(config):
    start = time.monotonic()
    while True:
        try:
            result = idle(config)
            return {'elapsed_s': round(time.monotonic()-start, 1), 'strict_guard': result}
        except Exception as error:
            if str(error) != 'Target has an unknown session' or time.monotonic()-start > 180:
                raise
            if int(time.monotonic()-start) % 30 < 3:
                print('Waiting for a strict empty-session observation; no COM/client/update starts', flush=True)
            time.sleep(3)


def finish_after_guard(folder, config):
    receipt = Receipt(folder)
    receipt.unchanged()
    exited = json.loads((folder/'client-exited.json').read_text(encoding='utf-8'))
    require(exited['exit_code'] == 0 and not exited['normal_close_requested'], 'Client did not exit normally')
    root = ET.parse(folder/'junit.xml').getroot()
    require(not any(list(root.iter(tag)) for tag in ['failure','error','skipped']), 'Actual test failure cannot be accepted')
    barrier = wait_idle(config)
    if not (folder/'runtime-after.json').exists():
        capture_runtime(receipt, config, 'after')
    else:
        require(json.loads((folder/'runtime-after.json').read_text(encoding='utf-8'))['source_hash'] == parent.spec['source_hash'], 'Wrong after proof')
    require(receipt.spec['source_hash'] == parent.spec['source_hash'], 'Different source cut')
    result = receipt.junit(0, True, False)
    receipt.record('late-session-guard-validation', {'original_controller_exit_code':1,
                   'reason':'Immediate post-client guard rejected a session; subsequent unchanged strict guard accepted empty stand',
                   'guard_weakened':False, 'session_exception_added':False, 'wait':barrier,
                   'controller_sha256':digest(Path(__file__).read_bytes()), 'actual_junit_passed':True})
    return result


class ResumedSuite(journal.Suite):
    def run(self, label, kind, methods):
        wait_idle(h.C)
        passed = super().run(label, kind, methods)
        if passed:
            wait_idle(h.C)
            return True
        folder = Path(self.out['runs'][label]['folder'])
        text = (folder/'bsp-rights-runner.log').read_text(encoding='utf-8')
        require('Target has an unknown session' in text and (folder/'client-exited.json').exists(), 'Not the recognized post-client guard condition')
        config_path = h.PRIVATE.with_name(h.PREFIX+'-'+label+'-runner.json')
        config = json.loads(config_path.read_text(encoding='utf-8'))
        proof = finish_after_guard(folder, config)
        self.out['runs'][label].update(passed=True, junit=proof, strict_late_validation=True)
        self.save()
        print(label, 'accepted by unchanged guard and current CFE after drain; original controller failure preserved', flush=True)
        return True


h.PREFIX = PREFIX
h.PRIVATE = private_path
h.private = private
h.O = RESUMED
h.out.update(prefix=PREFIX, target=old['target'], actors=old['actors'], before=old['before'], cleanup_complete=False)
suite = ResumedSuite(parent)
suite.out = copy.deepcopy(old)
suite.out.pop('cleanup_error', None)
suite.out.update(resumed_from=str(ORIGINAL), original_report_sha256=digest(ORIGINAL.read_bytes()), cleanup_complete=False, passed=False)
suite.records = old['actors']
suite.settings_users = [h.C['username']] + [x['name'] for x in suite.records.values()]
suite.actors.baseline = old['before']
suite.actors.created = [(value['catalog'], uid) for uid,value in private['objects'].items()]
suite.api_recovery = private['mcp_auth_recovery']
suite.api_changed = True
suite.preparation_attempted = True
suite.save()
try:
    config = json.loads(h.PRIVATE.with_name(PREFIX+'-prepare-runner.json').read_text(encoding='utf-8'))
    prep = suite.out['runs']['prepare']
    prep['junit'] = finish_after_guard(Path(prep['folder']), config)
    prep.update(passed=True, strict_late_validation=True)
    suite.save()
    for kind in ['a','b','viewer','diagnostic']:
        selected = journal.TESTS if 'КИИ_БазовыеПрава' in suite.records[kind]['roles'] else journal.TESTS[:-1]
        require(suite.run(kind,kind,selected), 'Role failed: '+kind)
finally:
    if suite.lock is not None:
        suite.disconnect()
    if suite.run('data-cleanup',None,['ОчиститьДанныеЖурнала']):
        suite.cleanup_users_and_settings()
    else:
        raise RuntimeError('Data cleanup failed; users retained for explicit recovery')
    if suite.lock is not None:
        suite.disconnect()
suite.out['passed'] = suite.out['cleanup_complete'] and all(x['passed'] for x in suite.out['runs'].values())
suite.save()
require(suite.out['passed'], 'Recovered suite did not pass')
print('Recovered journal roles and original baseline restored', flush=True)

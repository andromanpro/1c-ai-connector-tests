"""Existing BSP suites, with strict read-only waiting for post-client background jobs."""
from pathlib import Path
import importlib
import json
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
ROOT = Path(__file__).parent
TOOLS = Path('F:/temp/iikona-tests-github-public/tools')
sys.path.insert(0, str(TOOLS))
import run_bsp_journal_rights as managed
import bsp_test_users as h
from verified_yaxunit import idle, capture_runtime
from verification_receipt import Receipt, require, digest


def wait_idle(config):
    start = time.monotonic()
    notice = 30
    while True:
        try:
            return {'elapsed_s': round(time.monotonic()-start,1), 'strict_guard': idle(config)}
        except Exception as error:
            if str(error) != 'Target has an unknown session' or time.monotonic()-start > 240:
                raise
            if time.monotonic()-start > notice:
                print('Background work still blocks strict idle guard; no next database operation',flush=True)
                notice += 30
            time.sleep(3)


original_run = managed.Suite.run


def guarded_run(self, label, kind, methods):
    wait_idle(h.C)
    passed = original_run(self,label,kind,methods)
    if passed:
        wait_idle(h.C)
        return True
    info = self.out['runs'][label]
    folder = Path(info['folder'])
    log = (folder/'bsp-rights-runner.log').read_text(encoding='utf-8')
    require('Target has an unknown session' in log and (folder/'client-exited.json').exists(), 'Not the recognized after-client guard condition')
    exited = json.loads((folder/'client-exited.json').read_text(encoding='utf-8'))
    require(exited['exit_code']==0 and not exited['normal_close_requested'], 'Client did not exit normally')
    xml = ET.parse(folder/'junit.xml').getroot()
    require(not any(list(xml.iter(tag)) for tag in ['failure','error','skipped']), 'Actual test failures are not accepted')
    config = json.loads(h.PRIVATE.with_name(h.PREFIX+'-'+label+'-runner.json').read_text(encoding='utf-8'))
    barrier = wait_idle(config)
    lease = h.lease()
    try:
        receipt = Receipt(folder)
        receipt.unchanged()
        require(receipt.spec['source_hash']==self.parent.spec['source_hash'],'Different source cut')
        if not (folder/'runtime-after.json').exists():
            capture_runtime(receipt,config,'after')
        else:
            require(json.loads((folder/'runtime-after.json').read_text(encoding='utf-8'))['source_hash']==self.parent.spec['source_hash'],'Wrong after proof')
        proof = receipt.junit(0,True,False)
        receipt.record('late-session-guard-validation',{'original_controller_exit_code':info['runner_exit_code'],
                       'reason':'Platform background job can outlive the managed test client',
                       'guard_weakened':False,'session_exception_added':False,'wait':barrier,
                       'controller_sha256':digest(Path(__file__).read_bytes()),'actual_junit_passed':True})
    finally:
        lease.release()
    info.update(junit=proof,passed=True,strict_late_validation=True)
    self.save()
    print(label,'post-check completed after strict idle; actual JUnit and CFE unchanged',flush=True)
    return True


managed.Suite.run = guarded_run
kind = sys.argv[1]
require(kind in ['monitoring','connections'],'Unsupported suite')
folder = ROOT/'roles-recovered'/kind
folder.mkdir(parents=True,exist_ok=False)
module = importlib.import_module('run_bsp_monitoring_rights' if kind=='monitoring' else 'run_connection_rights')
parent = (ROOT/'active-run.txt').read_text(encoding='utf-8').strip()
sys.argv = [str(TOOLS/module.__name__)+'.py','--build-run',parent,'--evidence-dir',str(folder)]
raise SystemExit(module.main())

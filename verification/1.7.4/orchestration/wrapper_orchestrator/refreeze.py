from pathlib import Path
import sys, json, hashlib, shutil, subprocess, uuid
sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
T=Path('F:/temp/iikona-tests-github-public/tools')
sys.path.insert(0,str(T))
from verification_receipt import Receipt
R=Path('D:/home/Хобби/!ТекущиеПроекты/Проект тестирование/Исправления_аудита_2026-10-13')
O=R/'expert-tools/live-chat-20261016/logging'
old=Receipt(Path((O/'final5-run.txt').read_text().strip()))
assert json.loads((old.folder/'junit-verified.json').read_text())['passed']
root=Path('F:/temp/iikona174-refreeze')/uuid.uuid4().hex
root.mkdir(parents=True,exist_ok=False);shutil.copyfile(__file__,root/'refreeze.py')
roots={**old.spec['roots'],'wrapper_orchestrator':str(root)}
new=Receipt.begin(old.folder.parent,roots,old.spec['target'],old.spec['tests'],test_contexts=old.spec['test_contexts'])
delta=[k for k in old.spec['source_files'] if old.spec['source_files'][k]!=new.spec['source_files'].get(k)]
assert delta==['verification_tools/run_expert_tools_suite.py'],delta
assert set(new.spec['source_files'])-set(old.spec['source_files'])=={'wrapper_orchestrator/refreeze.py'}
shutil.copytree(old.folder/'export',new.folder/'export')
shutil.copytree(old.folder/'build-runtime',new.folder/'build-runtime')
export=json.loads((old.folder/'edt-export.json').read_text(encoding='utf-8'))
data={k:v for k,v in export.items() if k not in ['run_id','source_hash']}
for n,item in data['projects'].items():item['xml']=str(new.folder/'export'/n)
data['reused_from']=str(old.folder);new.record('edt-export',data)
build=new.build({n:new.folder/'export'/n for n in data['projects']},
                {n:old.folder/'build-runtime'/n for n in data['projects']},
                {n:old.folder/'build-runtime'/(n+'.cfe') for n in data['projects']})
assert build['artifacts']==json.loads((old.folder/'build.json').read_text())['artifacts']
new.record('source-provenance',{'previous_run':str(old.folder),'same_product_and_tests':True,
 'same_cfe':True,'changed_verification_tool':delta,'additional_frozen_file':'wrapper_orchestrator/refreeze.py',
 'reason':'public wrapper delegates fixture ownership to verified_yaxunit; no duplicate listener'})
(O/'wrapped5-run.txt').write_text(str(new.folder),encoding='utf-8')
print('PUBLIC WRAPPER5',new.folder,flush=True)
subprocess.run([sys.executable,'-X','utf8',str(T/'run_expert_tools_suite.py'),'--run-folder',str(new.folder),
                '--base-config','F:/private/iikona-audit-20261013/base.json','--timeout','600'],check=True)
assert json.loads((new.folder/'junit-verified.json').read_text())['passed']
print('PUBLIC WRAPPER5 ACCEPTED',flush=True)

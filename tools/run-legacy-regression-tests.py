"""Explicit safe whitelist, owned client and base lease; local responses only."""
from pathlib import Path
import sys,importlib.util,re,json,collections
TOOLS=Path(__file__).resolve().parent;sys.path.insert(0,str(TOOLS))
from qdrant_fixture import local_fixture
from diagram_fixture import local_diagram_fixture
from legacy_model_fixture import local_model_fixture
O=Path(sys.argv[sys.argv.index('--output-root')+1]);O.mkdir(parents=True,exist_ok=True)
source=(TOOLS/'run-query-rights-tests.py').read_text(encoding='utf-8').split("if __name__=='__main__':")[0]
source=source.replace("'filter':{'modules':MODULES}","'filter':{'modules':MODULES,'tests':WHITELIST}")
ns={'__name__':'safe_legacy_runner'};exec(compile(source,__file__,'exec'),ns)
reviewed=json.loads((TOOLS/'legacy-regression-selection.json').read_text(encoding='utf-8'))
core_only='--core-only' in sys.argv
if core_only:sys.argv.remove('--core-only')
selection=[x for x in reviewed['included'] if not core_only or x.startswith('Тесты_КИИ_Ядро.')]
excluded=reviewed['excluded'];counts=dict(collections.Counter(x.split('.')[0] for x in selection))
ns.update(WHITELIST=selection,MODULES=list(counts),EXPECTED_MODULES=counts,EXPECTED=len(selection))
(O/('safe-selection-core.json' if core_only else 'safe-selection.json')).write_text(json.dumps({'included':selection,'count':len(selection),'modules':counts,'excluded':excluded,'client_separate':12,'no_paid_calls':True},ensure_ascii=False,indent=2),encoding='utf-8')
with local_fixture(),local_diagram_fixture(),local_model_fixture() as events:
    rc=ns['main']()
(O/('model-fixture-events-core.json' if core_only else 'model-fixture-events.json')).write_text(json.dumps(events,ensure_ascii=False,indent=2),encoding='utf-8')
print('Synthetic HTTP requests',len(events),'scenarios',dict(collections.Counter(e['scenario'] for e in events)))
raise SystemExit(rc)

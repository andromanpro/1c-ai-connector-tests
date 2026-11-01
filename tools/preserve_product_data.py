"""Read-only, full-field baseline before/after deployment and sequential suites."""
from pathlib import Path
import argparse
import gc
import json
import sys

sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
sys.path.insert(0, 'F:/temp/iikona-tests-github-public/tools')
import bsp_test_users as h
from verification_receipt import require, digest

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--private-output', type=Path, required=True)
parser.add_argument('--mcp-helper', type=Path, required=True)
parser.add_argument('mode', choices=['before', 'after'])
parser.add_argument('--label')
options = parser.parse_args()
O = options.output.resolve()
PRIVATE = options.private_output.resolve()
mode = options.mode
label = options.label or mode
require(label.replace('-', '').isalnum(), 'Invalid label')
O.mkdir(parents=True, exist_ok=True)
require(PRIVATE != O and O not in PRIVATE.parents, 'Private snapshots must be outside published output')
from check_saved_dialog_access import Evidence
from edt_yaxunit import Mcp, edt_agent_provider
transport = O / ('transport-' + label)
transport.mkdir(exist_ok=False)
h.C['_edt_agent_provider'] = edt_agent_provider(Mcp(options.mcp_helper, Evidence(transport)), h.C)
if mode == 'before':
    require(label == 'before', 'Initial baseline must use the before label')
    require(not (O/'preservation-before.json').exists(), 'Immutable baseline already exists')
    PRIVATE.mkdir(parents=True, exist_ok=True)
    require(not any(PRIVATE.iterdir()), 'A private baseline already exists')
actor = h.Actors()
lock = h.lease()
b = q = rows = md = child = row = model = key = None
try:
    actor.connect()
    b = actor.base
    if mode == 'before':
        plan = {}
        for md in b.Метаданные.Справочники:
            name = str(md.Имя)
            if name.startswith('КИИ_'):
                plan['Справочник.'+name] = ['Ссылка']
                for child in md.ТабличныеЧасти:
                    plan['Справочник.'+name+'.'+str(child.Имя)] = ['Ссылка', 'НомерСтроки']
        for md in b.Метаданные.РегистрыСведений:
            name = str(md.Имя)
            if name.startswith('КИИ_'):
                plan['РегистрСведений.'+name] = [str(x.Имя) for x in md.Измерения]
        queries = {}
        for table, order in plan.items():
            q = b.NewObject('Запрос', 'ВЫБРАТЬ Т.* ИЗ '+table+' КАК Т')
            rows = q.Выполнить().Выгрузить()
            columns = [str(x.Имя) for x in rows.Колонки]
            queries[table] = {'text': 'ВЫБРАТЬ '+', '.join('Т.'+x for x in columns)+' ИЗ '+table+' КАК Т',
                              'sort': ', '.join(order), 'columns': columns}
            q = rows = None
        h.atomic(O/'preservation-plan.json', queries)
    else:
        queries = json.loads((O/'preservation-plan.json').read_bytes())
    identity = actor.snapshot()
    result = {'target': 'server:localhost/iikona_perf_20261011', 'data': {}, 'constants': {},
              'users': identity['ib_users'], 'catalog_ids': identity['catalog_ids']}
    for table, query in queries.items():
        q = b.NewObject('Запрос', query['text'])
        rows = q.Выполнить().Выгрузить()
        if query['sort']:
            rows.Сортировать(query['sort'])
        raw = str(b.ЗначениеВСтрокуВнутр(rows)).encode('utf-8')
        result['data'][table] = {'count': int(rows.Количество()), 'sha256': digest(raw)}
        if mode == 'before':
            with (PRIVATE/(str(len(result['data'])).zfill(3)+'.serialized')).open('xb') as stream:
                stream.write(raw)
        q = rows = None
    for md in b.Метаданные.Константы:
        name = str(md.Имя)
        if name.startswith('КИИ_'):
            result['constants'][name] = digest(str(b.ЗначениеВСтрокуВнутр(getattr(b.Константы, name).Получить())).encode('utf-8'))
    q = b.NewObject('Запрос', 'ВЫБРАТЬ М.Ссылка ИЗ Справочник.КИИ_МоделиИИ КАК М')
    rows = q.Выполнить().Выгрузить()
    result['model_keys'] = {}
    for row in rows:
        model = row.Ссылка
        key = b.ОбщегоНазначения.ПрочитатьДанныеИзБезопасногоХранилища(model, 'APIКлюч')
        result['model_keys'][str(b.XMLСтрока(model.УникальныйИдентификатор()))] = digest(str(key).encode('utf-8'))
        key = model = None
    q = rows = row = None
    target = O/('preservation-'+label+'.json')
    require(not target.exists(), 'Do not replace an earlier observation')
    h.atomic(target, result)
    if mode == 'after':
        baseline = json.loads((O/'preservation-before.json').read_bytes())
        differences = {section: [k for k in set(result[section]) | set(baseline[section])
                                if result[section].get(k) != baseline[section].get(k)]
                       for section in ['data', 'constants', 'users', 'catalog_ids', 'model_keys']}
        h.atomic(O/('preservation-'+label+'-comparison.json'), {'passed': result == baseline,
                 'tables': len(queries), 'all_current_fields': True, 'differences': differences})
        require(result == baseline, 'Data/settings/users/keys differ; inspect comparison without exposing values')
    print(mode, label, 'captured', len(queries), 'tables, all current columns, constants/users/model keys', flush=True)
finally:
    key = model = row = child = md = q = rows = b = None
    gc.collect()
    actor.disconnect()
    lock.release()

"""Run the 180 original tests covering RAG, queue, monitoring and return contracts.

Use a separate file infobase with the delivered original product and tests.
The shared runner owns the base lease and closes only its own ordinary client.
"""
from pathlib import Path
import importlib.util,json,sys
from qdrant_fixture import local_fixture
from diagram_fixture import local_diagram_fixture

def main():
    spec=importlib.util.spec_from_file_location('original_runner',Path(__file__).with_name('run-query-rights-tests.py'))
    runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
    runner.EXPECTED_MODULES.update({'Тесты_КИИ_RAG':77,'Тесты_КИИ_КонтрактыВозврата':10})
    runner.MODULES=list(runner.EXPECTED_MODULES);runner.EXPECTED=sum(runner.EXPECTED_MODULES.values())
    assert runner.EXPECTED==180
    with local_fixture(),local_diagram_fixture() as events:result=runner.main()
    output_root=Path(sys.argv[sys.argv.index('--output-root')+1])
    (output_root/'diagram-fixture-events.json').write_text(json.dumps(events,ensure_ascii=False,indent=2),encoding='utf-8')
    return result

if __name__=='__main__':raise SystemExit(main())

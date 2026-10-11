"""Run the twelve managed-client form checks in the explicitly selected stand."""
from pathlib import Path

def main():
    source=Path(__file__).with_name('run-query-rights-tests.py').read_text(encoding='utf-8-sig')
    source=source[:source.index("if __name__=='__main__':")]
    source=source.replace("'/RunModeOrdinaryApplication',", "'/RunModeManagedApplication',")
    source=source.replace("'mode':'ordinary'", "'mode':'managed'")
    source=source.replace("{'Сервер':EXPECTED}", "{'КлиентУправляемоеПриложение':EXPECTED}")
    source=source.replace('Server suite started','Managed client suite started')
    namespace={'__name__':'client_runner','__file__':str(Path(__file__))}
    exec(compile(source,str(Path(__file__).with_name('run-query-rights-tests.py')),'exec'),namespace)
    namespace['MODULES']=['Тесты_КИИ_КопированиеКлиент']
    namespace['EXPECTED_MODULES']={'Тесты_КИИ_КопированиеКлиент':12}
    namespace['EXPECTED']=12
    return namespace['main']()

if __name__=='__main__':raise SystemExit(main())

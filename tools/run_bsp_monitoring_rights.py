"""Managed monitoring-settings permissions probes; BSP actors and exact recovery."""
from pathlib import Path
import argparse,gc,json,sys
from verification_receipt import Receipt,require
from run_bsp_journal_rights import Suite,BASE_ROLES,MODULE,structure
import bsp_test_users as h

OWNER='КИИ_МониторингОшибок'
CONSTANTS=['КИИ_МониторингОшибокНастройки','КИИ_МониторингОшибокМодельАнализа']
TESTS=['КонтекстПравНастроекМониторинга','ЧтениеНастроекTelegramОграниченоПравом',
       'МиграцияСекретовTelegramОграниченаПравом','ЗаписьТокенаTelegramОграниченаПравом',
       'ЗаписьЧатаTelegramОграниченаПравом','СохранениеНастроекМониторингаАтомарноПоПравам',
       'ПрямоеЧтениеСекретовTelegramНедоступно']


class MonitoringSuite(Suite):
    def __init__(self,parent,contexts):
        super().__init__(parent)
        self.recovery=None
        self.monitoring_changed=False
        self.contexts=contexts

    def prepare_users(self):
        self.connect()
        self.actors.baseline=self.actors.snapshot()
        self.out['before']=self.actors.baseline
        self.save()
        rolesets=[('a',['КИИ_БазовыеПрава']),('b',['КИИ_БазовыеПрава']),
                           ('viewer',['КИИ_БазовыеПрава','КИИ_ОбщийЖурналЗапросовИИПросмотр','КИИ_ДашбордОшибокПросмотр']),
                           ('diagnostic',['КИИ_СерверMCPДиагностика'])]
        rolesets += [('readonly',['КИИ_ПробаЧтенияМониторинга']),
                     ('monitor_admin',['КИИ_ПробаУправленияМониторингом']),
                     ('partial_admin',['КИИ_ПробаНеполногоУправленияМониторингом'])]
        for kind,extra in rolesets:
            if kind in self.contexts:self.records[kind]=self.actors.create(kind,BASE_ROLES+extra)
        base=self.actors.base
        secure=base.ОбщегоНазначения.ПрочитатьДанныеИзБезопасногоХранилища(OWNER,None)
        self.recovery={'secure_internal':str(base.ЗначениеВСтрокуВнутр(secure)),
                       'constants':{name:str(base.ЗначениеВСтрокуВнутр(getattr(base.Константы,name).Получить())) for name in CONSTANTS}}
        h.private['monitoring_recovery']=self.recovery
        h.save()
        require(json.loads(h.PRIVATE.read_text(encoding='utf-8'))['monitoring_recovery']==self.recovery,
                'Exact monitoring recovery was not persisted')
        seed={'ТокенТелеграм':'TG_TEST_'+h.PREFIX,'ChatIDТелеграм':'TG_CHAT_'+h.PREFIX}
        self.monitoring_changed=True
        base.ОбщегоНазначения.ЗаписатьДанныеВБезопасноеХранилище(OWNER,structure(base,seed),None)
        current=str(base.Константы.КИИ_МониторингОшибокНастройки.Получить())
        legacy=json.loads(current) if current else {}
        require(isinstance(legacy,dict),'Monitoring settings must be a JSON object')
        legacy.update(ТокенБотаТелеграм='LEGACY_'+seed['ТокенТелеграм'],ChatIDТелеграм='LEGACY_'+seed['ChatIDТелеграм'])
        base.Константы.КИИ_МониторингОшибокНастройки.Установить(json.dumps(legacy,ensure_ascii=False))
        check=base.ОбщегоНазначения.ПрочитатьДанныеИзБезопасногоХранилища(OWNER,None)
        require(str(check.ТокенТелеграм)==seed['ТокенТелеграм'] and str(check.ChatIDТелеграм)==seed['ChatIDТелеграм'],
                'Synthetic Telegram fixture not installed')
        check=secure=None
        module=getattr(base,MODULE)
        for kind,record in [('system_admin',None),*self.records.items()]:
            if kind not in self.contexts:continue
            name=record['name'] if record else self.admin_name
            settings={'Режим':kind,'Метка':h.PREFIX,'УправлениеМониторингом':kind in ['system_admin','monitor_admin','partial_admin'],
                      'СохранениеМониторинга':kind in ['system_admin','monitor_admin'],
                      'ЧтениеМониторинга':kind in ['system_admin','readonly','monitor_admin','partial_admin'],
                      'СистемныйАдминистратор':kind=='system_admin','ТокенTelegram':seed['ТокенТелеграм'],
                      'ЧатTelegram':seed['ChatIDТелеграм'],'НовыйТокенTelegram':'NEW_'+seed['ТокенТелеграм'],
                      'НовыйЧатTelegram':'NEW_'+seed['ChatIDТелеграм']}
            require(module.ПрочитатьФикстуру(name) is None,'Existing fixture must be reviewed')
            self.settings_users.append(name)
            module.УстановитьФикстуру(name,structure(base,settings))
        self.out.update(actors=self.records,synthetic_data_only=True,recovery_persisted=True,
                        fixture_parameters=['token','chat','allowed_operation','system_admin'])
        module=base=None
        gc.collect()
        self.save()
        self.disconnect()

    def cleanup_users_and_settings(self):
        self.connect()
        base=self.actors.base
        if self.monitoring_changed:
            require(not base.ТранзакцияАктивна(),'Unexpected open transaction before recovery')
            base.НачатьТранзакцию()
            try:
                base.ОбщегоНазначения.УдалитьДанныеИзБезопасногоХранилища(OWNER)
                original=base.ЗначениеИзСтрокиВнутр(self.recovery['secure_internal'])
                if original is not None and original.Количество()>0:
                    base.ОбщегоНазначения.ЗаписатьДанныеВБезопасноеХранилище(OWNER,original,None)
                original=None
                for name,value in self.recovery['constants'].items():
                    getattr(base.Константы,name).Установить(base.ЗначениеИзСтрокиВнутр(value))
                base.ЗафиксироватьТранзакцию()
            except Exception:
                base.ОтменитьТранзакцию()
                raise
            secure=base.ОбщегоНазначения.ПрочитатьДанныеИзБезопасногоХранилища(OWNER,None)
            require(str(base.ЗначениеВСтрокуВнутр(secure))==self.recovery['secure_internal'],'Monitoring secure owner differs')
            secure=None
            for name,value in self.recovery['constants'].items():
                require(str(base.ЗначениеВСтрокуВнутр(getattr(base.Константы,name).Получить()))==value,
                        'Monitoring constant differs after recovery')
            self.monitoring_changed=False
            self.out['exact_monitoring_recovery']=True
        module=getattr(base,MODULE)
        for name in self.settings_users:
            module.УдалитьФикстуру(name)
        module=base=None
        gc.collect()
        self.actors.cleanup_generated_service_user()
        self.actors.cleanup()
        self.out['after']=h.out['after']
        self.out['cleanup_complete']=h.out['cleanup_complete']
        self.save()
        self.disconnect()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-run',type=Path,required=True)
    parser.add_argument('--evidence-dir',type=Path,required=True)
    parser.add_argument('--contexts',default='system_admin,a,b,viewer,diagnostic',help='Optional readonly/monitor_admin/partial_admin require a separately frozen instrumented build with temporary probe roles; never ship them.')
    parser.add_argument('--without-product-admin',action='store_true',help='Legacy option; the product full role is never provisioned by this suite.')
    args=parser.parse_args()
    h.O=args.evidence_dir.resolve()
    h.O.mkdir(parents=True,exist_ok=True)
    wanted=args.contexts.split(',')
    require(len(wanted)==len(set(wanted)) and set(wanted)<=set(['system_admin','a','b','viewer','diagnostic','readonly','monitor_admin','partial_admin']),'Invalid contexts')
    suite=MonitoringSuite(Receipt(args.build_run),wanted)
    suite.parent.unchanged()
    try:
        suite.prepare_users()
        for label in wanted:
            suite.run(label,None if label=='system_admin' else label,TESTS)
    except Exception as exc:
        suite.out['error']=str(exc).replace('123456','[test-password]')
        suite.save()
    finally:
        if suite.lock is not None:suite.disconnect()
        try:suite.cleanup_users_and_settings()
        except Exception as exc:
            suite.out['cleanup_error']=str(exc).replace('123456','[test-password]')
            suite.save()
        finally:
            if suite.lock is not None:suite.disconnect()
    suite.out['passed']=suite.out['cleanup_complete'] and all(suite.out['runs'].get(k,{}).get('passed') for k in wanted)
    suite.save()
    print('Monitoring suite:',h.O/(h.PREFIX+'-rights.json'),'passed:',suite.out['passed'],
          'cleanup:',suite.out['cleanup_complete'],'exact recovery:',suite.out.get('exact_monitoring_recovery'))
    return 0 if suite.out['passed'] else 1


if __name__=='__main__':raise SystemExit(main())

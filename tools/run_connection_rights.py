"""Sequential managed YAxUnit for database connection RLS and BSP secrets."""
from pathlib import Path
import sys, json, uuid, gc
from verification_receipt import Receipt, require, digest
import bsp_test_users as h
import run_bsp_journal_rights as managed

sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
MODULE='Тесты_КИИ_ПраваПодключенийКБазам'
managed.MODULE=MODULE
TESTS=['КонтекстОграниченногоПользователя','ДоступныТолькоРазрешенныеБазы',
       'СостояниеНеВозвращаетПароль','ЧужоеПодключениеНедоступно',
       'СлужебныйПарольИзменятьЗапрещено','СозданиеПодключенияЗапрещено',
       'СобственныйЛичныйВходСохраняется','ЧужиеЛичныеРеквизитыСкрыты',
       'ЗаписьЧужогоЛичногоВходаЗапрещена','СохранениеЧужогоПодключенияЗапрещено',
       'ЛичныйВходУдаляется','СекретыЗакрытыПослеСохранения',
       'СлужебныйИнструментДоступен','ЛичныйИнструментДоступен',
       'ЧужойИнструментНедоступен','ОтозванноеПодключениеНедоступно']

class Suite(managed.Suite):
    def __init__(self,parent):
        super().__init__(parent)
        self.ids={};self.groups=[];self.fixtures={}
        self.out.update(controller_sha256=digest(Path(__file__).read_bytes()))

    def query(self,text,params=None):
        q=self.actors.base.NewObject('Запрос');q.Текст=text
        for name,value in (params or {}).items():q.УстановитьПараметр(name,value)
        return q.Выполнить().Выгрузить()

    def user(self,kind):
        return self.actors.base.Справочники.Пользователи.ПолучитьСсылку(self.actors.base.NewObject('УникальныйИдентификатор',self.records[kind]['catalog_uid']))

    def connection(self,uid):
        return self.actors.base.Справочники.КИИ_ПодключенияКБазам.ПолучитьСсылку(self.actors.base.NewObject('УникальныйИдентификатор',uid))

    def create_connection(self,kind,allowed,personal=False):
        base=self.actors.base;obj,ref,uid=self.actors.new_object('КИИ_ПодключенияКБазам',h.PREFIX+'_'+kind)
        self.ids[kind]=uid;self.out['connection_ids']=self.ids;self.save()
        obj.Адрес='http://127.0.0.1:8874/source-a/hs/iikona-mcp/connection'
        obj.Пользователь='reader-a';obj.Используется=True;obj.ЛичныйВход=personal;obj.Таймаут=10
        obj.ИдентификаторБазы='11111111-1111-1111-1111-111111111111'
        for participant in allowed:
            row=obj.Доступ.Добавить();row.Участник=participant;row=None
        obj.Записать();obj=None
        if not personal:base.КИИ_ПодключенияКБазам.СохранитьСлужебныйПароль(ref,'123456','Заменить')
        ref=base=None
        return uid

    def write_fixture(self,kind):
        module=getattr(self.actors.base,MODULE)
        module.УстановитьФикстуру(self.records[kind]['name'],managed.structure(self.actors.base,self.fixtures[kind]))
        module=None

    def prepare(self):
        self.connect();a=self.actors
        a.baseline=a.snapshot();h.out['before']=a.baseline;h.private['baseline']=a.baseline
        self.out['before']=a.baseline;h.save();self.save()
        require(self.query('ВЫБРАТЬ Ссылка ИЗ Справочник.КИИ_ПодключенияКБазам').Количество()==0,'Stand has existing connection settings')
        require(self.query('ВЫБРАТЬ Подключение ИЗ РегистрСведений.КИИ_ЛичныеПодключенияКБазам').Количество()==0,'Stand has existing personal settings')
        for kind in ['a','b']:self.records[kind]=a.create(kind,managed.BASE_ROLES+['КИИ_БазовыеПрава'])
        self.out['actors']=self.records;self.save()
        obj,ref,gid=a.new_object('ГруппыПользователей',h.PREFIX+'_allowed_group');self.groups.append(gid)
        obj.Состав.Добавить().Пользователь=self.user('a');obj.Записать();obj=None
        self.out['group_ids']=self.groups;self.save()
        direct=self.create_connection('direct_a',[self.user('a')])
        grouped=self.create_connection('group_a',[ref]);ref=None
        personal=self.create_connection('personal',[self.user('a'),self.user('b')],True)
        foreign=self.create_connection('direct_b',[self.user('b')])
        admin=a.base.Пользователи.ТекущийПользователь();admin_uid=str(a.base.XMLСтрока(admin.УникальныйИдентификатор()));admin=None
        # A foreign existing row is a positive control for each limited reader.
        a.base.КИИ_ПодключенияКБазам.СохранитьЛичныйВход(self.connection(personal),'foreign-admin-login','123456','Заменить')
        for kind in ['a','b']:
            self.fixtures[kind]={'Метка':h.PREFIX,'СвойПользователь':self.records[kind]['catalog_uid'],
                                'ЧужойПользователь':admin_uid,'Личная':personal,
                                'Служебная':direct if kind=='a' else foreign,
                                'Чужая':foreign if kind=='a' else direct,
                                'Отозванная':foreign if kind=='a' else direct,
                                'Видимые':sorted([direct,grouped,personal] if kind=='a' else [personal,foreign])}
            self.settings_users.append(self.records[kind]['name']);self.write_fixture(kind)
        self.out['fixtures']=self.fixtures;self.save();self.disconnect()

    def verify_persistent_a(self):
        self.connect();a=self.actors
        rows=self.query('ВЫБРАТЬ Пользователь,Логин ИЗ РегистрСведений.КИИ_ЛичныеПодключенияКБазам ГДЕ Подключение=&Подключение',{'Подключение':self.connection(self.ids['personal'])})
        require(rows.Количество()==2,'Expected only admin and A personal settings')
        found={str(a.base.XMLСтрока(row.Пользователь.УникальныйИдентификатор())):str(row.Логин) for row in rows};rows=None
        require(found.get(self.records['a']['catalog_uid'])=='reader-a','A login not preserved after independent managed session')
        require(self.records['b']['catalog_uid'] not in found,'B leaked a transaction or wrote persistent data')
        for kind in ['direct_a','group_a','direct_b']:
            require(a.base.ОбщегоНазначения.ПрочитатьДанныеИзБезопасногоХранилища(self.connection(self.ids[kind]))=='123456','Denied service password change escaped rollback')
        self.out['persistent_a_and_service_secrets_verified']=True;self.save();self.disconnect()

    def revoke(self,kind):
        self.connect();a=self.actors
        if kind=='direct':
            obj=self.connection(self.ids['direct_a']).ПолучитьОбъект();obj.Доступ.Очистить();obj.Записать();obj=None
            self.fixtures['a']['Видимые']=sorted([self.ids['group_a'],self.ids['personal']]);self.fixtures['a']['Отозванная']=self.ids['direct_a']
        else:
            ref=a.base.Справочники.ГруппыПользователей.ПолучитьСсылку(a.base.NewObject('УникальныйИдентификатор',self.groups[0]))
            obj=ref.ПолучитьОбъект();obj.Состав.Очистить();obj.Записать();obj=ref=None
            self.fixtures['a']['Видимые']=[self.ids['personal']];self.fixtures['a']['Отозванная']=self.ids['group_a']
        self.write_fixture('a');self.save();self.disconnect()

    def cleanup(self):
        self.connect();a=self.actors
        for username in self.settings_users:getattr(a.base,MODULE).УдалитьФикстуру(username)
        # Any unexpected object created by a broken denial test is still scoped by tag.
        rows=self.query('ВЫБРАТЬ Ссылка,Наименование ИЗ Справочник.КИИ_ПодключенияКБазам')
        refs=[(str(a.base.XMLСтрока(row.Ссылка.УникальныйИдентификатор())),str(row.Наименование)) for row in rows];rows=None
        for uid,name in refs:
            require(name.startswith(h.PREFIX),'Foreign connection encountered during cleanup')
            obj=self.connection(uid).ПолучитьОбъект();obj.Удалить();obj=None
        require(self.query('ВЫБРАТЬ Подключение ИЗ РегистрСведений.КИИ_ЛичныеПодключенияКБазам').Количество()==0,'Personal settings not removed')
        for gid in self.groups:
            ref=a.base.Справочники.ГруппыПользователей.ПолучитьСсылку(a.base.NewObject('УникальныйИдентификатор',gid));obj=ref.ПолучитьОбъект()
            require(str(obj.Наименование).startswith(h.PREFIX),'Group cleanup escaped prefix');obj.Удалить();obj=ref=None
        a.cleanup_generated_service_user();a.cleanup();self.out['after']=h.out['after'];self.out['cleanup_complete']=h.out['cleanup_complete'];self.save();self.disconnect()

def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--build-run',type=Path,required=True);parser.add_argument('--evidence-dir',type=Path,required=True)
    args=parser.parse_args();h.O=args.evidence_dir;h.O.mkdir(exist_ok=True,parents=True)
    h.PREFIX='MB_YAX_'+uuid.uuid4().hex[:10];h.PRIVATE=Path('F:/private/iikona-audit-20261013')/(h.PREFIX+'.json')
    h.out['prefix']=h.PREFIX;h.private['prefix']=h.PREFIX
    suite=Suite(Receipt(args.build_run));suite.parent.unchanged()
    expected=['a','persist-a','b','return-a','revoked-direct','revoked-group']
    try:
        suite.prepare()
        require(suite.run('a','a',TESTS),'A profile failed')
        require(suite.run('persist-a','a',['СохранитьЛичныйВходДляДругогоСеанса']),'A persistence failed')
        require(suite.run('b','b',TESTS),'B profile failed')
        suite.verify_persistent_a()
        require(suite.run('return-a','a',['КонтекстОграниченногоПользователя','СохраненныйЛичныйВходИзолирован']),'A return failed')
        for kind in ['direct','group']:
            suite.revoke(kind)
            require(suite.run('revoked-'+kind,'a',['КонтекстОграниченногоПользователя','ДоступныТолькоРазрешенныеБазы','ОтозванноеПодключениеНедоступно']),'Revocation failed: '+kind)
    except Exception as exc:
        suite.out['error']=str(exc).replace('123456','[test-password]');suite.save();print('Profile failure:',suite.out['error'])
    finally:
        if suite.lock is not None:suite.disconnect()
        try:
            if suite.actors.baseline is not None:suite.cleanup()
        except Exception as exc:
            suite.out['cleanup_error']=str(exc).replace('123456','[test-password]');suite.save();print('Cleanup failure:',suite.out['cleanup_error'])
        finally:
            if suite.lock is not None:suite.disconnect()
    suite.parent.unchanged();suite.out['passed']=suite.out['cleanup_complete'] and all(suite.out['runs'].get(label,{}).get('passed') for label in expected);suite.save()
    print('Profile rights accepted:',suite.out['passed'],'cleanup:',suite.out['cleanup_complete'],'report:',h.O/(h.PREFIX+'-rights.json'))
    return 0 if suite.out['passed'] else 1

if __name__=='__main__':raise SystemExit(main())

"""BSP catalog/profile/group test actors; includes success and forced-error cleanup."""
from pathlib import Path
import json,sys,uuid,gc,datetime,importlib.util,os
sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
sys.path.insert(0,'F:/temp/iikona-tests-github-public/tools')
from verified_yaxunit import idle,public_base
from verification_receipt import require,digest
import win32com.client
C=json.loads(Path('F:/private/iikona-audit-20261013/base.json').read_text(encoding='utf-8'))
O=Path('D:/home/Хобби/!ТекущиеПроекты/Проект тестирование/Исправления_аудита_2026-10-13/k09-resume')
PREFIX='K09_bsp_'+uuid.uuid4().hex[:10]
PRIVATE=Path('F:/private/iikona-audit-20261013/k09-probes')/(PREFIX+'.json')
out={'target':'server:localhost/iikona_perf_20261011','prefix':PREFIX,'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'passed':False,'actors':{},'cleanup_complete':False}
private={'target':out['target'],'password':'123456','prefix':PREFIX,'names':{},'objects':{}}
def atomic(path,value):
    p=path.with_suffix('.tmp');p.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(p,path)
def save():atomic(O/(PREFIX+'.json'),out);atomic(PRIVATE,private)
def lease():
    sp=importlib.util.spec_from_file_location('lease','F:/temp/iikona-tests-github-public/tools/run-query-rights-tests.py');h=importlib.util.module_from_spec(sp);sp.loader.exec_module(h);return h.Lease(C['lease_key'])
class Actors:
    def __init__(self):self.connector=self.base=None;self.created=[];self.baseline=None
    def connect(self):
        idle(C);self.connector=win32com.client.Dispatch('V83.COMConnector');self.base=self.connector.Connect(C['connection']);require(public_base(str(self.base.СтрокаСоединенияИнформационнойБазы()))==out['target'],'Wrong stand')
    def disconnect(self):self.base=self.connector=None;gc.collect();idle(C)
    def snapshot(self):
        b=self.base;result={}
        for kind,text in [('models','ВЫБРАТЬ М.* ИЗ Справочник.КИИ_МоделиИИ КАК М УПОРЯДОЧИТЬ ПО М.Ссылка'),('logs','ВЫБРАТЬ Л.* ИЗ РегистрСведений.КИИ_ЛогЗапросовИИ КАК Л УПОРЯДОЧИТЬ ПО Л.УниверсальнаяДатаВМиллисекундах, Л.Идентификатор')]:
            q=b.NewObject('Запрос');q.Текст=text;t=q.Выполнить().Выгрузить();result[kind]={'count':t.Количество(),'sha256':digest(str(b.ЗначениеВСтрокуВнутр(t)).encode('utf-8'))};q=t=None
        result['constants']={str(i.Имя):digest(str(b.ЗначениеВСтрокуВнутр(getattr(b.Константы,str(i.Имя)).Получить())).encode('utf-8')) for i in b.Метаданные.Константы if str(i.Имя).startswith('КИИ_')}
        result['catalog_ids']={}
        for kind in ['Пользователи','ГруппыДоступа','ПрофилиГруппДоступа']:
            q=b.NewObject('Запрос');q.Текст='ВЫБРАТЬ П.Ссылка ИЗ Справочник.'+kind+' КАК П';t=q.Выполнить().Выгрузить();result['catalog_ids'][kind]=sorted(str(b.XMLСтрока(x.Ссылка.УникальныйИдентификатор())) for x in t);q=t=None
        result['ib_users']={str(u.Имя):{'uid':str(b.XMLСтрока(u.УникальныйИдентификатор)),'roles':sorted(str(r.Имя) for r in u.Роли)} for u in b.ПользователиИнформационнойБазы.ПолучитьПользователей()}
        return result
    def new_object(self,catalog,name):
        b=self.base;manager=getattr(b.Справочники,catalog);identifier=uuid.uuid4().hex;uid=str(uuid.UUID(identifier));ref=manager.ПолучитьСсылку(b.NewObject('УникальныйИдентификатор',uid));obj=manager.СоздатьЭлемент();obj.УстановитьСсылкуНового(ref);obj.Наименование=name
        self.created.append((catalog,uid));private['objects'][uid]={'catalog':catalog,'name':name};save();return obj,ref,uid
    def create(self,kind,roles,*,allow_product_admin=False):
        b=self.base;name=PREFIX+'_'+kind;private['names'][kind]=name;save()
        profile,profile_ref,profile_uid=self.new_object('ПрофилиГруппДоступа',name+'_profile')
        for role in roles:profile.Роли.Добавить().Роль=b.ОбщегоНазначения.ИдентификаторОбъектаМетаданных('Роль.'+role)
        profile.Записать();profile=None
        user,user_ref,user_uid=self.new_object('Пользователи',name)
        description=b.Пользователи.НовоеОписаниеПользователяИБ();description.Вставить('Действие','Записать');description.Вставить('Имя',name);description.Вставить('ПолноеИмя',name);description.Вставить('АутентификацияСтандартная',True);description.Вставить('Пароль','123456');description.Вставить('РежимЗапуска','УправляемоеПриложение')
        user.ДополнительныеСвойства.Вставить('ОписаниеПользователяИБ',description);user.Записать();user=description=None
        group,group_ref,group_uid=self.new_object('ГруппыДоступа',name+'_group');group.Профиль=profile_ref;group.Пользователи.Добавить().Пользователь=user_ref;group.Записать();group=None
        users=b.NewObject('Массив');users.Добавить(user_ref);b.УправлениеДоступом.ОбновитьРолиПользователей(users);users=None
        native=b.Пользователи.НайтиПоСсылке(user_ref);actual=sorted(str(r.Имя) for r in native.Роли);native_uid=str(b.XMLСтрока(native.УникальныйИдентификатор));native=None
        require(set(roles)<=set(actual),'Requested group roles were not applied: missing='+
                repr(sorted(set(roles)-set(actual)))+'; actual='+repr(actual))
        require(not {'ПолныеПрава','АдминистраторСистемы'}&set(actual),'Test actor received full base administrative rights')
        require(allow_product_admin is True or 'КИИ_ПолныеПрава' not in actual,
                'Limited actor received product administrative rights')
        require(not allow_product_admin or 'КИИ_ПолныеПрава' in roles,
                'Product administrator must be requested explicitly')
        record={'name':name,'ib_uid':native_uid,'catalog_uid':user_uid,'group_uid':group_uid,'profile_uid':profile_uid,'roles':actual,'requested_roles':roles,'creation':'Catalog.Пользователи + ОписаниеПользователяИБ','rights':'Catalog.ПрофилиГруппДоступа + Catalog.ГруппыДоступа + УправлениеДоступом.ОбновитьРолиПользователей'}
        out['actors'][kind]=record;save();return record
    def cleanup_generated_service_user(self):
        """Reconcile only the known inactive BSP service created by managed startup."""
        b=self.base;name='ОтправкаСерверныхОповещений'
        if name in self.baseline['ib_users']:return
        native=b.ПользователиИнформационнойБазы.НайтиПоИмени(name)
        if native is None:return
        require(not native.АутентификацияСтандартная and not native.АутентификацияОС and not list(native.Роли),'Unexpected authenticated/authorized service user')
        ref=b.Пользователи.НайтиПоИмени(name)
        require(str(b.XMLСтрока(ref.УникальныйИдентификатор()))=='ea3b6bcf-d6d8-11ee-886a-b06ebfbf08c7','Unexpected service catalog identity')
        native_uid=str(b.XMLСтрока(native.УникальныйИдентификатор))
        out['generated_service_user']={'name':name,'ib_uid':native_uid,'standard_auth':False,'os_auth':False,'roles':[]};save()
        # Keep the original service catalog element, reconcile through BSP only.
        b.Пользователи.УдалитьПользователяИБ(name);native=None
        obj=ref.ПолучитьОбъект();obj.Записать();obj=ref=None
    def cleanup(self):
        b=self.base
        # Groups first; then BSP user object deletion removes its native account;
        # profiles last. No administrative user or existing object is in this list.
        for catalog in ['ГруппыДоступа','Пользователи','ПрофилиГруппДоступа']:
            for kind,uid in self.created:
                if kind!=catalog:continue
                ref=getattr(b.Справочники,catalog).ПолучитьСсылку(b.NewObject('УникальныйИдентификатор',uid))
                q=b.NewObject('Запрос');q.Текст='ВЫБРАТЬ П.Ссылка ИЗ Справочник.'+catalog+' КАК П ГДЕ П.Ссылка = &Ссылка';q.УстановитьПараметр('Ссылка',ref)
                exists=not q.Выполнить().Пустой();q=None
                if not exists:ref=None;continue
                obj=ref.ПолучитьОбъект()
                require(str(obj.Наименование).startswith(PREFIX),'Cleanup escaped its owned object scope')
                obj.Удалить();obj=ref=None
        # If an object write failed after native account creation, the known ASCII
        # name is cleaned by the public BSP API, never native/SQL authentication edits.
        for name in private['names'].values():
            native=b.Пользователи.НайтиПоИмени(name)
            if native is not None:b.Пользователи.УдалитьПользователяИБ(name)
            native=None
        after=self.snapshot();out['after']=after;save();require(after==self.baseline,'BSP actor cleanup did not restore baseline');out['cleanup_complete']=True;save()

def main():
    a=Actors();lock=lease()
    try:
        a.connect();a.baseline=a.snapshot();out['before']=a.baseline;save()
        roles=['БазовыеПраваБСП','_ДемоБазовыеПраваБСП','ЗапускТолстогоКлиента','ЗапускТонкогоКлиента','ЗапускВнешнегоСоединения','КИИ_БазовыеПрава']
        a.create('lifecycle',roles)
        if len(sys.argv)>1 and sys.argv[1]=='error':raise RuntimeError('Intentional lifecycle cleanup probe')
        out['preparation_passed']=True
    except Exception as exc:out['error']=str(exc).replace('123456','[test-password]');save()
    finally:
        try:
            if a.base is None:a.connect()
            a.cleanup()
        except Exception as exc:out['cleanup_error']=str(exc).replace('123456','[test-password]');save()
        a.disconnect();lock.release()
    out['passed']=out['cleanup_complete'] and (out.get('preparation_passed') or out.get('error')=='Intentional lifecycle cleanup probe');save();print(json.dumps({k:out[k] for k in ['prefix','passed','preparation_passed','cleanup_complete','actors','error','cleanup_error'] if k in out},ensure_ascii=False,indent=2));return 0 if out['passed'] else 1
if __name__=='__main__':raise SystemExit(main())

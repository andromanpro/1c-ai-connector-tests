"""Owned synthetic records for native dialogue-form checks under limited BSP roles."""
import gc

from check_saved_dialog_access import REGISTERS, structure, array
from verification_receipt import require
from verified_yaxunit import public_base

TARGET = 'server:localhost/iikona_perf_20261011'


def validate_actor(config, actor, baseline):
    require(public_base(config['connection']) == TARGET, 'Wrong material-fixture stand')
    require(actor['name'].startswith('K09_bsp_') and actor['name'].endswith('_forms'),
            'Material fixtures require an owned disposable forms actor')
    require(actor['ib_uid'] not in {user['uid'] for user in baseline['ib_users'].values()},
            'Material-fixture actor existed before the probe')
    require(actor['name'] not in baseline['ib_users'], 'Material-fixture actor name existed before the probe')
    require(not {'ПолныеПрава', 'АдминистраторСистемы', 'КИИ_ПолныеПрава'} & set(actor['roles']),
            'Material forms must be checked under limited roles')


class MaterialFixtures:
    def __init__(self, config, actor, baseline, evidence):
        validate_actor(config, actor, baseline)
        self.config, self.actor, self.evidence = config, actor, evidence
        self.connector = self.base = self.api = None
        self.owned = {}

    def __enter__(self):
        import win32com.client
        try:
            self.connector = win32com.client.Dispatch('V83.COMConnector')
            self.base = self.connector.Connect(self.config['connection'])
            require(public_base(str(self.base.СтрокаСоединенияИнформационнойБазы())) == TARGET,
                    'Connected material-fixture stand differs')
            require(bool(self.base.РольДоступна('ПолныеПрава')), 'Fixture setup needs the stand administrator')
            native = self.base.ПользователиИнформационнойБазы.НайтиПоИмени(self.actor['name'])
            require(native is not None and str(self.base.XMLСтрока(native.УникальныйИдентификатор)) == self.actor['ib_uid'],
                    'Material-fixture actor identity differs')
            native = None
            self.api = self.base.КИИ_ХранениеДиалогов
            self.administrator = str(self.base.XMLСтрока(
                self.base.ПользователиИнформационнойБазы.ТекущийПользователь().УникальныйИдентификатор))
            return self
        except Exception:
            self.__exit__()
            raise

    def __exit__(self, *error):
        self.api = self.base = self.connector = None
        gc.collect()

    def prepare(self, state):
        require(state in {'draft', 'accepted', 'error', 'completed'}, 'Unknown material fixture')
        b, api = self.base, self.api
        b.НачатьТранзакцию()
        try:
            dialogue = str(api.СоздатьДиалог(b.Справочники.КИИ_ЭкспертыИИ.ПустаяСсылка()))
            filename = 'UI-status-' + state + '.txt'
            description = structure(b, Имя=filename, MIME='text/plain')
            payload = b.ПолучитьДвоичныеДанныеИзСтроки('Synthetic material fixture', 'UTF-8', False)
            material = str(api.ДобавитьФайл(dialogue, description, payload))
            request = ''
            if state != 'draft':
                settings = b.КИИ_КонтекстДиалога.НастройкиПоУмолчанию()
                data = api.ДанныеДляОтправки(dialogue, structure(b, Вопрос='Synthetic material fixture'), settings)
                operation = structure(b, АдресПодготовки='', Диалог=dialogue)
                request = str(api.НачатьЗапрос(dialogue, data, operation))
                if state == 'error':
                    response = structure(b, ЭтоОшибка=True, ТекстОшибки='Synthetic provider error')
                    api.СохранитьИтогЗапроса(dialogue, request, structure(b, Ответ=response), '')
                elif state == 'completed':
                    response = structure(b, ЭтоОшибка=False, ТекстОтвета='Synthetic saved response',
                                         ВложенияОтвета=array(b, []))
                    api.СохранитьИтогЗапроса(dialogue, request, structure(b, Ответ=response), '')
            # All rows are created in this transaction. Hand them to the disposable
            # reader before commit, so native form reads use its real owner checks.
            for name in REGISTERS:
                rows = getattr(b.РегистрыСведений, name).СоздатьНаборЗаписей()
                rows.Отбор.Диалог.Установить(dialogue)
                rows.Прочитать()
                for row in rows:
                    require(str(row.Владелец) == self.administrator, 'Fixture creation escaped its owner')
                    row.Владелец = self.actor['ib_uid']
                rows.Записать()
                rows = row = None
            b.ЗафиксироватьТранзакцию()
        except Exception:
            b.ОтменитьТранзакцию()
            raise
        fixture = {'dialogue': dialogue, 'material': material, 'request': request, 'filename': filename}
        self.owned[dialogue] = request
        self.evidence.record('material-fixture-' + state, fixture)
        return fixture

    def change_pending_state(self, fixture, state):
        require(state in {'Выполняется', 'Результат неизвестен'}, 'Only pending fixture states may change')
        dialogue, request = fixture['dialogue'], fixture['request']
        require(bool(request) and self.owned.get(dialogue) == request, 'Unknown material fixture identity')
        b = self.base
        b.НачатьТранзакцию()
        try:
            saved_dialogue = b.РегистрыСведений.КИИ_ДиалогиЧата.СоздатьМенеджерЗаписи()
            saved_dialogue.Диалог = dialogue
            saved_dialogue.Прочитать()
            saved_request = b.РегистрыСведений.КИИ_ЗапросыЧата.СоздатьМенеджерЗаписи()
            saved_request.Диалог, saved_request.ЗапросЧата = dialogue, request
            saved_request.Прочитать()
            require(saved_dialogue.Выбран() and saved_request.Выбран(), 'Material-fixture records disappeared')
            require(str(saved_dialogue.Владелец) == str(saved_request.Владелец) == self.actor['ib_uid'],
                    'Material-fixture owner changed')
            require(str(saved_dialogue.АктивныйЗапрос) == request, 'Material fixture is no longer active')
            counters = (int(saved_dialogue.Версия), int(saved_dialogue.НомерСообщения))
            saved_request.Состояние = state
            saved_request.ТекстОшибки = 'Synthetic transport uncertainty' if state == 'Результат неизвестен' else ''
            saved_dialogue.Состояние = state
            saved_request.Записать()
            saved_dialogue.Записать()
            require(counters == (int(saved_dialogue.Версия), int(saved_dialogue.НомерСообщения)),
                    'Pending-state fixture altered the cache counters')
            b.ЗафиксироватьТранзакцию()
        except Exception:
            b.ОтменитьТранзакцию()
            raise
        self.evidence.record('material-transition-' + state, {'counters_unchanged': True, 'state': state})

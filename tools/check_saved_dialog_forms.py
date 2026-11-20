"""Exercise saved dialogue forms with a real limited BSP actor and Testpilot."""
import argparse
import gc
import json
import os
from pathlib import Path
import sys
import traceback
import time

os.environ['TC1C_SCREENSHOTS'] = 'true'
os.environ['TC1C_RESPONSE_FORMAT'] = 'json'
sys.path.insert(0, 'F:/WorkAI/tools/1c-testpilot/app')
from testpilot import Client, ActionError
import bsp_test_users as actors
from check_saved_dialog_access import (
    BASE_ROLES, Evidence, register_snapshot, remove_actor_dialogues,
)
from edt_yaxunit import Mcp, edt_agent_provider
from owned_forms_cleanup import cleanup as cleanup_owned_forms_session, failed_launch_result


def capture_screenshot(client):
    """Retry a read-only capture during a window transition, never the UI action."""
    for attempt in range(4):
        try:
            return client.get_screenshot()
        except ActionError as error:
            if error.code != 'screenshot_window_changed' or attempt == 3:
                raise
            time.sleep(0.2)


def exercise_application_exit(client, evidence):
    """Require graceful application exit while a real dialogue form is still open."""
    context = client.get_context(result_mode='full', include_tables=True)
    evidence.record('application-exit-before', context)
    assert context['form']['form_name'] == 'Обработка.КИИ_ТестИИ.Форма.Форма', 'Dialogue must remain open on exit'
    stopped = client.stop_client(graceful_timeout=30)
    evidence.record('application-exit-result', stopped)
    assert stopped.get('ok') is True and stopped.get('shutdown') == 'graceful', \
        'Application did not close gracefully with an open dialogue: ' + str(stopped)
    return {'dialogue_open_on_exit': True, 'shutdown': stopped['shutdown']}


def exercise_review_controls(client, options, evidence):
    """Choose and clear a real base value and inspect the moved command."""
    base_field = client.find_object(name='ФильтрБазаБесед')
    base_field.open_drop_list()
    choices = base_field.get_choice_list()
    evidence.record('review-base-choices', choices)
    assert choices.get('ok') and choices.get('presentations'), 'No base choices were presented'
    options.output.joinpath('base-drop-list.png').write_bytes(capture_screenshot(client).png)
    chosen = choices['presentations'][0]
    base_field.choose_from_drop_list(value=chosen)
    accepted = client.find_object(name='ФильтрБазаБесед').get_data_presentation()
    evidence.record('review-base-selected', accepted)
    assert accepted, 'The chosen base was not applied'
    client.find_object(name='ФильтрБазаБесед').clear()
    cleared = client.find_object(name='ФильтрБазаБесед').get_data_presentation()
    evidence.record('review-base-cleared', cleared)
    assert cleared == '', 'The base filter was not cleared'
    parent = client.find_object(name='КомандыПанелиБесед').info
    button = client.find_object(name='Очистить').info
    assert button['key'].startswith(parent['key'] + '.'), 'The new-dialogue command is outside the sidebar'
    options.output.joinpath('review-expanded.png').write_bytes(capture_screenshot(client).png)
    client.find_object(name='МоиДиалоги').click()
    options.output.joinpath('review-collapsed.png').write_bytes(capture_screenshot(client).png)
    hidden = client.find_object(name='ПанельБесед').is_visible()
    assert hidden.get('visible') is False
    client.find_object(name='МоиДиалоги').click()
    return {'base_choices': choices['presentations'], 'base_selected': True, 'base_cleared': True,
            'new_dialogue_in_sidebar': True, 'sidebar_hidden_and_restored': True}


def exercise_material_statuses(client, options, evidence, actor, baseline):
    """Verify limited-role native reads of explicitly owned synthetic request states."""
    from saved_dialog_form_fixtures import MaterialFixtures
    safe_mode = client.execute_code(context='server', code='Результат = БезопасныйРежим();')
    evidence.record('material-helper-safe-mode', safe_mode)

    def open_case(fixture):
        client.execute_code(context='client', parameters={
            'dialogue': fixture['dialogue'], 'scale': options.form_scale or 100}, code='''
Диалог = Параметры["dialogue"];
ПараметрыОткрытия = Новый Структура("Диалог", Диалог);
ОткрытьФорму("Обработка.КИИ_ТестИИ.Форма.Форма", ПараметрыОткрытия, , Диалог);
Форма = ПолучитьФорму("Обработка.КИИ_ТестИИ.Форма.Форма", ПараметрыОткрытия, , Диалог);
Форма.Масштаб = Параметры["scale"];
Результат = Истина;
''')
        client.find_object(name='ПоказатьМатериалы').click()

    def check(fixture, name, label, direction):
        client.find_object(name='ОбновитьБеседу').click()
        rows = client.find_object(name='ТаблицаВложений').read_rows(max_rows=10)
        evidence.record('material-' + name, rows)
        matches = [row for row in rows['rows'] if fixture['filename'] in row.values()]
        assert len(matches) == 1, ('The original file row is missing or duplicated', rows)
        assert matches[0].get('Направление') == direction, matches[0]
        assert matches[0].get('Состояние') == label, matches[0]

    with MaterialFixtures(actors.C, actor, baseline, evidence) as fixtures:
        draft = fixtures.prepare('draft')
        pending = fixtures.prepare('accepted')
        failed = fixtures.prepare('error')
        completed = fixtures.prepare('completed')
        open_case(draft)
        check(draft, 'draft', 'Отмечено для отправки', 'Исходящее')
        open_case(pending)
        check(pending, 'accepted', 'Запрос принят', 'Вопрос')
        fixtures.change_pending_state(pending, 'Выполняется')
        check(pending, 'processing', 'Запрос выполняется', 'Вопрос')
        fixtures.change_pending_state(pending, 'Результат неизвестен')
        check(pending, 'unknown', 'Результат неизвестен', 'Вопрос')
        open_case(completed)
        check(completed, 'completed', 'Запрос выполнен', 'Вопрос')
        open_case(failed)
        check(failed, 'error', 'Ошибка запроса', 'Вопрос')
        table = client.find_object(name='ТаблицаВложений')
        selected = table.goto_row(column='Файл', value=failed['filename'])
        assert selected.get('found') is True, 'The reusable material is absent'
        client.find_object(name='ПовторноИспользоватьМатериал').click()
        client.find_object(name='ОбновитьБеседу').click()
        repeated = client.find_object(name='ТаблицаВложений').read_rows(max_rows=10)
        evidence.record('material-repeat-copy', repeated)
        copies = [row for row in repeated['rows'] if failed['filename'] in row.values()]
        assert len(copies) == 2, ('Explicit reuse must create a separate next-question file', repeated)
        assert sorted(row['Состояние'] for row in copies) == sorted(['Ошибка запроса', 'Отмечено для отправки'])
        options.output.joinpath('material-statuses.png').write_bytes(capture_screenshot(client).png)
    return {'draft': True, 'accepted': True, 'processing': True, 'uncertain_with_same_counters': True,
            'failed': True, 'completed': True, 'explicit_reuse_preserved_previous_status': True,
            'provider_calls': 0}


def record_table_states(client, evidence, name):
    """Read table availability and edit modes without selecting or changing rows."""
    states = []
    for table in client.find_objects(cls='Table'):
        info = table.info
        target = {key: info.get(key) for key in ('key', 'handle', 'name', 'title')}
        reads = {}
        for action in ('is_visible', 'is_enabled', 'current_mode_is_edit'):
            reads[action] = client.call(action, key=info['key'], handle=info['handle'], check=False)
        states.append({'table': target, 'reads': reads})
    evidence.record(name, states)
    evidence.record(name + '-context', client.get_context(result_mode='full', include_tables=False))


def exercise_dialogue_deletion(client, options, evidence):
    """Exercise the native list command on the two dialogues owned by this actor."""
    def select(title):
        table = client.find_object(name='СписокБесед')
        table.goto_first_row()
        selected = table.goto_row(column='Беседа', value=title)
        assert selected.get('found') is True, ('Dialogue not found', selected)
        actual = table.get_cell_text(column='СписокБеседСписокБесед1')
        assert actual.get('text') == title, ('Selected dialogue differs', actual)

    def own_count():
        value = client.find_object(name='СписокБесед').read_rows(max_rows=10)
        rows = value['rows']
        assert isinstance(rows, list), ('Native list rows are unavailable', value)
        return len(rows)

    select('UI-dialogue-A')
    evidence.record('deletion-list', client.get_context(result_mode='full', include_tables=True))
    options.output.joinpath('deletion-list.png').write_bytes(capture_screenshot(client).png)
    assert own_count() == 2, 'Deletion probe requires exactly the actor-owned pair'
    client.find_object(name='УдалитьБеседы').click()
    options.output.joinpath('deletion-question.png').write_bytes(capture_screenshot(client).png)
    answer = client.answer_dialog(confirm=False, timeout=10)
    evidence.record('deletion-cancel', answer)
    assert answer.get('answered') == 'Нет' and 'UI-dialogue-A' in (answer.get('question') or '')
    assert own_count() == 2, 'Cancel must preserve both dialogues'
    after_cancel = client.get_context(result_mode='full', include_tables=True)
    evidence.record('deletion-after-cancel', after_cancel)
    assert after_cancel['form'].get('modified') is False, 'Cancel left the read-only list marked as unsaved'

    select('UI-dialogue-A')
    client.find_object(name='УдалитьБеседы').click()
    answer = client.answer_dialog(confirm=True, timeout=10)
    evidence.record('deletion-confirm-first', answer)
    assert answer.get('answered') == 'Да' and 'UI-dialogue-A' in (answer.get('question') or '')
    client.wait_until('Deleted first dialogue disappears', own_count, condition=lambda n: n == 1, timeout=15, interval=1)
    forms = client.find_objects(cls='ManagedForm', scope='application')
    evidence.record('deletion-open-forms-first', [form.info for form in forms])
    assert not any('UI-dialogue-A' in form.info.get('title', '') for form in forms), 'Deleted open dialogue remains on screen'

    # The shared workspace stays available after deleting its selected conversation.
    select('UI-dialogue-B')
    client.find_object(name='УдалитьБеседы').click()
    answer = client.answer_dialog(confirm=True, timeout=10)
    evidence.record('deletion-confirm-owner', answer)
    assert answer.get('answered') == 'Да' and 'UI-dialogue-B' in (answer.get('question') or '')
    record_table_states(client, evidence, 'deletion-owner-table-states')
    evidence.record('deletion-owner-returned', client.get_context(result_mode='full', include_tables=True))
    options.output.joinpath('deletion-owner-returned.png').write_bytes(capture_screenshot(client).png)
    client.wait_until('Deleted owner dialogue disappears', own_count, condition=lambda n: n == 0, timeout=15, interval=1)
    forms = client.find_objects(cls='ManagedForm', scope='application')
    evidence.record('deletion-open-forms-final', [form.info for form in forms])
    assert not any('UI-dialogue-' in form.info.get('title', '') for form in forms), 'Deleted dialogue window remains open'
    evidence.record('deletion-final', client.get_context(result_mode='full', include_tables=True))
    options.output.joinpath('deletion-final.png').write_bytes(capture_screenshot(client).png)
    return {'cancel_preserved_data': True, 'native_confirmations': 3,
            'both_owned_dialogues_deleted': True, 'workspace_survived_deletion': True}


def exercise_multiple_dialogue_deletion(client, options, evidence):
    """Delete the selected pair through one native confirmation, including cancel."""
    table = client.find_object(name='СписокБесед')
    before = table.read_rows(max_rows=10)
    assert len(before['rows']) == 2, 'The multi-delete fixture requires exactly its own pair'
    table.select_all_rows()
    selection = table.get_selected_rows()
    evidence.record('multi-selection', selection)
    assert len(selection['rows']) == 2, 'Two rows must actually be selected in the live table'
    options.output.joinpath('multi-selection.png').write_bytes(capture_screenshot(client).png)
    table = client.find_object(name='СписокБесед')
    table.select_all_rows()
    assert len(table.get_selected_rows()['rows']) == 2, 'Confirm must still apply to the selected pair'
    client.find_object(name='УдалитьБеседы').click()
    options.output.joinpath('multi-question.png').write_bytes(capture_screenshot(client).png)
    cancelled = client.answer_dialog(confirm=False, timeout=10)
    evidence.record('multi-cancel', cancelled)
    assert cancelled.get('answered') == 'Нет' and '(2)' in (cancelled.get('question') or '')
    after_cancel = client.get_context(result_mode='full', include_tables=True)
    evidence.record('multi-after-cancel', after_cancel)
    assert after_cancel['form'].get('modified') is False, 'Cancel must not mark the list as unsaved'
    assert len(client.find_object(name='СписокБесед').read_rows(max_rows=10)['rows']) == 2
    table = client.find_object(name='СписокБесед')
    table.select_all_rows()
    selection_after_cancel = table.get_selected_rows()
    evidence.record('multi-reselection', selection_after_cancel)
    assert len(selection_after_cancel['rows']) == 2, 'The second command must start with two selected rows'
    client.find_object(name='УдалитьБеседы').click()
    confirmed = client.answer_dialog(confirm=True, timeout=10)
    evidence.record('multi-confirm', confirmed)
    assert confirmed.get('answered') == 'Да' and '(2)' in (confirmed.get('question') or '')
    client.wait_until('The whole selected pair disappears',
        lambda: len(client.find_object(name='СписокБесед').read_rows(max_rows=10)['rows']),
        condition=lambda count: count == 0, timeout=15, interval=1)
    forms = client.find_objects(cls='ManagedForm', scope='application')
    evidence.record('multi-open-forms-final', [form.info for form in forms])
    assert not any('UI-dialogue-' in form.info.get('title', '') for form in forms)
    evidence.record('multi-final', client.get_context(result_mode='full', include_tables=True))
    options.output.joinpath('multi-final.png').write_bytes(capture_screenshot(client).png)
    return {'selected': 2, 'cancel_preserved_both': True,
            'one_confirmation_deleted_both': True, 'workspace_survived_deletion': True,
            'native_selection_committed': True}


def resize_owned_client(client, pid, width, height):
    import ctypes
    import psutil
    import win32con
    import win32gui
    import win32process
    process = psutil.Process(pid)
    assert process.ppid() == os.getpid() and process.name().lower() == '1cv8c.exe', 'Launched client process identity differs'
    windows = []
    def visit(hwnd, _):
        if (win32process.GetWindowThreadProcessId(hwnd)[1] == pid
                and win32gui.IsWindowVisible(hwnd) and not win32gui.GetWindow(hwnd, win32con.GW_OWNER)
                and win32gui.GetClassName(hwnd).startswith('V8TopLevelFrame')):
            windows.append(hwnd)
    isolated = getattr(client._connected_object(), '_isolated_process', None)
    assert isolated is not None and isolated.pid == pid and isolated.poll() is None, 'The client does not own this isolated process'
    assert isolated.name.startswith('Testpilot_') and isolated.desktop is not None, 'Only an owned isolated desktop may be resized'
    win32gui.EnumDesktopWindows(isolated.desktop, visit, None)
    assert len(set(windows)) == 1, 'Owned main window is absent or ambiguous'
    hwnd = windows[0]
    dpi_context = ctypes.windll.user32.SetThreadDpiAwarenessContext
    dpi_context.argtypes = [ctypes.c_void_p]
    dpi_context.restype = ctypes.c_void_p
    previous_context = dpi_context(ctypes.c_void_p(-4))
    assert previous_context, 'Cannot select physical coordinates for the owned test window'
    try:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetWindowPos(hwnd, 0, 20, 20, width, height, win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE)
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        assert (right - left, bottom - top) == (width, height), f'1C accepted window size {(right-left, bottom-top)}, requested {(width, height)}'
        return {'pid': pid, 'rect': [left, top, right, bottom], 'dpi': ctypes.windll.user32.GetDpiForWindow(hwnd), 'coordinates': 'physical-pixels'}
    finally:
        dpi_context(previous_context)


def exercise_sidebar(client, options, evidence):
    """Verify one native workspace, horizontal collapse and independent drafts."""
    def state():
        context = client.get_context(result_mode='full', include_tables=False)
        assert context.get('form', {}).get('form_name') == 'Обработка.КИИ_ТестИИ.Форма.Форма'
        return {'form_id': context['form']['name'],
                'title': client.find_object(name='ЗаголовокДиалога').get_data_presentation(),
                'sidebar_visible': client.find_object(name='ПанельБесед').is_visible().get('visible')}

    def select(title, draft):
        evidence.record('sidebar-before-select-' + title,
            client.get_context(result_mode='full', include_tables=False))
        table = client.find_object(name='СписокБесед')
        table.activate()
        table.goto_first_row()
        selected = table.goto_row(column='Беседа', value=title)
        assert selected.get('found') is True, ('Saved dialogue missing', title, selected)
        client.wait_until('Selected draft is visible',
            lambda: client.find_object(name='Промпт').get_data_presentation(),
            condition=lambda text: text == draft, timeout=20, interval=0.2)

    initial = state()
    assert initial['sidebar_visible']
    draft_a = 'Draft A: keep this text in the first dialogue.'
    draft_b = 'Draft B: independent second dialogue.'
    client.find_object(name='ЗаголовокДиалога').input_text(text='UI-dialogue-A')
    client.find_object(name='Промпт').input_text(text=draft_a)
    evidence.record('sidebar-before-new', client.get_context(result_mode='full', include_tables=True))
    client.find_object(name='Очистить').click()
    second = state()
    evidence.record('sidebar-after-new', second)
    assert second['form_id'] == initial['form_id'], 'New dialogue opened another workspace'
    assert second['title'] != 'UI-dialogue-A', 'New dialogue retained the previous title'
    assert client.find_object(name='Промпт').get_data_presentation() == ''
    evidence.record('sidebar-before-second-title', client.get_context(result_mode='full', include_tables=False))
    try:
        client.find_object(name='ЗаголовокДиалога').input_text(text='UI-dialogue-B')
    except ActionError:
        evidence.record('sidebar-title-failure-state', state())
        record_table_states(client, evidence, 'sidebar-title-failure-tables')
        raise
    client.find_object(name='Промпт').input_text(text=draft_b)
    select('UI-dialogue-A', draft_a)
    assert state()['title'] == 'UI-dialogue-A'
    evidence.record('sidebar-expanded', client.get_context(result_mode='full', include_tables=False))
    options.output.joinpath('sidebar-expanded.png').write_bytes(capture_screenshot(client).png)
    client.find_object(name='МоиДиалоги').click()
    collapsed = state()
    assert not collapsed['sidebar_visible']
    assert client.find_object(name='Промпт').get_data_presentation() == draft_a
    evidence.record('sidebar-collapsed', client.get_context(result_mode='full', include_tables=False))
    options.output.joinpath('sidebar-collapsed.png').write_bytes(capture_screenshot(client).png)
    client.find_object(name='МоиДиалоги').click()
    assert state()['sidebar_visible']
    select('UI-dialogue-B', draft_b)
    result = {'single_workspace': True, 'two_independent_drafts': True,
              'horizontal_sidebar_collapse': True, 'selection_preserved_after_expand': True}
    if options.exercise_review_controls:
        result['review_controls'] = exercise_review_controls(client, options, evidence)
    if not (options.exercise_deletion or options.exercise_multi_deletion):
        client.close_window()
        client.execute_command(command='e1cib/app/Обработка.КИИ_ТестИИ')
        select('UI-dialogue-B', draft_b)
        result['closed_dialogue_draft_restored'] = True
    if options.exercise_opening:
        client.execute_code(context='client', code='''
ПараметрыВыбора = Новый Структура("РежимВыбора", "Контекст");
ОткрытьФорму("Обработка.КИИ_ТестИИ.Форма.Диалоги", ПараметрыВыбора);
Результат = Истина;
''')
        table = client.find_object(name='СписокДиалогов')
        chosen = table.goto_row(column='Беседа', value='UI-dialogue-A')
        assert chosen.get('found') is True
        table.choose_row()
        context = client.get_context(result_mode='full', include_tables=True)
        evidence.record('opening-context-after-choice', context)
        assert context['form']['form_name'] == 'Обработка.КИИ_ТестИИ.Форма.Диалоги'
        client.close_window()
        assert client.find_object(name='Промпт').get_data_presentation() == draft_b
        result['context_choice_preserved_mode_and_draft'] = True
    return result


def exercise_draft_input(client, evidence):
    """Keep uncommitted text through the timer and restore both closing paths."""
    title = 'Проверка ввода вопроса'

    def reopen_with(expected):
        client.close_window()
        client.execute_command(command='e1cib/app/Обработка.КИИ_ТестИИ')
        table = client.find_object(name='СписокБесед')
        table.activate()
        table.goto_first_row()
        assert table.goto_row(column='Беседа', value=title).get('found') is True, 'Saved dialogue is missing'
        client.wait_until('Saved draft is restored',
            lambda: client.find_object(name='Промпт').get_data_presentation(),
            condition=lambda text: text == expected, timeout=15, interval=0.3)

    client.find_object(name='ЗаголовокДиалога').input_text(text=title)
    prompt = client.find_object(name='Промпт')
    prompt.activate()
    sample = 'Проверка набора вопроса с паузой'
    prompt.input_text(text=sample, finish=False)
    assert prompt.get_edit_text().get('text') == sample, 'The probe needs an uncommitted edit buffer'
    started = time.monotonic()
    readings = []
    while time.monotonic() - started < 7.1:
        readings.append({'seconds': round(time.monotonic() - started, 2), 'text': prompt.get_edit_text().get('text')})
        time.sleep(0.4)
    preserved = all(row['text'] == sample for row in readings)
    evidence.record('draft-buffer', {'preserved': preserved, 'readings': readings})
    assert preserved, 'The dialogue timer cleared text that had not been committed'

    client.find_object(name='ОтветHTML').activate()
    assert prompt.get_data_presentation() == sample, 'The draft did not survive leaving the field'
    reopen_with(sample)

    prompt = client.find_object(name='Промпт')
    prompt.activate()
    active_edit = 'Черновик перед закрытием без выхода из поля'
    prompt.input_text(text=active_edit, finish=False)
    assert prompt.get_edit_text().get('text') == active_edit
    reopen_with(active_edit)
    return {'preserved_during_timer': True, 'restored_after_leaving_field': True,
            'restored_after_closing_active_field': True}


def diagnose_layout(client, options, evidence):
    """Capture bounded, reversible layout probes in the owned isolated form."""
    lines = ['Форма = ПолучитьФорму("Обработка.КИИ_ТестИИ.Форма.Форма");', 'Сведения = Новый Массив;']
    for group in ['ГруппаОсновная', 'РабочаяОбластьБесед', 'ПанельБесед']:
        for name in ['Объединенная', 'СквозноеВыравнивание', 'РастягиватьПоВертикали', 'Группировка']:
            expression = 'Форма.Элементы.' + group + '.' + name
            lines.extend(['Попытка',
                f'Сведения.Добавить(Новый Структура("property,value", "{expression}", Строка({expression})));',
                'Исключение',
                f'Сведения.Добавить(Новый Структура("property,error", "{expression}", ОписаниеОшибки()));',
                'КонецПопытки;'])
    lines.append('Результат = Сведения;')
    values = client.execute_code(context='client', code='\n'.join(lines))
    evidence.record('layout-properties', values)
    changed = client.execute_code(context='client', code='''
Форма = ПолучитьФорму("Обработка.КИИ_ТестИИ.Форма.Форма");
Форма.Элементы.ГруппаОсновная.Объединенная = Ложь;
Результат = Форма.Элементы.ГруппаОсновная.Объединенная;
''')
    evidence.record('layout-root-united-off', changed)
    options.output.joinpath('layout-root-united-off.png').write_bytes(capture_screenshot(client).png)
    return {'root_united_probe': changed.get('result')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--mcp-helper', type=Path, required=True)
    parser.add_argument('--helper', action='store_true')
    parser.add_argument('--size', type=int, nargs=2)
    parser.add_argument('--exercise', action='store_true')
    parser.add_argument('--exercise-opening', action='store_true')
    parser.add_argument('--exercise-material-statuses', action='store_true')
    parser.add_argument('--exercise-deletion', action='store_true')
    parser.add_argument('--exercise-multi-deletion', action='store_true')
    parser.add_argument('--exercise-application-exit', action='store_true')
    parser.add_argument('--exercise-review-controls', action='store_true')
    parser.add_argument('--exercise-draft-input', action='store_true')
    parser.add_argument('--diagnose-layout', action='store_true')
    parser.add_argument('--form-scale', type=int)
    options = parser.parse_args()
    if options.form_scale is not None and (not options.helper or not 50 <= options.form_scale <= 200):
        parser.error('--form-scale requires --helper and a value between 50 and 200')
    if options.diagnose_layout and not options.helper:
        parser.error('--diagnose-layout requires --helper')
    if options.exercise_deletion and not (options.helper and options.exercise):
        parser.error('--exercise-deletion requires --helper and --exercise')
    if options.exercise_opening and not (options.helper and options.exercise):
        parser.error('--exercise-opening requires --helper and --exercise')
    if options.exercise_material_statuses and not options.helper:
        parser.error('--exercise-material-statuses requires --helper')
    if options.exercise_material_statuses and (options.exercise_deletion or options.exercise_multi_deletion
                                             or options.exercise_application_exit):
        parser.error('Material status verification requires its own undeleted dialogue')
    if options.exercise_multi_deletion and not (options.helper and options.exercise):
        parser.error('--exercise-multi-deletion requires --helper and --exercise')
    if options.exercise_deletion and options.exercise_multi_deletion:
        parser.error('Single and multi deletion fixtures must run separately')
    if options.exercise_application_exit and not (options.helper and options.exercise):
        parser.error('--exercise-application-exit requires --helper and --exercise')
    if options.exercise_review_controls and not (options.helper and options.exercise):
        parser.error('--exercise-review-controls requires --helper and --exercise')
    if options.exercise_application_exit and (options.exercise_deletion or options.exercise_multi_deletion):
        parser.error('Application-exit verification requires an open dialogue, without deletion')
    options.output.mkdir(parents=True, exist_ok=False)
    actors.O = options.output
    evidence = Evidence(options.output)
    actors.C['_edt_agent_provider'] = edt_agent_provider(Mcp(options.mcp_helper, evidence), actors.C)
    suite = actors.Actors()
    lease = actors.lease()
    result = {'passed': False, 'cleanup_complete': False}
    actor = None
    before = None
    launched = None
    try:
        suite.connect()
        suite.baseline = suite.snapshot()
        evidence.record('baseline', suite.baseline)
        before = register_snapshot(suite.base)
        evidence.record('baseline-dialogues', before)
        roles = BASE_ROLES + (['СохранениеДанныхПользователя',
            'ИнтерактивноеОткрытиеВнешнихОтчетовИОбработок'] if options.helper else [])
        actor = suite.create('forms', roles)
        result['actor'] = actor
        if options.helper:
            # The helper is an external processing. Prepare only this disposable
            # actor's startup trust; do not alter existing users or product roles.
            base = suite.base
            user_ref = base.Справочники.Пользователи.ПолучитьСсылку(
                base.NewObject('УникальныйИдентификатор', actor['catalog_uid']))
            user_object = user_ref.ПолучитьОбъект()
            description = base.Пользователи.НовоеОписаниеПользователяИБ()
            description.Вставить('Действие', 'Записать')
            description.Вставить('ЗащитаОтОпасныхДействий', False)
            user_object.ДополнительныеСвойства.Вставить('ОписаниеПользователяИБ', description)
            user_object.Записать()
            native = base.Пользователи.НайтиПоСсылке(user_ref)
            assert not native.ЗащитаОтОпасныхДействий.ПредупреждатьОбОпасныхДействиях
            assert sorted(str(role.Имя) for role in native.Роли) == actor['roles']
            evidence.record('owned-fixture-trust', {'only_temporary_actor': True,
                'product_data_roles_unchanged': True, 'native_external_file_warning': False})
            native = description = user_object = user_ref = base = None
        suite.disconnect()
        with Client() as client:
            launched = client.launch_client(
                base='localhost\\iikona_perf_20261011', server=True,
                user=actor['name'], password='123456',
                exe=str(Path(actors.C['platform_bin']) / '1cv8c.exe'),
                version='8.3.27.1989', desktop='isolated',
                extra_args=['/RunModeManagedApplication', '/Out', str(options.output/'platform.log')], wait=150,
                code_epf='F:/WorkAI/tools/1c-testpilot/onec/Testpilot/Testpilot.epf' if options.helper else '')
            evidence.record('launch', launched)
            client.wait_until('Wait for the first application window',
                lambda: client.call('get_active_window', check=False),
                condition=lambda value: bool(value.get('ok') and value.get('key')),
                timeout=90, interval=1)
            evidence.record('startup', client.get_context(result_mode='full', include_tables=True))
            if options.helper:
                evidence.record('native-identity', client.execute_code(
                    code='Результат = Строка(ПользователиИнформационнойБазы.ТекущийПользователь().УникальныйИдентификатор);', context='server'))
            options.output.joinpath('startup.png').write_bytes(capture_screenshot(client).png)
            client.execute_command(command='e1cib/app/Обработка.КИИ_ТестИИ')
            if options.form_scale is not None:
                evidence.record('form-scale', client.execute_code(context='client',
                    parameters={'scale': options.form_scale}, code='''
Форма = ПолучитьФорму("Обработка.КИИ_ТестИИ.Форма.Форма");
Форма.Масштаб = Параметры["scale"];
Форма.Открыть();
Результат = Форма.Масштаб;
'''))
            if options.size:
                evidence.record('window-size', resize_owned_client(client, launched['pid'], *options.size))
            evidence.record('dialogue', client.get_context(result_mode='full', include_tables=True))
            screenshot = capture_screenshot(client)
            options.output.joinpath('dialogue.png').write_bytes(screenshot.png)
            if options.size:
                import io
                from PIL import Image
                assert Image.open(io.BytesIO(screenshot.png)).size == tuple(options.size), 'Screenshot and requested physical window size differ'
            if options.exercise_draft_input:
                result['draft_input'] = exercise_draft_input(client, evidence)
            if options.exercise:
                result.update(exercise_sidebar(client, options, evidence))
            if options.diagnose_layout:
                result['layout_probe'] = diagnose_layout(client, options, evidence)
            if options.exercise_deletion:
                result['deletion'] = exercise_dialogue_deletion(client, options, evidence)
            if options.exercise_material_statuses:
                result['material_statuses'] = exercise_material_statuses(client, options, evidence, actor, suite.baseline)
            if options.exercise_multi_deletion:
                result['multi_deletion'] = exercise_multiple_dialogue_deletion(client, options, evidence)
            if options.exercise_application_exit:
                result['application_exit'] = exercise_application_exit(client, evidence)
            result['passed'] = True
    except Exception as error:
        if launched is None:
            launched = failed_launch_result(getattr(error, 'action', None), getattr(error, 'result', None))
            if launched is not None:
                evidence.record('launch', launched)
        result['error'] = str(error).replace('123456', '[test-password]')
        result['error_type'] = type(error).__name__
        result['traceback'] = traceback.format_exc().replace('123456', '[test-password]')
        if hasattr(error, 'result'):
            evidence.record('action-error', error.result)
    finally:
        gc.collect()
        try:
            cleanup_owned_forms_session(actors.C, actor, launched, suite.baseline, evidence)
            suite.connect()
            if actor is not None:
                remove_actor_dialogues(suite, [actor], before)
            suite.cleanup_generated_service_user()
            suite.cleanup()
            result['cleanup_complete'] = True
        except Exception as error:
            result['cleanup_error'] = str(error)
        finally:
            try:
                suite.disconnect()
            except Exception as error:
                result['disconnect_error'] = str(error)
            finally:
                lease.release()
        evidence.record('result', result)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['passed'] and result['cleanup_complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

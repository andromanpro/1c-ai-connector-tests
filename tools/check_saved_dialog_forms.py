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
from check_saved_dialog_access import BASE_ROLES, Evidence, register_snapshot, remove_actor_dialogues
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


def exercise_dialogue_deletion(client, options, evidence):
    """Exercise the native list command on the two dialogues owned by this actor."""
    def select(title):
        table = client.find_object(name='СписокДиалогов')
        table.goto_first_row()
        selected = table.goto_row(column='Беседа', value=title)
        assert selected.get('found') is True, ('Dialogue not found', selected)
        actual = table.get_cell_text(column='СписокДиалоговСписокДиалогов1')
        assert actual.get('text') == title, ('Selected dialogue differs', actual)

    def own_count():
        value = client.find_object(name='СписокДиалогов').read_rows(max_rows=10)
        rows = value['rows']
        assert isinstance(rows, list), ('Native list rows are unavailable', value)
        return len(rows)

    client.find_object(name='МоиДиалоги').click()
    select('UI-dialogue-A')
    evidence.record('deletion-list', client.get_context(result_mode='full', include_tables=True))
    options.output.joinpath('deletion-list.png').write_bytes(capture_screenshot(client).png)
    assert own_count() == 2, 'Deletion probe requires exactly the actor-owned pair'
    client.find_object(name='УдалитьДиалог').click()
    options.output.joinpath('deletion-question.png').write_bytes(capture_screenshot(client).png)
    answer = client.answer_dialog(confirm=False, timeout=10)
    evidence.record('deletion-cancel', answer)
    assert answer.get('answered') == 'Нет' and 'UI-dialogue-A' in (answer.get('question') or '')
    assert own_count() == 2, 'Cancel must preserve both dialogues'
    after_cancel = client.get_context(result_mode='full', include_tables=True)
    evidence.record('deletion-after-cancel', after_cancel)
    assert after_cancel['form'].get('modified') is False, 'Cancel left the read-only list marked as unsaved'

    select('UI-dialogue-A')
    client.find_object(name='УдалитьДиалог').click()
    answer = client.answer_dialog(confirm=True, timeout=10)
    evidence.record('deletion-confirm-first', answer)
    assert answer.get('answered') == 'Да' and 'UI-dialogue-A' in (answer.get('question') or '')
    client.wait_until('Deleted first dialogue disappears', own_count, condition=lambda n: n == 1, timeout=15, interval=1)
    forms = client.find_objects(cls='ManagedForm', scope='application')
    evidence.record('deletion-open-forms-first', [form.info for form in forms])
    assert not any('UI-dialogue-A' in form.info.get('title', '') for form in forms), 'Deleted open dialogue remains on screen'

    # The list was opened by B. This checks closing the owner form from its list.
    select('UI-dialogue-B')
    client.find_object(name='УдалитьДиалог').click()
    answer = client.answer_dialog(confirm=True, timeout=10)
    evidence.record('deletion-confirm-owner', answer)
    assert answer.get('answered') == 'Да' and 'UI-dialogue-B' in (answer.get('question') or '')
    evidence.record('deletion-owner-returned', client.get_context(result_mode='full', include_tables=True))
    options.output.joinpath('deletion-owner-returned.png').write_bytes(capture_screenshot(client).png)
    client.wait_until('Deleted owner dialogue disappears', own_count, condition=lambda n: n == 0, timeout=15, interval=1)
    forms = client.find_objects(cls='ManagedForm', scope='application')
    evidence.record('deletion-open-forms-final', [form.info for form in forms])
    assert not any('UI-dialogue-' in form.info.get('title', '') for form in forms), 'Deleted dialogue window remains open'
    evidence.record('deletion-final', client.get_context(result_mode='full', include_tables=True))
    options.output.joinpath('deletion-final.png').write_bytes(capture_screenshot(client).png)
    return {'cancel_preserved_data': True, 'native_confirmations': 3,
            'both_owned_dialogues_deleted': True, 'open_owner_and_other_form_closed': True}


def exercise_multiple_dialogue_deletion(client, options, evidence):
    """Delete the selected pair through one native confirmation, including cancel."""
    client.find_object(name='МоиДиалоги').click()
    table = client.find_object(name='СписокДиалогов')
    before = table.read_rows(max_rows=10)
    assert len(before['rows']) == 2, 'The multi-delete fixture requires exactly its own pair'
    table.select_all_rows()
    selection = table.get_selected_rows()
    evidence.record('multi-selection', selection)
    assert len(selection['rows']) == 2, 'Two rows must actually be selected in the live table'
    options.output.joinpath('multi-selection.png').write_bytes(capture_screenshot(client).png)
    table = client.find_object(name='СписокДиалогов')
    table.select_all_rows()
    assert len(table.get_selected_rows()['rows']) == 2, 'Confirm must still apply to the selected pair'
    client.find_object(name='УдалитьДиалог').click()
    options.output.joinpath('multi-question.png').write_bytes(capture_screenshot(client).png)
    cancelled = client.answer_dialog(confirm=False, timeout=10)
    evidence.record('multi-cancel', cancelled)
    assert cancelled.get('answered') == 'Нет' and '(2)' in (cancelled.get('question') or '')
    after_cancel = client.get_context(result_mode='full', include_tables=True)
    evidence.record('multi-after-cancel', after_cancel)
    assert after_cancel['form'].get('modified') is False, 'Cancel must not mark the list as unsaved'
    assert len(client.find_object(name='СписокДиалогов').read_rows(max_rows=10)['rows']) == 2
    table = client.find_object(name='СписокДиалогов')
    table.select_all_rows()
    selection_after_cancel = table.get_selected_rows()
    evidence.record('multi-reselection', selection_after_cancel)
    assert len(selection_after_cancel['rows']) == 2, 'The second command must start with two selected rows'
    client.find_object(name='УдалитьДиалог').click()
    confirmed = client.answer_dialog(confirm=True, timeout=10)
    evidence.record('multi-confirm', confirmed)
    assert confirmed.get('answered') == 'Да' and '(2)' in (confirmed.get('question') or '')
    client.wait_until('The whole selected pair disappears',
        lambda: len(client.find_object(name='СписокДиалогов').read_rows(max_rows=10)['rows']),
        condition=lambda count: count == 0, timeout=15, interval=1)
    forms = client.find_objects(cls='ManagedForm', scope='application')
    evidence.record('multi-open-forms-final', [form.info for form in forms])
    assert not any('UI-dialogue-' in form.info.get('title', '') for form in forms)
    evidence.record('multi-final', client.get_context(result_mode='full', include_tables=True))
    options.output.joinpath('multi-final.png').write_bytes(capture_screenshot(client).png)
    return {'selected': 2, 'cancel_preserved_both': True,
            'one_confirmation_deleted_both': True, 'open_dialogues_closed': True,
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--mcp-helper', type=Path, required=True)
    parser.add_argument('--helper', action='store_true')
    parser.add_argument('--size', type=int, nargs=2)
    parser.add_argument('--exercise', action='store_true')
    parser.add_argument('--exercise-deletion', action='store_true')
    parser.add_argument('--exercise-multi-deletion', action='store_true')
    parser.add_argument('--exercise-application-exit', action='store_true')
    parser.add_argument('--form-scale', type=int)
    options = parser.parse_args()
    if options.form_scale is not None and (not options.helper or not 50 <= options.form_scale <= 200):
        parser.error('--form-scale requires --helper and a value between 50 and 200')
    if options.exercise_deletion and not (options.helper and options.exercise):
        parser.error('--exercise-deletion requires --helper and --exercise')
    if options.exercise_multi_deletion and not (options.helper and options.exercise):
        parser.error('--exercise-multi-deletion requires --helper and --exercise')
    if options.exercise_deletion and options.exercise_multi_deletion:
        parser.error('Single and multi deletion fixtures must run separately')
    if options.exercise_application_exit and not (options.helper and options.exercise):
        parser.error('--exercise-application-exit requires --helper and --exercise')
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
            if options.exercise:
                client.find_object(name='ЗаголовокДиалога').input_text(text='UI-dialogue-A')
                client.find_object(name='Промпт').input_text(text='Draft A: keep this text in the first dialogue.')
                client.find_object(name='Очистить').click()
                evidence.record('second-dialogue', client.get_context(result_mode='full'))
                assert client.find_object(name='Промпт').get_data_presentation() == ''
                client.find_object(name='ЗаголовокДиалога').input_text(text='UI-dialogue-B')
                client.find_object(name='Промпт').input_text(text='Draft B: independent second dialogue.')
                options.output.joinpath('two-dialogues.png').write_bytes(capture_screenshot(client).png)
                client.close_window()
                evidence.record('returned-first', client.get_context(result_mode='full'))
                assert client.find_object(name='Промпт').get_data_presentation() == 'Draft A: keep this text in the first dialogue.'
                client.find_object(name='МоиДиалоги').click()
                evidence.record('saved-dialogue-list', client.get_context(result_mode='full', include_tables=True))
                options.output.joinpath('saved-dialogue-list.png').write_bytes(capture_screenshot(client).png)
                client.find_object(name='Выбрать').click()
                evidence.record('reopened-second', client.get_context(result_mode='full'))
                assert client.find_object(name='Промпт').get_data_presentation() == 'Draft B: independent second dialogue.'
                result['two_independent_drafts'] = True
                result['closed_dialogue_draft_restored'] = True
            if options.exercise_deletion:
                result['deletion'] = exercise_dialogue_deletion(client, options, evidence)
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

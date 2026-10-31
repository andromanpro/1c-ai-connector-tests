"""Exercise saved dialogue forms with a real limited BSP actor and Testpilot."""
import argparse
import gc
import json
import os
from pathlib import Path
import sys
import traceback

os.environ['TC1C_SCREENSHOTS'] = 'true'
sys.path.insert(0, 'F:/WorkAI/tools/1c-testpilot/app')
from testpilot import Client
import bsp_test_users as actors
from check_saved_dialog_access import BASE_ROLES, Evidence, register_snapshot, remove_actor_dialogues
from edt_yaxunit import Mcp, edt_agent_provider


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
    options = parser.parse_args()
    options.output.mkdir(parents=True, exist_ok=False)
    actors.O = options.output
    evidence = Evidence(options.output)
    actors.C['_edt_agent_provider'] = edt_agent_provider(Mcp(options.mcp_helper, evidence), actors.C)
    suite = actors.Actors()
    lease = actors.lease()
    result = {'passed': False, 'cleanup_complete': False}
    actor = None
    before = None
    try:
        suite.connect()
        suite.baseline = suite.snapshot()
        evidence.record('baseline', suite.baseline)
        before = register_snapshot(suite.base)
        evidence.record('baseline-dialogues', before)
        actor = suite.create('forms', BASE_ROLES)
        result['actor'] = actor
        suite.disconnect()
        with Client() as client:
            launched = client.launch_client(
                base='localhost\\iikona_perf_20261011', server=True,
                user=actor['name'], password='123456',
                exe=str(Path(actors.C['platform_bin']) / '1cv8c.exe'),
                version='8.3.27.1989', desktop='isolated',
                extra_args=['/RunModeManagedApplication'], wait=150,
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
            options.output.joinpath('startup.png').write_bytes(client.get_screenshot().png)
            client.execute_command(command='e1cib/app/Обработка.КИИ_ТестИИ')
            if options.size:
                evidence.record('window-size', resize_owned_client(client, launched['pid'], *options.size))
            evidence.record('dialogue', client.get_context(result_mode='full', include_tables=True))
            screenshot = client.get_screenshot()
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
                options.output.joinpath('two-dialogues.png').write_bytes(client.get_screenshot().png)
                client.close_window()
                evidence.record('returned-first', client.get_context(result_mode='full'))
                assert client.find_object(name='Промпт').get_data_presentation() == 'Draft A: keep this text in the first dialogue.'
                client.find_object(name='МоиДиалоги').click()
                evidence.record('saved-dialogue-list', client.get_context(result_mode='full', include_tables=True))
                options.output.joinpath('saved-dialogue-list.png').write_bytes(client.get_screenshot().png)
                client.find_object(name='Выбрать').click()
                evidence.record('reopened-second', client.get_context(result_mode='full'))
                assert client.find_object(name='Промпт').get_data_presentation() == 'Draft B: independent second dialogue.'
                result['two_independent_drafts'] = True
                result['closed_dialogue_draft_restored'] = True
            result['passed'] = True
    except Exception as error:
        result['error'] = str(error).replace('123456', '[test-password]')
        result['error_type'] = type(error).__name__
        result['traceback'] = traceback.format_exc().replace('123456', '[test-password]')
        if hasattr(error, 'result'):
            evidence.record('action-error', error.result)
    finally:
        gc.collect()
        try:
            suite.connect()
            if actor is not None:
                remove_actor_dialogues(suite, [actor], before)
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

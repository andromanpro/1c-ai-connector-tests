"""Preflight known YAxUnit startup rights and classify fatal initialization logs."""
import re
from verification_receipt import require


def require_startup_roles(roles):
    # Current BSP stand: the standard role grants SaveUserData, needed by
    # ЮТКонтекстСлужебныйВызовСервера.ИнициализироватьКонтекст. FullRights also
    # supplies it. These are preparation rights; log RLS remains unchanged.
    require(bool({'СохранениеДанныхПользователя', 'ПолныеПрава'} & set(roles)),
            'YAxUnit initialization requires SaveUserData: add the standard BSP '
            'СохранениеДанныхПользователя role to the test profile before launch')


def startup_failure(text):
    lines = text.replace('\r', '').splitlines()
    fatal = 'Зацикливание обработки глобальной ошибки, дальнейшая работа YAxUnit прервана'
    if any(fatal in line for line in lines):
        return {'stage': 'yaxunit-initialization', 'kind': 'global-error-loop',
                'test_execution_proven': False, 'diagnostic': text.strip()}
    starts = [i for i, line in enumerate(lines)
              if re.match(r'^\s*Инициализация:\s*Ошибка(?:\s|[.:]|$)', line, re.IGNORECASE)]
    if not starts:
        return None
    diagnostic = '\n'.join(lines[starts[0]:]).strip()
    return {'stage': 'yaxunit-initialization',
            'kind': 'access-denied' if ('[НарушениеПравДоступа]' in diagnostic
                                      or 'Нарушение прав доступа!' in diagnostic)
                    else 'initialization-error',
            'test_execution_proven': False, 'diagnostic': diagnostic}

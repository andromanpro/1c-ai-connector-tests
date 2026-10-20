"""Объективные проверки оформления BSL; код не изменяется.

Проверяются только явно переданные файлы. Строки, даты и комментарии
отделяет закрепленный lossless-лексер bslfmt, без догадок по сырому regex.
Код возврата: 0 - замечаний нет, 1 - замечания, 2 - проверка не выполнена.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
import sys

LEXER_SOURCE = Path('F:/WorkAI/tools/bslfmt/src')
sys.path.insert(0, str(LEXER_SOURCE))
from bslfmt.lexer import LexerError, lex

RULES = {
    'BSLSTYLE001': 'Несколько операторов на одной строке',
    'BSLSTYLE002': 'Тело блока на строке его заголовка',
    'BSLSTYLE003': 'Многострочное вычисление коллекции в заголовке цикла',
    'BSLSTYLE004': 'Длинный список полей в заголовке цикла',
}

@dataclass(frozen=True)
class Word:
    text: str
    kind: str
    start: int
    end: int
    line: int
    column: int

@dataclass(frozen=True)
class Issue:
    rule: str
    line: int
    column: int
    message: str

def words(source: str) -> list[Word]:
    result = []
    directive_lines = {n for n, line in enumerate(source.splitlines(), 1)
                       if line.lstrip().startswith(('#', '&'))}
    for token in lex(source):
        if token.kind in {'whitespace', 'newline', 'comment'}:
            continue
        if token.kind == 'opaque':
            raise ValueError('Область вставки/удаления требует отдельного разбора; проверка не считается выполненной')
        if token.line in directive_lines:
            continue
        if token.kind in {'string', 'date'}:
            result.append(Word(token.text, token.kind, token.start, token.end, token.line, token.column))
            continue
        for match in re.finditer(r'\w+|[^\s]', token.text):
            result.append(Word(match.group(), 'code', token.start + match.start(),
                               token.start + match.end(), token.line, token.column + match.start()))
    return result

def check_source(source: str, *, list_length: int = 80, min_fields: int = 4) -> list[Issue]:
    if list_length < 1 or min_fields < 2:
        raise ValueError('Некорректные пороги проверки списков')
    tokens = words(source)
    issues = []
    emitted = set()
    def add(rule, token, message):
        key = (rule, token.line)
        if key not in emitted:
            emitted.add(key)
            issues.append(Issue(rule, token.line, token.column, message))
    for index, token in enumerate(tokens[:-1]):
        following = tokens[index + 1]
        if token.kind != 'code' or following.line != token.line:
            continue
        if token.text == ';':
            add('BSLSTYLE001', following, 'Каждый оператор и конец блока разместите на отдельной строке.')
        previous = tokens[index - 1].text if index else ''
        if previous != '.' and token.text.casefold() in {'тогда','иначе','цикл','попытка','исключение',
                                                         'then','else','do','try','except'}:
            add('BSLSTYLE002', following, 'Тело блока начните со следующей строки; сохраните отступ.')
    for index in range(len(tokens) - 2):
        if [x.text.casefold() for x in tokens[index:index + 2]] not in [['для','каждого'],['for','each']]:
            continue
        cursor = index + 2
        while cursor < len(tokens) and tokens[cursor].text.casefold() not in {'из','in',';'}:
            cursor += 1
        if cursor == len(tokens) or tokens[cursor].text == ';':
            continue
        start = cursor + 1
        cursor = start
        while cursor < len(tokens):
            current = tokens[cursor]
            if current.kind == 'code' and current.text.casefold() in {'цикл','do',';'}:
                break
            cursor += 1
        if cursor == len(tokens) or tokens[cursor].text == ';':
            continue
        expression = tokens[start:cursor]
        if not expression:
            continue
        if any(t.kind == 'code' and t.text == '(' for t in expression) and expression[0].line < tokens[cursor].line:
            add('BSLSTYLE003', expression[0], 'Подготовьте вычисляемую коллекцию перед циклом и дайте ей имя по назначению.')
        for literal in expression:
            if literal.kind != 'string':
                continue
            text = literal.text[1:-1].replace('""', '"')
            fields = text.split(',')
            if len(text) >= list_length and len(fields) >= min_fields and all(re.fullmatch(r'\s*\w[\w.]*\s*', x) for x in fields):
                add('BSLSTYLE004', literal, 'Вынесите длинный перечень полей из заголовка в именованную коллекцию или явные операции.')
    return sorted(issues, key=lambda x: (x.line, x.column, x.rule))

def check_paths(paths: list[Path], *, list_length=80, min_fields=4) -> dict:
    if not paths:
        raise ValueError('Не задан ни один файл BSL')
    files = []
    for path in paths:
        if path.suffix.casefold() != '.bsl' or not path.is_file():
            raise ValueError(f'Недоступный BSL-файл: {path}')
        raw = path.read_bytes()
        issues = check_source(raw.decode('utf-8-sig'), list_length=list_length, min_fields=min_fields)
        files.append({'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(),
                      'issues': [asdict(x) for x in issues]})
    lexer_file = LEXER_SOURCE/'bslfmt/lexer.py'
    return {'engine': 'bsl-readability', 'version': 1, 'rules': RULES,
            'list_length': list_length, 'min_fields': min_fields,
            'lexer_sha256': hashlib.sha256(lexer_file.read_bytes()).hexdigest(),
            'files': files, 'issues': sum(len(x['issues']) for x in files)}

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('files', nargs='*', type=Path)
    parser.add_argument('--list-file', type=Path, help='JSON: массив явных путей к BSL')
    parser.add_argument('--json-report', type=Path)
    parser.add_argument('--list-length', type=int, default=80)
    parser.add_argument('--min-fields', type=int, default=4)
    args = parser.parse_args(argv)
    try:
        paths = args.files
        if args.list_file:
            selected = json.loads(args.list_file.read_text(encoding='utf-8-sig'))
            if not isinstance(selected, list) or not all(isinstance(x, str) and x for x in selected):
                raise ValueError('Список файлов должен быть непустым массивом путей')
            paths = paths + [Path(x) for x in selected]
        if len(set(map(str, paths))) != len(paths):
            raise ValueError('В списке повторяется один файл')
        report = check_paths(paths, list_length=args.list_length, min_fields=args.min_fields)
        if args.json_report:
            args.json_report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        for file in report['files']:
            for issue in file['issues']:
                print(f"{file['path']}:{issue['line']}:{issue['column']}: {issue['rule']} {issue['message']}")
        print(f"Проверено файлов: {len(report['files'])}; замечаний: {report['issues']}")
        return 1 if report['issues'] else 0
    except (OSError, UnicodeError, ValueError, LexerError) as exc:
        print('Проверка оформления НЕ выполнена: ' + str(exc), file=sys.stderr)
        return 2

if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    raise SystemExit(main())

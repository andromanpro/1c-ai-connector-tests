from pathlib import Path
import json
import sys
import xml.etree.ElementTree as ET

sys.stdout.reconfigure(encoding='utf-8')
RUN = Path('F:/temp/iikona-audit-20261013/runs/20261013T085116Z-507a813ce714')
NIL = '{http://www.w3.org/2001/XMLSchema-instance}nil'


def local(tag):
    return tag.rsplit('}', 1)[-1]


def normalized(node):
    children = [normalized(c) for c in node if not (local(c.tag) in ('MinValue', 'MaxValue')
                and c.attrib == {NIL: 'true'} and not len(c) and not (c.text or '').strip())]
    kind = local(node.tag)
    if kind in ('Properties', 'Events', 'Rights', 'object', 'right'):
        children.sort(key=repr)
    text = node.text or ''
    if (len(node) or kind == 'InternalInfo') and not text.strip():
        text = ''
    return [node.tag, sorted(node.attrib.items()), text, children]


def main():
    report = {}
    for extension in ('ИИКона', 'Тесты'):
        left, right = RUN / 'export' / extension, RUN / 'build-runtime' / extension
        differences = []
        for p in left.rglob('*.xml'):
            relative = p.relative_to(left)
            a, b = normalized(ET.parse(p).getroot()), normalized(ET.parse(right / relative).getroot())
            if a != b:
                # Compact differing nodes; preserve full documents in the run.
                import difflib
                diff = list(difflib.unified_diff(json.dumps(a, ensure_ascii=False, indent=1).splitlines(),
                                               json.dumps(b, ensure_ascii=False, indent=1).splitlines(), n=1))
                differences.append({'file': str(relative), 'diff': diff})
        report[extension] = differences
        print(extension, 'different XML after explicit normalization:', len(differences))
        for item in differences:
            print(item['file'], '\n'.join(item['diff'][:90]))
    (Path(__file__).parent / 'xml-semantic-differences.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()

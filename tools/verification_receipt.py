"""Tie a 1C verification to immutable inputs, installed CFE files and fresh JUnit.

No connections, credentials, configuration updates or process termination here.
The caller captures installed extensions from the actual connection while the
test client is stopped, then passes their files and the actual public base ID.
"""
from __future__ import annotations

import collections
import datetime as dt
import hashlib
import json
from pathlib import Path
import uuid
import xml.etree.ElementTree as ET
import zipfile


class VerificationError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise VerificationError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def expected_contexts(tests, contexts=None):
    """Bind each exact test to server or managed-client execution at capture time."""
    if contexts is None:
        return {name: 'Сервер' for name in tests}
    require(isinstance(contexts, dict) and set(contexts) == set(tests),
            'Expected contexts must match every selected test exactly')
    require(all(value in ('Сервер', 'КлиентУправляемоеПриложение') for value in contexts.values()),
            'Only server and managed-client test contexts are supported')
    return dict(sorted(contexts.items()))


def manifest(roots):
    result = {}
    for label, directory in sorted(roots.items()):
        root = Path(directory).resolve(strict=True)
        require(root.is_dir(), f"Not a source directory: {label}")
        files = [p for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts]
        require(files, f"Empty source directory: {label}")
        for path in sorted(files):
            require(not path.is_symlink(), f"Source symlink: {path}")
            result[f'{label}/{path.relative_to(root).as_posix()}'] = digest(path.read_bytes())
    return result


def tree_hash(files):
    return digest(json.dumps(files, sort_keys=True, separators=(',', ':')).encode())


def canonical_file(path):
    path = Path(path)
    if path.suffix.lower() in ('.xml', '.bsl'):
        text = path.read_text(encoding='utf-8-sig').replace('\r\n', '\n')
        if path.suffix.lower() == '.xml':
            root = ET.fromstring(text)
            # Designer derives this marker from the adopted module on import;
            # EDT omits it. Do not ignore other extension property states.
            md = '{http://v8.1c.ru/8.3/MDClasses}'
            xr = '{http://v8.1c.ru/8.3/xcf/readable}'
            module = root.find(md + 'CommonModule')
            code = path.with_suffix('') / 'Ext' / 'Module.bsl'
            if module is not None and code.is_file():
                props = module.find(md + 'Properties')
                info = module.find(md + 'InternalInfo')
                if props is not None and info is not None and props.findtext(md + 'ObjectBelonging') == 'Adopted':
                    for state in list(info):
                        if (state.tag == xr + 'PropertyState' and len(state) == 2
                                and not state.attrib and state.findtext(xr + 'Property') == 'Module'
                                and state.findtext(xr + 'State') == 'Extended'):
                            info.remove(state)
            return json.dumps(xml_value(root), ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        return text.rstrip('\n').encode('utf-8')
    return path.read_bytes()


def xml_value(node):
    """Normalize proven serialization differences, retaining order in form items.

    Only named property/event/right collections are unordered. Never sort table
    columns, form ChildItems or arbitrary XML arrays. Explicit nonempty defaults,
    limits, role values and all other metadata remain part of the fingerprint.
    """
    md = '{http://v8.1c.ru/8.3/MDClasses}'
    xsi = '{http://www.w3.org/2001/XMLSchema-instance}'
    children = []
    for child in node:
        absent_default = (child.tag in (md + 'MinValue', md + 'MaxValue', md + 'FillValue')
                          and child.attrib == {xsi + 'nil': 'true'} and not len(child)
                          and not (child.text or '').strip())
        empty_string_default = (child.tag == md + 'FillValue' and child.attrib == {xsi + 'type': 'xs:string'}
                                and not len(child) and not child.text
                                and node.findtext(md + 'FillFromFillingValue') == 'false')
        if not (absent_default or empty_string_default):
            children.append(xml_value(child))
    name = node.tag.rsplit('}', 1)[-1]
    unordered = {md + 'Properties', '{http://v8.1c.ru/8.3/xcf/logform}Events',
                 '{http://v8.1c.ru/8.2/roles}Rights', '{http://v8.1c.ru/8.2/roles}object',
                 '{http://v8.1c.ru/8.2/roles}right'}
    if node.tag in unordered:
        children.sort(key=repr)
    # TypeDescription alternatives form a set. Keep qualifiers, duplicate
    # alternatives and every type name; only reorder the core:Type leaves.
    core = '{http://v8.1c.ru/8.1/data/core}'
    form = '{http://v8.1c.ru/8.3/xcf/logform}'
    roles = '{http://v8.1c.ru/8.2/roles}'
    unordered_leaf = None
    if node.tag in (md + 'Type', form + 'Type'):
        unordered_leaf = core + 'Type'
    elif node.tag == roles + 'restrictionByCondition':
        # Field order within one restriction does not change its scope.
        # The field/condition association and the empty default scope stay intact.
        unordered_leaf = roles + 'field'
    if unordered_leaf is not None:
        positions = [i for i, child in enumerate(children)
                     if child[0] == unordered_leaf and not child[1] and not child[3]]
        values = sorted((children[i] for i in positions), key=repr)
        for index, value in zip(positions, values):
            children[index] = value
    text = node.text or ''
    if (len(node) or name == 'InternalInfo') and not text.strip():
        text = ''
    return [node.tag, sorted(node.attrib.items()), text, children]


def exported_tree(directory):
    root = Path(directory).resolve(strict=True)
    files = {}
    for p in sorted(root.rglob('*')):
        if not p.is_file():
            continue
        relative = p.relative_to(root).as_posix()
        if relative == 'ConfigDumpInfo.xml':
            require(ET.parse(p).getroot().tag == '{http://v8.1c.ru/8.3/xcf/dumpinfo}ConfigDumpInfo',
                    'Unexpected ConfigDumpInfo.xml content')
            continue  # Export inventory, not configuration contents.
        files[relative] = digest(canonical_file(p))
    require(files, f"Empty export: {root}")
    return files


def compare_files(expected, actual, description):
    removed = sorted(expected.keys() - actual.keys())
    added = sorted(actual.keys() - expected.keys())
    changed = sorted(k for k in expected.keys() & actual.keys() if expected[k] != actual[k])
    require(not (removed or added or changed),
            f'{description}: removed={removed}; added={added}; changed={changed}')


class Receipt:
    def __init__(self, folder):
        self.folder = Path(folder).resolve(strict=True)
        require(digest((self.folder / 'inputs.json').read_bytes()) ==
                (self.folder / 'inputs.sha256').read_text().strip(), 'Inputs were modified')
        self.spec = json.loads((self.folder / 'inputs.json').read_text(encoding='utf-8'))
        require(self.folder.name == self.spec['run_id'], 'Wrong run directory')
        self.test_contexts = expected_contexts(self.spec['tests'], self.spec.get('test_contexts'))

    @classmethod
    def begin(cls, output_root, roots, target, tests, test_contexts=None):
        require(target and isinstance(target, str), 'An explicit public base ID is required')
        require(tests and len(tests) == len(set(tests)), 'Empty or duplicate expected tests')
        require(all('.' in x for x in tests), 'Tests must include module and method')
        contexts = expected_contexts(tests, test_contexts)
        roots = {k: str(Path(v).resolve(strict=True)) for k, v in roots.items()}
        output = Path(output_root).resolve()
        require(all(not output.is_relative_to(Path(v)) for v in roots.values()),
                'Output must be outside source directories')
        run_id = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex[:12]
        folder = output / run_id
        folder.mkdir(parents=True, exist_ok=False)
        files = manifest(roots)
        data = {'schema': 1, 'run_id': run_id, 'roots': roots, 'target': target,
                'tests': sorted(tests), 'test_contexts': contexts,
                'source_files': files, 'source_hash': tree_hash(files),
                'verifier_sha256': digest(Path(__file__).read_bytes())}
        with zipfile.ZipFile(folder / 'sources.zip', 'x', zipfile.ZIP_DEFLATED) as archive:
            for name in files:
                label, relative = name.split('/', 1)
                archive.write(Path(roots[label]) / relative, name)
        # Detect edits during capture, not just after it.
        compare_files(files, manifest(roots), 'Source changed during capture')
        with zipfile.ZipFile(folder / 'sources.zip') as archive:
            compare_files(files, {n: digest(archive.read(n)) for n in archive.namelist()},
                          'Captured archive differs')
        raw = json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8')
        (folder / 'inputs.json').write_bytes(raw)
        (folder / 'inputs.sha256').write_text(digest(raw), encoding='ascii')
        return cls(folder)

    def unchanged(self):
        require(digest(Path(__file__).read_bytes()) == self.spec['verifier_sha256'],
                'Verifier changed after capture')
        compare_files(self.spec['source_files'], manifest(self.spec['roots']), 'Source changed')

    def record(self, name, data):
        self.unchanged()
        require(name.replace('-', '').replace('_', '').isalnum(), 'Invalid evidence name')
        path = self.folder / (name + '.json')
        with path.open('x', encoding='utf-8') as stream:
            json.dump(dict(run_id=self.spec['run_id'], source_hash=self.spec['source_hash'], **data),
                      stream, ensure_ascii=False, indent=2)
        return data

    def build(self, expected_xml, installed_xml, artifacts):
        require(artifacts, 'No build artifacts')
        export = json.loads((self.folder / 'edt-export.json').read_text(encoding='utf-8'))
        require(set(export['projects']) == set(expected_xml), 'EDT export scope differs')
        exports = {}
        require(set(expected_xml) == set(installed_xml) == set(artifacts), 'Build extension sets differ')
        for name in expected_xml:
            wanted = exported_tree(expected_xml[name])
            require(tree_hash(wanted) == export['projects'][name]['xml_hash'], 'EDT export changed')
            compare_files(wanted, exported_tree(installed_xml[name]), f'Installed XML differs: {name}')
            exports[name] = {'files': wanted, 'tree_hash': tree_hash(wanted)}
        return self.record('build', {'xml': exports,
                          'artifacts': {k: digest(Path(v).read_bytes()) for k, v in artifacts.items()}})

    def runtime(self, stage, actual_target, extensions):
        require(stage in ('before', 'after'), 'Unknown runtime stage')
        require(actual_target == self.spec['target'], 'Connected to a different base')
        build = json.loads((self.folder / 'build.json').read_text(encoding='utf-8'))
        require(set(extensions) == set(build['artifacts']), 'Installed extension set differs')
        observed = {}
        for name, item in extensions.items():
            require(item['active'] is True, f'Inactive extension: {name}')
            require(item['version'], f'Missing runtime version: {name}')
            actual = digest(Path(item['file']).read_bytes())
            require(actual == build['artifacts'][name], f'Installed CFE differs: {name}')
            require('safe_mode' in item and (type(item['safe_mode']) is bool or
                    (isinstance(item['safe_mode'], str) and bool(item['safe_mode'].strip()))),
                    f'Missing or invalid runtime safe mode: {name}')
            observed[name] = {'sha256': actual, 'version': item['version'], 'active': True,
                              'safe_mode': item['safe_mode']}
        if stage == 'after':
            before = json.loads((self.folder / 'runtime-before.json').read_text(encoding='utf-8'))
            require(before['extensions'] == observed, 'Runtime extension policy or identity changed')
        return self.record('runtime-' + stage, {'target': actual_target, 'extensions': observed})

    def live_build(self, project, delivery, artifacts):
        """Native EDT delivery evidence; deliberately does not claim an offline XML comparison."""
        require(project and artifacts and set(delivery) == set(artifacts), 'Live delivery scope differs')
        for name, item in delivery.items():
            require(item.get('status') == 'updated' and item.get('updated') is True
                    and item.get('base_project') == project and item.get('extension_project'),
                    'Native EDT delivery was not confirmed: ' + name)
        return self.record('build', {'verification_kind': 'native-edt-delivery',
                                    'base_project': project, 'delivery': delivery,
                                    'offline_xml_comparison': False,
                                    'artifacts': {k:digest(Path(v).read_bytes()) for k,v in artifacts.items()}})

    def prepare_test(self, configuration):
        require((self.folder / 'runtime-before.json').exists(), 'Runtime was not checked')
        require(not (self.folder / 'junit.xml').exists(), 'JUnit already exists before launch')
        return self.record('test-start', {'configuration_sha256': digest(Path(configuration).read_bytes()),
                                        'junit_absent_before_launch': True})

    def junit(self, exit_code, process_exited, close_requested=False):
        require((self.folder / 'test-start.json').exists(), 'Test launch was not recorded')
        require((self.folder / 'runtime-after.json').exists(), 'Runtime was not checked after tests')
        require(process_exited and exit_code == 0 and not close_requested, 'Test client did not finish normally')
        report = self.folder / 'junit.xml'
        root = ET.parse(report).getroot()
        cases = list(root.iter('testcase'))
        names = [c.attrib.get('classname', '').split('.')[0] + '.' + c.attrib['name'] for c in cases]
        counts = collections.Counter(names)
        require(all(n == 1 for n in counts.values()), 'Duplicate test execution')
        require(sorted(names) == self.spec['tests'], 'Missing or unexpected tests')
        require(all(c.attrib.get('context') == self.test_contexts[name] for c, name in zip(cases, names)),
                'Unexpected test context')
        require(not any(list(c.iter(tag)) for c in cases for tag in ('failure', 'error', 'skipped')),
                'JUnit contains failures, errors or skipped tests')
        return self.record('junit-verified', {'sha256': digest(report.read_bytes()), 'total': len(cases),
                                           'exit_code': exit_code, 'passed': True})

    def sonar_input(self, roots):
        build = json.loads((self.folder / 'build.json').read_text(encoding='utf-8'))
        require(set(roots) == set(build['xml']), 'Sonar extension scope differs from build')
        for name, path in roots.items():
            compare_files(build['xml'][name]['files'], exported_tree(path), f'Sonar input differs: {name}')
        return self.record('sonar-input', {'xml_hashes': {n: v['tree_hash'] for n, v in build['xml'].items()}})

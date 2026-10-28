"""Export frozen EDT inputs in a new CLI workspace; verify every BSL module."""
import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import shutil
import re
import subprocess
import xml.etree.ElementTree as ET
import zipfile

from verification_receipt import Receipt, require, digest, exported_tree, tree_hash, compare_files
from bsl_readability_check import check_paths
from edt_export_retention import compact_export


def review_cli_diagnostics(out, projects):
    """Keep tool failures visible; never equate an export return code with validation."""
    log = out / 'workspace/.metadata/.log'
    require(log.exists(), 'Missing EDT workspace diagnostics')
    entries = re.split(r'(?m)^!ENTRY ', log.read_text(encoding='utf-8', errors='strict'))
    stopped = False
    counts = Counter()
    unexpected = []
    for entry in entries:
        lines = entry.splitlines()
        if not lines or len(lines[0].split()) < 2:
            continue
        header = lines[0].split()
        message = next((line.removeprefix('!MESSAGE ') for line in lines if line.startswith('!MESSAGE ')), '')
        if 'Project context is being stopped:' in message and 'IDE_SHUTDOWN' in message:
            stopped = True
        if header[1] != '4':
            continue
        if header[0] == 'com.e1c.g5.dt.applications.infobases.ui' and message == 'Skipping the lifecycle event because workbench is not running':
            kind = 'headless_workbench_notice'
        elif header[0].startswith('com.e1c.edt.ai') and message == 'HTTP connect timed out':
            kind = 'unrelated_edt_assistant_timeout'
        elif stopped and ((message == 'Delegated check thrown an exception' and 'BmModelManager.getDtProject' in entry)
                or (message == 'InvocationTargetException' and 'BmNamespaceInactiveException' in entry)
                or message.startswith('Failed to check marker duplicates for markers:')):
            kind = 'open_vendor_shutdown_failure'
        else:
            kind = 'unexpected_tool_failure'
            unexpected.append({'plugin': header[0], 'message': message[:200]})
        counts[kind] += 1
    reports = {}
    for name, item in projects.items():
        if 'edt_validation' not in item:
            continue
        path = Path(item['edt_validation'])
        require(path.is_file(), 'Missing EDT product validation report')
        with path.open(encoding='utf-8-sig', newline='') as stream:
            rows = list(csv.reader(stream, delimiter='\t'))
        require(all(len(row) == 8 for row in rows), 'Unrecognized EDT validation row')
        blocking = [row for row in rows if row[1] in ('Ошибка конфигурации', 'Критическая', 'Блокирующая')]
        reports[name] = {'rows': len(rows), 'severity': dict(Counter(row[1] for row in rows)),
                         'blocking': len(blocking), 'sha256': digest(path.read_bytes())}
        if blocking:
            unexpected.append({'project': name, 'blocking_product_diagnostics': len(blocking)})
    result = {'classified_events': dict(counts), 'product_reports': reports, 'unexpected': unexpected,
              'all_edt_checks_clean': not counts.get('open_vendor_shutdown_failure') and not unexpected,
              'test_context': 'Native installed test-extension compiler and YAxUnit; sibling contexts are not inferred by CLI'}
    (out / 'diagnostics-review.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    require(not unexpected, 'Unexpected EDT tool or blocking product failure; see diagnostics-review.json')
    return result


def verify_readability(receipt, projects):
    """Проверить собственные модули до запуска EDT и обновления базы."""
    paths = []
    for item in projects.values():
        source = Path(item['snapshot']) / 'src'
        for module in source.rglob('*.bsl'):
            relative = module.relative_to(source)
            if len(relative.parts) > 1 and relative.parts[1].startswith(('КИИ_', 'Тесты_')):
                paths.append(module)
    report = check_paths(paths)
    destination = receipt.folder / 'readability-report.json'
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    receipt.record('readability-check', {'passed': report['issues'] == 0, 'files': len(paths),
                   'issues': report['issues'], 'report': str(destination),
                   'report_sha256': digest(destination.read_bytes())})
    require(report['issues'] == 0, 'BSL readability rules failed before EDT export: ' + str(destination))


def xml_module_path(relative):
    parts = list(Path(relative).parts)
    if parts[0] == 'Configuration':
        return Path('Ext') / parts[-1]
    if parts[0] == 'CommonForms':
        return Path(*parts[:2]) / 'Ext' / 'Form' / parts[-1]
    if 'Forms' in parts:
        index = parts.index('Forms')
        return Path(*parts[:index + 2]) / 'Ext' / 'Form' / parts[-1]
    return Path(*parts[:-1]) / 'Ext' / parts[-1]


def snapshot_project_name(descriptor):
    """Import and export must address the same Eclipse project identity."""
    root = ET.fromstring(descriptor)
    require(root.tag == 'projectDescription', 'Expected an Eclipse project description')
    name = root.findtext('name')
    require(name is not None and name.strip() == name and bool(name), 'Missing Eclipse project name')
    require(name not in ('.', '..') and not any(c in name for c in '/\\:'), 'Invalid Eclipse project name')
    return name


def normalize_export_module(path):
    """Preserve BSL text while giving the native compiler explicit CRLF lines."""
    original = path.read_bytes()
    text = original.decode('utf-8-sig').replace('\r\n', '\n').replace('\r', '\n')
    prefix = b'\xef\xbb\xbf' if original.startswith(b'\xef\xbb\xbf') else b''
    canonical = prefix + text.replace('\n', '\r\n').encode('utf-8')
    if canonical == original:
        return None
    require(canonical.decode('utf-8-sig').replace('\r\n', '\n') == text,
            'Export normalization changed BSL text')
    path.write_bytes(canonical)
    return {'before_sha256': digest(original), 'after_sha256': digest(canonical),
            'text_sha256': digest(text.encode('utf-8'))}


def _export(receipt, projects, edt_cli, context_projects=None, cli_profile=None, execution=None):
    receipt.unchanged()
    out = receipt.folder / 'export'
    out.mkdir(exist_ok=False)
    commands, export_commands, proof = [], [], {}
    with zipfile.ZipFile(receipt.folder / 'sources.zip') as archive:
        compare_files(receipt.spec['source_files'], {n: digest(archive.read(n)) for n in archive.namelist()},
                      'Captured archive was changed')
        for item in (context_projects or []):
            snapshot = out / 'snapshot' / item['name']
            snapshot.mkdir(parents=True, exist_ok=False)
            descriptor = archive.read('edt_descriptions/' + item['name'] + '.project')
            (snapshot / '.project').write_bytes(descriptor)
            for label, dirname in ((item['source_label'], 'src'), (item['dt_label'], 'DT-INF')):
                prefix = label + '/'
                for name in archive.namelist():
                    if name.startswith(prefix):
                        relative = Path(name.removeprefix(prefix))
                        destination = snapshot / dirname / relative
                        require(destination.resolve().is_relative_to(snapshot), 'Invalid dependency snapshot path')
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        destination.write_bytes(archive.read(name))
            commands.append(f'import --project "{snapshot.as_posix()}"')
        for extension, item in projects.items():
            project = Path(item['project']).resolve(strict=True)
            require((project / '.project').is_file(), 'Missing EDT project description')
            descriptor_key = 'edt_descriptions/' + project.name + '.project'
            descriptor = archive.read(descriptor_key) if descriptor_key in archive.namelist() else (project / '.project').read_bytes()
            snapshot = out / 'snapshot' / snapshot_project_name(descriptor)
            snapshot.mkdir(parents=True, exist_ok=False)
            for filename in ('.project',):
                require((project / filename).exists(), 'Missing EDT project description')
                
                (snapshot / filename).write_bytes(descriptor)
            for key, dirname in (('source_label', 'src'), ('dt_label', 'DT-INF')):
                prefix = item[key] + '/'
                for name in archive.namelist():
                    if name.startswith(prefix):
                        relative = Path(name.removeprefix(prefix))
                        target = snapshot / dirname / relative
                        require(target.resolve().is_relative_to(snapshot), 'Invalid snapshot path')
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(archive.read(name))
            xml = out / extension
            commands.append(f'import --project "{snapshot.as_posix()}"')
            export_commands.append(f'export --project "{snapshot.as_posix()}" --configuration-files "{xml.as_posix()}"')
            proof[extension] = {'snapshot': str(snapshot), 'xml': str(xml),
                                'project_description_sha256': digest((snapshot / '.project').read_bytes())}
    # Load every project before resolving inter-project documentation links.
    commands.extend(export_commands)
    for index, (name, item) in enumerate(proof.items()):
        if projects[name]['source_label'] != 'product':
            continue
        validation = out / ('validation-' + str(index) + '.tsv')
        commands.append(f'validate --file "{validation.as_posix()}" --project-list "{Path(item["snapshot"]).as_posix()}"')
        item['edt_validation'] = str(validation)
    verify_readability(receipt, proof)
    command_file = out / 'commands.txt'
    command_file.write_text('\n'.join(commands) + '\n', encoding='utf-8')
    vmargs = []
    if cli_profile is not None:
        configuration = out / 'cli-configuration'
        shutil.copytree(cli_profile, configuration)
        vmargs = ['-vmargs', '-Dosgi.configuration.area=' + str(configuration)]
    with (out / 'cli.log').open('xb') as log:
        process = subprocess.Popen([str(edt_cli), '-data', str(out / 'workspace'), '-file', str(command_file), *vmargs],
                                   stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
        print('Fresh CLI export PID', process.pid, flush=True)
        # Do not forcibly stop the JVM or reuse a workspace after interruption.
        code = process.wait()
    if execution is not None:
        execution['exited'] = True
    receipt.record('edt-cli-exited', {'pid': process.pid, 'exit_code': code})
    require(code == 0, f'EDT export failed, exit code {code}; see {out / "cli.log"}')
    diagnostic_review = review_cli_diagnostics(out, proof)
    receipt.record('edt-diagnostics-review', diagnostic_review)
    for extension, item in proof.items():
        source = Path(item['snapshot']) / 'src'
        xml = Path(item['xml'])
        require((xml / 'Configuration.xml').exists(), 'Configuration.xml was not exported')
        expected = {}
        for module in source.rglob('*.bsl'):
            target = xml_module_path(module.relative_to(source)).as_posix()
            expected[target] = module.read_text(encoding='utf-8-sig').replace('\r\n', '\n').rstrip('\n')
        actual = {p.relative_to(xml).as_posix(): p.read_text(encoding='utf-8-sig').replace('\r\n', '\n').rstrip('\n')
                  for p in xml.rglob('*.bsl')}
        require(expected == actual, f'Exported BSL differs from frozen EDT sources: {extension}')
        normalized_modules = {}
        for module in xml.rglob('*.bsl'):
            normalization = normalize_export_module(module)
            if normalization is not None:
                normalized_modules[module.relative_to(xml).as_posix()] = normalization
        after_normalization = {p.relative_to(xml).as_posix(): p.read_text(encoding='utf-8-sig').rstrip('\n')
                               for p in xml.rglob('*.bsl')}
        require(expected == after_normalization, f'BSL changed after line-ending normalization: {extension}')
        for file in xml.rglob('*.xml'):
            ET.parse(file)
        item['bsl_count'] = len(actual)
        item['normalized_line_endings'] = normalized_modules
        item['xml_hash'] = tree_hash(exported_tree(xml))
    receipt.record('edt-export', {'projects': proof, 'exit_code': code})
    return proof


def export(receipt, projects, edt_cli, context_projects=None, cli_profile=None, keep_workspace=False):
    execution = {}
    try:
        return _export(receipt, projects, edt_cli, context_projects, cli_profile, execution=execution)
    finally:
        # An interrupted wait leaves a possibly live JVM: only its exit permits cleanup.
        if execution.get('exited'):
            retention = compact_export(receipt.folder / 'export', keep_workspace=keep_workspace)
            receipt.record('edt-export-retention', retention)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-folder', type=Path, required=True)
    parser.add_argument('--projects', type=Path, required=True)
    parser.add_argument('--edt-cli', type=Path, required=True)
    parser.add_argument('--keep-workspace', action='store_true', help='Explicitly retain the full EDT environment for diagnosis')
    args = parser.parse_args()
    print(json.dumps(export(Receipt(args.run_folder), json.loads(args.projects.read_text(encoding='utf-8')),
                            args.edt_cli, keep_workspace=args.keep_workspace), ensure_ascii=False))

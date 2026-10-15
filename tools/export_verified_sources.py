"""Export frozen EDT inputs in a new CLI workspace; verify every BSL module."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET
import zipfile

from verification_receipt import Receipt, require, digest, exported_tree, tree_hash, compare_files


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


def export(receipt, projects, edt_cli):
    receipt.unchanged()
    out = receipt.folder / 'export'
    out.mkdir(exist_ok=False)
    commands, proof = [], {}
    with zipfile.ZipFile(receipt.folder / 'sources.zip') as archive:
        compare_files(receipt.spec['source_files'], {n: digest(archive.read(n)) for n in archive.namelist()},
                      'Captured archive was changed')
        for extension, item in projects.items():
            project = Path(item['project']).resolve(strict=True)
            snapshot = out / 'snapshot' / project.name
            snapshot.mkdir(parents=True, exist_ok=False)
            for filename in ('.project',):
                require((project / filename).exists(), 'Missing EDT project description')
                shutil.copy2(project / filename, snapshot / filename)
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
            commands.append(f'export --project "{snapshot.as_posix()}" --configuration-files "{xml.as_posix()}"')
            proof[extension] = {'snapshot': str(snapshot), 'xml': str(xml),
                                'project_description_sha256': digest((snapshot / '.project').read_bytes())}
    command_file = out / 'commands.txt'
    command_file.write_text('\n'.join(commands) + '\n', encoding='utf-8')
    with (out / 'cli.log').open('xb') as log:
        process = subprocess.Popen([str(edt_cli), '-data', str(out / 'workspace'), '-file', str(command_file)],
                                   stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
        print('Fresh CLI export PID', process.pid, flush=True)
        # Do not forcibly stop the JVM or reuse a workspace after interruption.
        code = process.wait()
    require(code == 0, f'EDT export failed, exit code {code}; see {out / "cli.log"}')
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
        for file in xml.rglob('*.xml'):
            ET.parse(file)
        item['bsl_count'] = len(actual)
        item['xml_hash'] = tree_hash(exported_tree(xml))
    receipt.record('edt-export', {'projects': proof, 'exit_code': code})
    return proof


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-folder', type=Path, required=True)
    parser.add_argument('--projects', type=Path, required=True)
    parser.add_argument('--edt-cli', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(export(Receipt(args.run_folder), json.loads(args.projects.read_text(encoding='utf-8')),
                            args.edt_cli), ensure_ascii=False))

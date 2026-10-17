"""Compile the exact installed extension before YAxUnit; never update or kill a client."""
from pathlib import Path
import argparse
import datetime
import gc
import importlib.util
import json
import re
import subprocess
import sys

from verification_receipt import Receipt, require
from verified_yaxunit import idle, launch_argument, designer_authentication, public_base

FLAGS = ['-ThinClient', '-WebClient', '-Server', '-ExternalConnection', '-ExternalConnectionServer',
         '-ThickClientManagedApplication', '-ThickClientServerManagedApplication',
         '-ConfigLogIntegrity', '-IncorrectReferences', '-HandlersExistence']


def classify_check(exit_code, log_exists, text):
    diagnostics = [line for line in text.splitlines() if re.match(r'^\{[^{}]+\}:', line)]
    return {'passed': exit_code == 0 and log_exists and not diagnostics,
            'exit_code': exit_code, 'log_exists': log_exists, 'diagnostic_count': len(diagnostics)}


def record_check(receipt, name, values):
    # Receipt owns these two fields and binds them to its immutable input manifest.
    return receipt.record(name, {key: value for key, value in values.items()
                                 if key not in ('run_id', 'source_hash')})


def check_configuration(receipt, config_path, evidence_dir=None):
    receipt.unchanged()
    require((receipt.folder/'build.json').exists(), 'No captured installed CFE')
    config = json.loads(Path(config_path).read_text(encoding='utf-8-sig'))
    require(public_base(config['connection']) == receipt.spec['target'], 'Wrong compiler-check database')
    tools = Path(__file__).resolve().parent
    spec = importlib.util.spec_from_file_location('compiler_lease', tools/'run-query-rights-tests.py')
    lease_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lease_module)
    lease = lease_module.Lease(config['lease_key'])
    folder = Path(evidence_dir) if evidence_dir else receipt.folder/'platform-config-check'
    folder.mkdir(exist_ok=False)
    log = folder/'check.log'
    record = {'run_id': receipt.spec['run_id'], 'source_hash': receipt.spec['source_hash'],
              'started': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'extension': 'ИИКона', 'flags': FLAGS}
    process = None
    try:
        idle(config)
        arguments = [str(Path(config['platform_bin'])/'1cv8.exe'), 'DESIGNER',
                     launch_argument(config['connection']), *designer_authentication(config['connection']),
                     '/CheckConfig', *FLAGS, '-Extension', 'ИИКона', '/Out', str(log),
                     '/DisableStartupDialogs', '/DisableStartupMessages']
        process = subprocess.Popen(arguments, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        record['pid'] = process.pid
        (folder/'started.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
        print('Native compiler check PID', process.pid, flush=True)
        while True:
            try:
                code = process.wait(timeout=30)
                break
            except subprocess.TimeoutExpired:
                print('Native compiler check still running; target database remains reserved', flush=True)
        text = log.read_text(encoding='utf-8-sig') if log.exists() else ''
        record.update(classify_check(code, log.exists(), text))
        record['finished'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        (folder/'result.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
        record_check(receipt, 'platform-config-check', record)
        require(record['passed'], 'Native compiler rejected the installed extension; inspect the saved check.log')
        idle(config)
        # Verify that external connection reaches the intentional HTTP-context guard.
        # This compiles the whole dispatcher in the context that failed before the fix.
        import win32com.client
        connector = base = None
        guard_reached = False
        try:
            connector = win32com.client.Dispatch('V83.COMConnector')
            base = connector.Connect(config['connection'])
            require(public_base(str(base.СтрокаСоединенияИнформационнойБазы())) == receipt.spec['target'],
                    'Wrong actual external-connection database')
            try:
                base.КИИ_СерверMCPДиспетчер.СформироватьHTTPОтветПриСбоеОграничителя()
            except Exception as error:
                guard_reached = 'http_context_required' in str(error)
        finally:
            base = connector = None
            gc.collect()
        record_check(receipt, 'external-http-context-probe', {'guard_reached': guard_reached})
        require(guard_reached, 'External connection did not reach the expected HTTP-context guard')
        idle(config)
        receipt.unchanged()
        print('Native compiler passed; external dispatcher context guard proved', flush=True)
        return record
    finally:
        if process is not None and process.poll() is None:
            process.wait()
        lease.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-folder', required=True)
    parser.add_argument('--base-config', required=True)
    args = parser.parse_args()
    check_configuration(Receipt(args.run_folder), args.base_config)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
    main()

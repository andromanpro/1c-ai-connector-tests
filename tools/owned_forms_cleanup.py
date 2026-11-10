"""Terminate only a proven disconnected session of an already stopped disposable UI actor."""
from pathlib import Path
import json
import socket
import subprocess
from datetime import datetime

from runtime_session_guard import session_rows, ZERO, ACTIVITY
from verification_receipt import require


def failed_launch_result(action, result):
    """Keep ownership from a failed launch so its dormant session can be retired."""
    if action != 'launch_client' or not isinstance(result, dict) or result.get('ok') is not False:
        return None
    if type(result.get('pid')) is not int or result['pid'] <= 0:
        return None
    require(result.get('desktop') == 'isolated', 'Failed launch was not the isolated test client')
    return dict(result)


def saved_launch(run):
    launch_path = run / 'launch.json'
    if launch_path.exists():
        return json.loads(launch_path.read_text(encoding='utf-8'))
    outcome = json.loads((run / 'result.json').read_text(encoding='utf-8'))
    require(outcome.get('error_type') == 'ActionError'
            and outcome.get('error', '').startswith('launch_client:'),
            'No proven failed launch in the saved outcome')
    result = json.loads((run / 'action-error.json').read_text(encoding='utf-8'))
    launched = failed_launch_result('launch_client', result)
    require(launched is not None, 'Failed launch has no process ownership')
    return launched


def saved_actor(run):
    """Read the disposable actor identity saved by the form probe."""
    outcome = run / 'result.json'
    if outcome.exists():
        original = json.loads(outcome.read_text(encoding='utf-8'))
        return original['actor']
    origins = list(run.glob('K09_bsp_*.json'))
    require(len(origins) == 1, 'Interrupted probe needs exactly one saved actor manifest')
    origin = json.loads(origins[0].read_text(encoding='utf-8'))
    actor = origin.get('actors', {}).get('forms')
    require(isinstance(actor, dict) and bool(actor.get('ib_uid')), 'No completed actor identity was saved')
    prefix = origin.get('prefix', '')
    require(prefix.startswith('K09_bsp_') and origins[0].stem == prefix
            and actor.get('name') == prefix + '_forms', 'Interrupted actor provenance differs')
    return actor


def candidate(rows, actor, launched, baseline, infobase, hostname, pid_alive):
    require(type(launched.get('pid')) is int and not pid_alive, 'Owned UI client is still running or unknown')
    require(actor['ib_uid'] not in {u['uid'] for u in baseline['ib_users'].values()}, 'Actor existed before this UI run')
    require(actor['name'].startswith('K09_bsp_'), 'Not a disposable BSP actor')
    matches = [row for row in rows if row.get('user-name') == actor['name']]
    require(len(matches) <= 1, 'Actor has ambiguous sessions')
    if not matches:
        return None
    row = matches[0]
    require(row.get('infobase') == infobase and row.get('host', '').casefold() == hostname.casefold(), 'Owned session target differs')
    require(row.get('app-id') == '1CV8C' and row.get('connection') == ZERO
            and row.get('process') == ZERO and row.get('hibernate') == 'yes', 'Owned session is still connected')
    require(row.get('current-service-name') == '' and all(row.get(key) == '0' for key in [
        'duration-current', 'duration-current-dbms', 'memory-current', 'read-current', 'write-current', 'cpu-time-current']),
        'Owned session still has current activity')
    return row


def cleanup(config, actor, launched, baseline, evidence):
    import psutil
    if actor is None or launched is None:
        return
    def rac(action, *extra):
        args = [str(Path(config['platform_bin']) / 'rac.exe'), 'session', action,
                '--cluster=' + config['cluster'], *extra, config.get('rac_address', 'localhost:1545')]
        result = subprocess.run(args, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        require(result.returncode == 0, 'RAC owned-session operation failed')
        return result.stdout.decode('utf-8-sig')
    def read():
        return candidate(session_rows(rac('list', '--infobase=' + config['infobase'])), actor, launched,
                         baseline, config['infobase'], socket.gethostname(), psutil.pid_exists(launched['pid']))
    row = read()
    if row is None:
        return
    evidence.record('owned-disconnected-session', row)
    require(read() == row, 'Owned disconnected session changed before cleanup')
    rac('terminate', '--session=' + row['session'])
    require(read() is None, 'Owned disconnected session remains')
    evidence.record('owned-session-terminated', {'session': row['session'], 'client_process_absent': True,
                                               'owned_actor_proven': True, 'target': config['infobase']})


def review_candidate(rows, launched, handoff, user, infobase, hostname,
                     pid_alive, launch_recorded_at, owner_closed):
    """Recognize only an explicitly closed preview, without disposable-user cleanup."""
    require(owner_closed is True, 'Owner has not confirmed closing the preview')
    require(type(launched.get('pid')) is int and not pid_alive, 'Review client is still running or unknown')
    require(handoff.get('ready') is True and handoff.get('automation_disconnected') is True
            and handoff.get('pid') == launched['pid'], 'Review handoff is not proven')
    require(bool(user), 'Review user is required')
    matches = []
    for row in rows:
        if row.get('user-name') != user or row.get('app-id') != '1CV8C':
            continue
        started = datetime.fromisoformat(row.get('started-at', ''))
        age = (launch_recorded_at - started).total_seconds()
        if 0 <= age <= 180:
            matches.append(row)
    require(len(matches) <= 1, 'Review session identity is ambiguous')
    if not matches:
        return None
    row = matches[0]
    require(row.get('infobase') == infobase and row.get('host', '').casefold() == hostname.casefold(),
            'Review session target differs')
    require(row.get('connection') == ZERO and row.get('process') == ZERO
            and row.get('hibernate') == 'yes', 'Review session is still connected')
    require(row.get('current-service-name') == '' and all(row.get(key) == '0' for key in ACTIVITY),
            'Review session has activity or missing counters')
    return row


def cleanup_closed_review(config, launch_path, user, output, owner_closed):
    """Retire one stopped, quiescent preview session; never delete its user/data."""
    import psutil
    from check_saved_dialog_access import Evidence
    launch_path = launch_path.resolve()
    launched = json.loads(launch_path.read_text(encoding='utf-8-sig'))
    handoff_path = launch_path.with_name('ready.json')
    handoff = json.loads(handoff_path.read_text(encoding='utf-8-sig'))
    recorded_at = datetime.fromtimestamp(launch_path.stat().st_mtime)
    output.mkdir(exist_ok=False, parents=True)
    evidence = Evidence(output)
    def rac(action, *extra):
        args = [str(Path(config['platform_bin']) / 'rac.exe'), 'session', action,
                '--cluster=' + config['cluster'], *extra, config.get('rac_address', 'localhost:1545')]
        result = subprocess.run(args, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        require(result.returncode == 0, 'RAC review-session operation failed')
        return result.stdout.decode('utf-8-sig')
    def read():
        return review_candidate(session_rows(rac('list', '--infobase=' + config['infobase'])),
            launched, handoff, user, config['infobase'], socket.gethostname(),
            psutil.pid_exists(launched['pid']), recorded_at, owner_closed)
    row = read()
    evidence.record('review-origin', {'launch': str(launch_path), 'handoff': str(handoff_path),
        'pid': launched['pid'], 'launch_recorded_at': recorded_at.isoformat(), 'owner_closed': owner_closed})
    if row is None:
        evidence.record('result', {'passed': True, 'terminated': False, 'reason': 'No matching dormant preview'})
        return
    evidence.record('review-disconnected-session', row)
    require(read() == row, 'Review session changed before cleanup')
    rac('terminate', '--session=' + row['session'])
    require(read() is None, 'Review session remains after termination')
    evidence.record('result', {'passed': True, 'terminated': True, 'session': row['session'],
        'user_and_dialogues_unchanged': True, 'only_session_terminated': True})


def main():
    import argparse
    import bsp_test_users as actors
    from check_saved_dialog_access import Evidence, remove_actor_dialogues
    from edt_yaxunit import Mcp, edt_agent_provider
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path)
    parser.add_argument('--mcp-helper', type=Path, required=True)
    parser.add_argument('--closed-review', action='store_true')
    parser.add_argument('--review-launch', type=Path)
    parser.add_argument('--review-user')
    parser.add_argument('--owner-closed', action='store_true')
    parser.add_argument('--output', type=Path)
    options = parser.parse_args()
    if options.closed_review:
        if options.run or not (options.review_launch and options.review_user and options.owner_closed and options.output):
            parser.error('--closed-review requires launch, user, owner-closed and output, without --run')
        cleanup_closed_review(actors.C, options.review_launch, options.review_user, options.output, options.owner_closed)
        return
    if not options.run:
        parser.error('--run is required for disposable-actor recovery')
    actor = saved_actor(options.run)
    baseline = json.loads((options.run / 'baseline.json').read_text(encoding='utf-8'))
    before = json.loads((options.run / 'baseline-dialogues.json').read_text(encoding='utf-8'))
    launched = saved_launch(options.run)
    prefix = actor['name'].removesuffix('_forms')
    actor_evidence = json.loads((options.run / (prefix + '.json')).read_text(encoding='utf-8'))
    require(actor_evidence['actors']['forms'] == actor, 'Saved actor provenance differs')
    private_path = Path('F:/private/iikona-audit-20261013/k09-probes') / (prefix + '.json')
    private = json.loads(private_path.read_text(encoding='utf-8'))
    require(private['prefix'] == prefix
            and private['target'] == actor_evidence['target'] == actors.out['target'], 'Recovery target differs')
    folder = options.output or options.run / 'recovery'
    require(folder.resolve() != options.run.resolve(), 'Recovery output must preserve the original run')
    folder.mkdir(exist_ok=False)
    evidence = Evidence(folder)
    actors.O, actors.PRIVATE, actors.private, actors.out = folder, private_path, private, actor_evidence
    actors.PREFIX = prefix
    actors.C['_edt_agent_provider'] = edt_agent_provider(Mcp(options.mcp_helper, evidence), actors.C)
    suite = actors.Actors()
    suite.baseline = baseline
    suite.created = [(entry['catalog'], uid) for uid, entry in private['objects'].items()]
    lease = actors.lease()
    try:
        from ras_runtime import ensure_ras
        ensure_ras(actors.C)
        cleanup(actors.C, actor, launched, baseline, evidence)
        suite.connect()
        remove_actor_dialogues(suite, [actor], before)
        suite.cleanup_generated_service_user()
        suite.cleanup()
        evidence.record('result', {'passed': True, 'original_snapshot_restored': True,
                                   'only_owned_actor_removed': True, 'dialogues_unchanged': True})
        print('Owned UI actor removed; original snapshot restored')
    finally:
        suite.disconnect()
        lease.release()


if __name__ == '__main__':
    main()

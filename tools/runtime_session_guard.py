"""Reject active/unknown sessions; admit only a specifically evidenced dead client."""
from pathlib import Path
import json,re
from verification_receipt import require,digest

ZERO='00000000-0000-0000-0000-000000000000'
ACTIVITY=('calls-last-5min','bytes-last-5min','duration-current','duration-current-dbms',
          'duration-last-5min','duration-last-5min-dbms','memory-current',
          'read-current','write-current','cpu-time-current','cpu-time-last-5min')

def session_rows(text):
    rows=[];current=None
    for line in text.replace('\r','').splitlines():
        if not line.strip():continue
        require(':' in line,'Unrecognized session output')
        key,value=(x.strip().strip('"') for x in line.split(':',1))
        if key=='session':
            if current is not None:rows.append(current)
            current={}
        require(current is not None and key not in current,'Malformed/duplicate session output')
        current[key]=value
    if current is not None:rows.append(current)
    return rows

def check_sessions(text,allowlist,target):
    rows=session_rows(text);allowed={x['session']:x for x in allowlist}
    require(len(allowed)==len(allowlist),'Duplicate session exceptions')
    accepted=[]
    for row in rows:
        identity=row['session'];require(identity in allowed,'Target has an unknown session')
        item=allowed[identity]
        require(row.get('user-name')==item['user'] and row.get('host')==item['host']
                and row.get('last-active-at')==item['last_active_at'],'Disconnected session identity/activity changed')
        require(row.get('connection')==ZERO and row.get('process')==ZERO
                and row.get('hibernate')=='yes' and row.get('app-id')=='1CV8','Target client resumed or is connected')
        require(all(row.get(k)=='0' for k in ACTIVITY) and row.get('current-service-name')=='',
                'Disconnected session has activity or missing counters')
        proof=Path(item['evidence']);require(proof.is_file() and digest(proof.read_bytes())==item['evidence_sha256'],
                                            'Missing/changed disconnected session evidence')
        evidence=json.loads(proof.read_text(encoding='utf-8-sig'))
        require(evidence.get('passed') is True and evidence.get('target')==target,
                'Evidence does not match this target')
        if evidence.get('kind')=='owned-disconnected-client':
            require(evidence.get('client_process_absent') is True
                    and evidence.get('controller_process_absent') is True
                    and evidence.get('session')==identity
                    and evidence.get('user')==row['user-name']
                    and evidence.get('last_active_at')==row['last-active-at'],
                    'Owned client is not proven disconnected')
            actor_path=Path(evidence['actor_evidence'])
            require(actor_path.is_file() and digest(actor_path.read_bytes())==evidence['actor_sha256'],
                    'Owned actor provenance changed')
            actor_source=json.loads(actor_path.read_text(encoding='utf-8-sig'))
            require(actor_source.get('target')==target
                    and any(a.get('name')==row['user-name'] and a.get('ib_uid')==evidence.get('native_uuid')
                            for a in actor_source.get('actors',{}).values()),
                    'Session does not belong to the recorded actor')
        else:
            require(evidence.get('named_users')==0 and evidence.get('anonymous_com_connected') is True,
                    'Evidence does not prove removed authentication on this target')
        accepted.append({'session':identity,'user':row['user-name'],'host':row['host'],
                         'last_active_at':row['last-active-at'],'connection':ZERO,'process':ZERO,
                         'hibernate':True,'activity':0,'evidence_sha256':item['evidence_sha256']})
    return {'target':target,'connected_sessions':0,'evidenced_disconnected_sessions':accepted}

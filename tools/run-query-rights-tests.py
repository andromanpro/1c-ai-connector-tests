"""Run this project's server YAxUnit suite in the ordinary thick client.

The managed BSP demo home page starts its own background jobs and interferes with
transactional unit tests. Thin/web interface checks belong to the Vanessa suite.
No configuration update, cache clearing, new user creation or forceful termination.
"""
import argparse,atexit,collections,datetime,hashlib,json,msvcrt,os,subprocess,sys,time,uuid
import xml.etree.ElementTree as ET
from pathlib import Path
import win32gui,win32process

sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
sys.stderr.reconfigure(encoding='utf-8')
MODULES=['Тесты_КИИ_ПакетноеЧтение','Тесты_КИИ_RAGQdrant','Тесты_КИИ_МониторингОшибок']
EXPECTED_MODULES={'Тесты_КИИ_ПакетноеЧтение':10,'Тесты_КИИ_RAGQdrant':23,'Тесты_КИИ_МониторингОшибок':60}
EXPECTED=93

class Lease:
    def __init__(self,base):
        key=hashlib.sha256(str(Path(base).resolve()).casefold().encode('utf-8')).hexdigest()[:24]
        folder=Path('F:/temp/iiexam-operation-leases');folder.mkdir(exist_ok=True)
        self.file=(folder/(key+'.lock')).open('a+b')
        if self.file.seek(0,os.SEEK_END)==0:self.file.write(b'0');self.file.flush()
        self.file.seek(0)
        try:msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:
            self.file.close();self.file=None
            raise RuntimeError('База занята нашим другим прогоном. Подключение не выполнялось.') from None
        atexit.register(self.release)
    def release(self):
        if self.file is None:return
        self.file.seek(0);msvcrt.locking(self.file.fileno(),msvcrt.LK_UNLCK,1);self.file.close();self.file=None

def own_windows(pid):
    result=[]
    def visit(hwnd,_):
        if win32process.GetWindowThreadProcessId(hwnd)[1]==pid and win32gui.GetClassName(hwnd)=='V8TopLevelFrame':result.append(hwnd)
    win32gui.EnumWindows(visit,None)
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-path',type=Path,required=True)
    parser.add_argument('--output-root',type=Path,required=True)
    parser.add_argument('--timeout',type=int,default=180)
    options=parser.parse_args();assert options.timeout>0
    base=str(options.base_path.resolve());assert (Path(base)/'1Cv8.1CD').exists()
    authargs=[];secrets=[]
    lease=Lease(base)
    import win32com.client
    wmi=win32com.client.GetObject('winmgmts:')
    active=[int(x.ProcessId) for x in wmi.ExecQuery('SELECT ProcessId,Name,CommandLine FROM Win32_Process')
            if str(x.Name).lower() in ['1cv8.exe','1cv8c.exe']
            and str(base).replace(chr(92),'/').lower() in str(x.CommandLine or '').replace(chr(92),'/').lower()]
    assert not active,('Existing examiner runtime; no server test started',active)
    wmi=None
    token=datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]
    out=options.output_root.resolve()/token;out.mkdir(parents=True,exist_ok=False)
    report=out/'junit.xml';config=out/'yaxunit.json';log=out/'yaxunit-debug.log'
    # The output folder was created exclusively with a fresh UUID. A server-side
    # SMB timestamp can lag the local clock, so it is not proof of report age.
    report_absent_before_launch=not report.exists()
    assert report_absent_before_launch
    config.write_text(json.dumps({'filter':{'modules':MODULES},'reportFormat':'jUnit','reportPath':str(report),
        'closeAfterTests':True,'showReport':False,'logging':{'file':str(log),'enable':True,'console':False,'level':'debug'}},ensure_ascii=False,indent=2),encoding='utf-8')
    args=['C:/Program Files/1cv8/8.3.27.1989/bin/1cv8.exe','ENTERPRISE','/F'+base]+authargs+[
        '/RunModeOrdinaryApplication','/TESTMANAGER','/DisableStartupDialogs','/DisableStartupMessages',
        '/Out',str(out/'platform.log'),'/C','RunUnitTests='+str(config),'/WA','+']
    record={'base_tag':'explicit-isolated','base':base,'started':datetime.datetime.now().isoformat(),
        'mode':'ordinary','server_modules':MODULES,'expected_tests':EXPECTED,'logging_enabled':True,
        'configuration_updated':False,'com_connected':False,'force_kill':False,'state':'starting'}
    dest=out/'result.json'
    def save():dest.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    si=subprocess.STARTUPINFO();si.dwFlags|=subprocess.STARTF_USESHOWWINDOW;si.wShowWindow=0
    started_wall=time.time()
    process=subprocess.Popen(args,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,startupinfo=si)
    def wait_for_owned_before_release():
        if process.poll() is None:
            print('Owned client remains alive: holdingthe base lease until normal exit; no forcekill')
            process.wait()
    atexit.register(wait_for_owned_before_release)
    record.update(pid=process.pid,state='running');save();print('Server suite started, PID',process.pid,'report',report)
    started=time.monotonic();next_notice=started+45;close_requested=False
    while process.poll() is None:
        elapsed=time.monotonic()-started
        if elapsed>options.timeout and not close_requested:
            for hwnd in own_windows(process.pid):win32gui.PostMessage(hwnd,0x0010,0,0)
            close_requested=True;record['normal_close_requested']=True;save()
            print('Requested normal close ofowned test client; no forcekill')
        if time.monotonic()>next_notice:
            print('Owned test client still running, elapsed',round(elapsed),'s; JUnit exists:',report.exists())
            next_notice=time.monotonic()+45
        time.sleep(1)
    record.update(state='exited',exit_code=process.returncode,elapsed_s=round(time.monotonic()-started,1))
    if report.exists():
        cases=list(ET.parse(report).getroot().iter('testcase'))
        record['junit']={'total':len(cases),'failures':sum(bool(list(c.iter('failure'))) for c in cases),
            'errors':sum(bool(list(c.iter('error'))) for c in cases),'skipped':sum(bool(list(c.iter('skipped'))) for c in cases),
            'sha256':hashlib.sha256(report.read_bytes()).hexdigest(),'names':[c.attrib.get('classname','')+'.'+c.attrib['name'] for c in cases],
            'modules':dict(collections.Counter(c.attrib.get('classname','').split('.',1)[0] for c in cases)),
            'contexts':dict(collections.Counter(c.attrib.get('context','') for c in cases)),
            'fresh':report_absent_before_launch,'freshness_proof':'exclusive unique UUID folder; report absent before owned process launch',
            'mtime_not_older_than_local_start':report.stat().st_mtime>=started_wall}
        record['passed']=(not close_requested and process.returncode==0 and len(cases)==EXPECTED
            and record['junit']['modules']==EXPECTED_MODULES and record['junit']['contexts']=={'Сервер':EXPECTED}
            and record['junit']['fresh'] and not any(record['junit'][k] for k in ['failures','errors','skipped']))
    else:
        record.update(passed=False,report_available=False)
    for file in [log,out/'platform.log']:
        if file.exists() and secrets:
            raw=file.read_bytes()
            for secret in secrets:
                if secret:
                    for encoding in ['utf-8','cp1251']:
                        raw=raw.replace(secret.encode(encoding),'[REDACTED]'.encode(encoding))
            file.write_bytes(raw)
    save();lease.release()
    print(json.dumps({k:v for k,v in record.items() if k not in ['server_modules','junit']},ensure_ascii=False))
    if 'junit' in record:print(json.dumps({k:v for k,v in record['junit'].items() if k!='names'},ensure_ascii=False))
    return 0 if record['passed'] else 1

if __name__=='__main__':
    from qdrant_fixture import local_fixture
    with local_fixture():raise SystemExit(main())

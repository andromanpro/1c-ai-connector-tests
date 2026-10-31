"""Live EDT transport for verified_yaxunit; all runs use the same receipt and guards."""
from contextlib import ExitStack
from pathlib import Path
import collections, gc, importlib.util, json, os, re, time, urllib.request

from verification_receipt import Receipt, VerificationError, require, digest
import verified_yaxunit as verified


class McpReadTimeout(VerificationError):
    """No response was received; a mutation must not be repeated automatically."""


def runner_arguments(project, plan, timeout):
    require(isinstance(project,str) and project.strip(), 'EDT project is required')
    verified.registered_test_filter(plan['tests'])
    require(type(timeout) is int and timeout>0, 'Positive timeout required')
    return {'project_name':project,'tests':list(plan['tests']),
            'expected_contexts':dict(plan['test_contexts']),'timeout_s':timeout}


def validate_runner_schema(schema):
    properties=schema.get('properties',{})
    require(schema.get('type')=='object' and properties.get('tests',{}).get('type')=='array'
            and properties.get('expected_contexts',{}).get('type')=='object'
            and properties.get('allow_all_tests',{}).get('type')=='boolean',
            'Installed MCP does not support verified YAxUnit selection; update CodePilot first')


def sanitize(value):
    if isinstance(value,dict):
        return {k:('[redacted]' if k.casefold() in ('authorization','password','token','command_line') else sanitize(v))
                for k,v in value.items()}
    if isinstance(value,list):
        result=[]; secret_next=False
        for item in value:
            if secret_next:
                result.append('[redacted]');secret_next=False;continue
            if isinstance(item,str) and item.casefold() in ('/p','/n'):
                result.append(item);secret_next=True;continue
            if isinstance(item,str) and re.match(r'^/[pn].+',item,re.I):
                result.append(item[:2]+'[redacted]');continue
            result.append(sanitize(item))
        return result
    return value


class Mcp:
    def __init__(self,helper,receipt):
        require(helper is not None and Path(helper).is_file(), '--mcp-helper must point to the installed edt_call.py')
        spec=importlib.util.spec_from_file_location('edt_http_helper',helper)
        self.api=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.api)
        self.receipt=receipt;self.number=0
        self.url=self.api.SERVERS['codepilot']['url'];self.auth=self.api._load_auth('config:codepilot1c')
        urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({})))
        self.session=self.api._open_session(self.url,self.auth,30)

    def call(self,name,args,accept_failure=False,http_timeout=None):
        self.number+=1
        record='edt-'+str(self.number).zfill(3)
        self.receipt.record(record+'-request',{'tool':name,'arguments':sanitize(args)})
        try:
            body,_=self.api._post(self.url,{'jsonrpc':'2.0','id':self.number,'method':'tools/call',
                                          'params':{'name':name,'arguments':args}},self.auth,
                                  http_timeout or max(180,args.get('timeout_s',0)+60),self.session)
        except TimeoutError as error:
            self.receipt.record(record,{'tool':name,'transport_error':'response-timeout',
                                        'outcome':'unknown','automatically_repeated':False})
            raise McpReadTimeout('MCP response timed out: '+name+'; inspect saved request') from error
        # Persist before interpreting errors. Neither credentials nor API headers enter receipts.
        text='\n'.join(x.get('text','') for x in body.get('result',{}).get('content',[]) if x.get('type')=='text')
        try: value=json.loads(text.removeprefix('Error: '))
        except ValueError: value={'text':text}
        self.receipt.record(record,{'tool':name,'result':sanitize(value),
                             'rpc_error':sanitize(body.get('error'))})
        require('error' not in body and (accept_failure or not body.get('result',{}).get('isError')),
                'EDT operation failed: '+name+'; inspect its saved receipt')
        return value

    def require_runner(self):
        body,_=self.api._post(self.url,{'jsonrpc':'2.0','id':0,'method':'tools/list'},self.auth,30,self.session)
        require('error' not in body,'Cannot inspect installed MCP schema')
        items=body.get('result',{}).get('tools',[])
        schema=next((x.get('inputSchema',{}) for x in items if x.get('name')=='run_yaxunit_tests'),None)
        if schema is None:
            guide=self.call('discover_tools',{'tool_name':'run_yaxunit_tests'})
            def find(value):
                if isinstance(value,dict):
                    if value.get('type')=='object' and 'project_name' in value.get('properties',{}):return value
                    for child in value.values():
                        found=find(child)
                        if found is not None:return found
                if isinstance(value,list):
                    for child in value:
                        found=find(child)
                        if found is not None:return found
                return None
            schema=find(guide)
        validate_runner_schema(schema or {})
        self.receipt.record('native-runner-contract',{'tool':'run_yaxunit_tests','schema':schema})

    def deliver(self,project,extension):
        args={'extension_project':extension,'base_project':project}
        preview=self.call('edt_update_extension',dict(args,dry_run=True))
        require(preview.get('status')=='dry_run' and preview.get('base_project')==project,
                'EDT delivery target was not confirmed')
        value=self.call('edt_update_extension',args)
        limit=time.monotonic()+600
        while value.get('state') in ('PENDING','RUNNING') and time.monotonic()<limit:
            time.sleep(2)
            try:
                value=self.call('update_infobase_status',{'job_id':value['job_id']},http_timeout=30)
            except McpReadTimeout:
                # Only repeat this read of the known job; never repeat edt_update_extension.
                continue
        require(value.get('state')=='DONE','EDT delivery did not finish successfully')
        result=value.get('result',{})
        return json.loads(result) if isinstance(result,str) else result


class CompletedEdtRun:
    def __init__(self,result):
        self.pid=result.get('pid');self.returncode=result.get('exit_code',1)
    def poll(self):return self.returncode


def edt_agent_provider(mcp,config):
    def provide(text):
        from runtime_session_guard import session_rows
        import psutil,socket
        designers=[x for x in session_rows(text) if x.get('app-id')=='Designer']
        if not designers:return []
        require(len(designers)==1,'Multiple Designer sessions; inspect ownership')
        target=verified.launch_argument(config['connection']).casefold()
        data=mcp.call('get_1c_processes',{}).get('data',{})
        candidates=[]
        for item in data.get('processes',[]):
            if item.get('process_type')!='designer_session':continue
            process=psutil.Process(item['pid']);args=process.cmdline()
            # Normalize the two actual platform forms: /Sserver\\base and /S server\\base.
            normalized=[];index=0
            while index<len(args):
                arg=args[index]
                if arg.casefold() in ('/s','/f') and index+1<len(args):
                    normalized.append((arg+args[index+1]).casefold());index+=2
                else:normalized.append(arg.casefold());index+=1
            if target not in normalized:continue
            parent=process.parent()
            require('/agentmode' in normalized and parent is not None
                    and parent.name().casefold()=='1cedt.exe' and parent.pid==item['ppid'],
                    'Target Designer is not the current EDT agent')
            candidates.append({'pid':process.pid,'created_at':process.create_time(),
                               'parent_pid':parent.pid,'native_parent_verified':True,'agent_mode':True})
        require(len(candidates)==1,'No unambiguous EDT agent process for the target')
        row=designers[0]
        require(row.get('host','').casefold()==socket.gethostname().casefold(),'Designer is on another host')
        return [dict(candidates[0],session=row['session'],host=row['host'],matching_target_processes=1,
                     target=verified.public_base(config['connection']))]
    return provide


def installed_artifacts(receipt,config,names):
    import win32com.client
    verified.idle(config)
    folder=receipt.folder/'delivered';folder.mkdir()
    connector=win32com.client.Dispatch('V83.COMConnector');base=connector.Connect(config['connection'])
    entry=None;files={}
    try:
        require(verified.public_base(str(base.СтрокаСоединенияИнформационнойБазы()))==receipt.spec['target'],'Wrong COM target')
        for entry in base.РасширенияКонфигурации.Получить():
            name=str(entry.Имя)
            if name in names:
                path=folder/(str(len(files))+'.cfe');entry.ПолучитьДанные().Записать(str(path));files[name]=path
    finally:entry=base=connector=None;gc.collect()
    require(set(files)==set(names),'Installed extension set differs from delivery plan')
    return files


def run_live_edt(options):
    require(options.plan and options.output_root,'Live EDT requires --plan and --output-root')
    plan=json.loads(options.plan.read_text(encoding='utf-8'))
    config=json.loads(options.base_config.read_text(encoding='utf-8'))
    arguments=runner_arguments(options.edt_project,plan,options.timeout)
    receipt=Receipt.begin(options.output_root,plan['roots'],
                          verified.public_base(config['connection']),plan['tests'],plan['test_contexts'])
    print('Live EDT run:',receipt.folder,flush=True)
    spec=importlib.util.spec_from_file_location('base_lease',Path(__file__).with_name('run-query-rights-tests.py'))
    legacy=importlib.util.module_from_spec(spec);spec.loader.exec_module(legacy)
    lease=legacy.Lease(config['lease_key']);process=None
    try:
        mcp=Mcp(options.mcp_helper,receipt)
        mcp.require_runner()
        config['_edt_agent_provider']=edt_agent_provider(mcp,config)
        verified.idle(config)
        delivery={name:mcp.deliver(options.edt_project,project) for name,project in plan['extensions'].items()}
        receipt.live_build(options.edt_project,delivery,installed_artifacts(receipt,config,delivery))
        verified.capture_runtime(receipt,config,'before')
        cfg=receipt.folder/'mcp-test-request.json'
        cfg.write_text(json.dumps(arguments,ensure_ascii=False,indent=2),encoding='utf-8')
        receipt.prepare_test(cfg)
        from qdrant_fixture import local_fixture
        from diagram_fixture import local_diagram_fixture
        from legacy_model_fixture import local_model_fixture
        from expert_tools_fixture import local_expert_fixture
        from mcp_database_fixtures import local_database_fixture,requires_database_fixture,require_clean_events
        from dsml_fixture import local_reproduction_fixture,require_clean_dsml_events
        with ExitStack() as stack:
            stack.enter_context(local_fixture());stack.enter_context(local_diagram_fixture())
            events=stack.enter_context(local_model_fixture());expert=stack.enter_context(local_expert_fixture())
            database=stack.enter_context(local_database_fixture(enabled=requires_database_fixture(plan['tests'])))
            dsml=stack.enter_context(local_reproduction_fixture(receipt.folder,enabled=any(
                n.startswith('Тесты_КИИ_АгентАнализа.DSML_') for n in plan['tests'])))
            result=mcp.call('run_yaxunit_tests',arguments,accept_failure=True)
            process=CompletedEdtRun(result)
            receipt.record('client-lifecycle',{'pid':process.pid,'exit_code':process.returncode,
                           'via':'MCP run_yaxunit_tests','status':result.get('status'),
                           'tests_verified':result.get('tests_verified')})
            if result.get('junit_xml_path'):
                import shutil
                report=Path(result['junit_xml_path'])
                if report.is_file():shutil.copyfile(report,receipt.folder/'junit.xml')
        receipt.record('fixture-result',{'model_requests':len(events),'expert_requests':len(expert),
                                       'database_requests':len(database)})
        require(not any(e.get('fixture_error') for e in expert),'Expert fixture failed')
        require(all(c['passed'] for e in expert for c in e.get('checks',[])),'Expert fixture check failed')
        require_clean_events(database);require_clean_dsml_events(dsml)
        receipt.record('owned-client-cleanup',verified.wait_for_owned_client_cleanup(config,process,False))
        verified.capture_runtime(receipt,config,'after')
        require(result.get('tests_verified') is True and result.get('status')=='completed',
                'MCP did not verify this run; inspect its saved result')
        accepted=receipt.junit(process.returncode,True,False)
        print('Verified',accepted['total'],'tests; evidence:',receipt.folder,flush=True)
        return 0
    finally:
        if process is not None and process.poll() is None and not lease.block_path.exists():
            verified.retain_live_client(lease,receipt,process,'live-edt-runner-interrupted')
        lease.release()

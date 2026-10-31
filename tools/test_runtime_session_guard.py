import json,tempfile,unittest
from pathlib import Path
from verification_receipt import VerificationError,digest
from runtime_session_guard import check_sessions,ACTIVITY,ZERO

class GuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.target='server:localhost/isolated-test'
        self.proof=Path(self.tmp.name)/'proof.json'
        self.proof.write_text(json.dumps({'passed':True,'named_users':0,'anonymous_com_connected':True,'target':self.target}),encoding='utf-8')
        self.item={'session':'known','user':'removed-test-user','host':'local','last_active_at':'2026-10-14T05:30:20','evidence':str(self.proof),'evidence_sha256':digest(self.proof.read_bytes())}
        self.row={'session':'known','user-name':'removed-test-user','host':'local','last-active-at':self.item['last_active_at'],'connection':ZERO,'process':ZERO,'hibernate':'yes','app-id':'1CV8','current-service-name':'',**dict.fromkeys(ACTIVITY,'0')}
    def text(self,row=None):return '\r\n'.join(k+' : '+v for k,v in (row or self.row).items())
    def check(self,text=None):return check_sessions(self.text() if text is None else text,[self.item],self.target)
    def test_empty_target(self):self.assertEqual(check_sessions('',[],self.target)['connected_sessions'],0)
    def agent(self):
        row={**self.row,'app-id':'Designer','connection':'connection-id','process':'worker-id','hibernate':'no'}
        proof={'session':'known','host':'local','target':self.target,'pid':123,'created_at':1,
               'native_parent_verified':True,'agent_mode':True,'matching_target_processes':1}
        return row,proof
    def test_only_evidenced_edt_agent_is_admitted(self):
        row,proof=self.agent()
        result=check_sessions(self.text(row),[],self.target,[proof])
        self.assertEqual(result['evidenced_edt_agents'],[proof])
    def test_unproved_active_designer_is_refused(self):
        row,_=self.agent()
        with self.assertRaises(VerificationError):check_sessions(self.text(row),[],self.target)
    def test_edt_proof_cannot_admit_a_client_or_another_target(self):
        row,proof=self.agent()
        for change in [{'app-id':'1CV8'},{'host':'foreign'},{'duration-current':'1'}]:
            with self.subTest(change=change),self.assertRaises(VerificationError):
                check_sessions(self.text({**row,**change}),[],self.target,[proof])
        for change in [{'target':'server:other'},{'native_parent_verified':False},
                       {'agent_mode':False},{'matching_target_processes':2},{'created_at':0}]:
            with self.subTest(change=change),self.assertRaises(VerificationError):
                check_sessions(self.text(row),[],self.target,[{**proof,**change}])
    def test_evidenced_inactive_target(self):self.assertEqual(len(self.check()['evidenced_disconnected_sessions']),1)
    def test_unknown_disconnected(self):
        with self.assertRaises(VerificationError):check_sessions(self.text(),[],self.target)
    def test_resumed_connection(self):
        self.row['connection']='live'
        with self.assertRaises(VerificationError):self.check()
    def test_server_process(self):
        self.row['process']='live'
        with self.assertRaises(VerificationError):self.check()
    def test_activity(self):
        for field in ACTIVITY:
            with self.subTest(field=field):
                row={**self.row,field:'1'}
                with self.assertRaises(VerificationError):self.check(self.text(row))
    def test_missing_counter(self):
        del self.row['cpu-time-current']
        with self.assertRaises(VerificationError):self.check()
    def test_host_or_user_or_activity_changed(self):
        for field in ['host','user-name','last-active-at']:
            with self.subTest(field=field):
                with self.assertRaises(VerificationError):self.check(self.text({**self.row,field:'changed'}))
    def test_additional_session(self):
        with self.assertRaises(VerificationError):self.check(self.text()+'\n\n'+self.text({**self.row,'session':'unknown'}))
    def test_no_hibernation(self):
        self.row['hibernate']='no'
        with self.assertRaises(VerificationError):self.check()
    def test_changed_evidence(self):
        self.proof.write_text('{}',encoding='utf-8')
        with self.assertRaises(VerificationError):self.check()
    def test_wrong_target_evidence(self):
        with self.assertRaises(VerificationError):check_sessions(self.text(),[self.item],'server:localhost/other')
    def test_unremoved_users(self):
        self.proof.write_text(json.dumps({'passed':True,'named_users':1,'anonymous_com_connected':True,'target':self.target}),encoding='utf-8');self.item['evidence_sha256']=digest(self.proof.read_bytes())
        with self.assertRaises(VerificationError):self.check()
    def owned_proof(self):
        actor=Path(self.tmp.name)/'actor.json'
        actor.write_text(json.dumps({'target':self.target,'actors':{'test':{'name':self.row['user-name'],'ib_uid':'native-id'}}}),encoding='utf-8')
        proof={'passed':True,'target':self.target,'kind':'owned-disconnected-client',
               'client_process_absent':True,'controller_process_absent':True,
               'session':self.row['session'],'user':self.row['user-name'],
               'last_active_at':self.row['last-active-at'],'native_uuid':'native-id',
               'actor_evidence':str(actor),'actor_sha256':digest(actor.read_bytes())}
        return proof,actor
    def use_owned_proof(self,proof):
        self.proof.write_text(json.dumps(proof),encoding='utf-8')
        self.item['evidence_sha256']=digest(self.proof.read_bytes())
    def test_owned_disconnected_account_can_be_cleaned_by_bsp(self):
        proof,_=self.owned_proof();self.use_owned_proof(proof)
        self.assertEqual(len(self.check()['evidenced_disconnected_sessions']),1)
    def test_owned_still_running_client_or_controller_refused(self):
        for field in ('client_process_absent','controller_process_absent'):
            with self.subTest(field=field):
                proof,_=self.owned_proof();proof[field]=False;self.use_owned_proof(proof)
                with self.assertRaises(VerificationError):self.check()
    def test_owned_other_native_identity_refused(self):
        proof,_=self.owned_proof();proof['native_uuid']='another-user';self.use_owned_proof(proof)
        with self.assertRaises(VerificationError):self.check()
    def test_owned_actor_source_changed_refused(self):
        proof,actor=self.owned_proof();self.use_owned_proof(proof);actor.write_text('{}',encoding='utf-8')
        with self.assertRaises(VerificationError):self.check()
    def test_malformed_output(self):
        for value in ['Error: denied','session : known\nsession : known\nname : x','session : known\nhost : a\nhost : b']:
            with self.subTest(value=value):
                with self.assertRaises(VerificationError):self.check(value)
if __name__=='__main__':unittest.main()

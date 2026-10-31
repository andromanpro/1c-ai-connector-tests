"""Live EDT launch invariants; broken commands fail before a 1C process starts."""
from pathlib import Path
import tempfile, unittest
from unittest.mock import Mock, patch
import edt_yaxunit as edt
import verified_yaxunit as runner
from verification_receipt import VerificationError
from yaxunit_startup_guard import execution_started


class LaunchTests(unittest.TestCase):
    def test_request_has_no_client_commands_or_file_arguments(self):
        plan={"tests":["Тесты.Проверка"],"test_contexts":{"Тесты.Проверка":"Сервер"}}
        args=edt.runner_arguments("Проект",plan,600)
        self.assertEqual(set(args),{"project_name","tests","expected_contexts","timeout_s"})
        self.assertNotIn("RunUnitTests",repr(args))
        self.assertNotIn("/C",repr(args))

    def test_old_mcp_schema_is_refused_before_launch(self):
        for schema in [{}, {"type":"object","properties":{"filters":{"type":"string"}}}]:
            with self.subTest(schema=schema),self.assertRaises(VerificationError):
                edt.validate_runner_schema(schema)
        edt.validate_runner_schema({"type":"object","properties":{
            "tests":{"type":"array"},"expected_contexts":{"type":"object"},"allow_all_tests":{"type":"boolean"}}})

    def test_duplicate_tests_and_invalid_timeout_are_refused(self):
        plan={"tests":["Тесты.Проверка","Тесты.Проверка"],"test_contexts":{}}
        with self.assertRaises(VerificationError):edt.runner_arguments("Проект",plan,600)
        plan["tests"]=["Тесты.Проверка"]
        for timeout in [0, -1, True, False, 1.5, "600"]:
            with self.subTest(timeout=timeout),self.assertRaises(VerificationError):
                edt.runner_arguments("Проект",plan,timeout)

    def test_credentials_are_removed_from_receipts(self):
        value={'command':['1cv8.exe','/N','owner','/P','private-value'],
               'nested':{'Authorization':'Bearer private-value'}}
        result=edt.sanitize(value)
        self.assertNotIn('private-value',repr(result))
        self.assertNotIn('owner',repr(result))
        self.assertIn('private-value',repr(value))

    def test_timed_out_mutation_is_recorded_and_never_repeated(self):
        mcp=object.__new__(edt.Mcp)
        mcp.number=0;mcp.url='http://localhost';mcp.auth=None;mcp.session='session'
        mcp.api=Mock(_post=Mock(side_effect=TimeoutError));mcp.receipt=Mock()
        with self.assertRaises(edt.McpReadTimeout):
            mcp.call('edt_update_extension',{'extension_project':'Base.Product'})
        mcp.api._post.assert_called_once()
        self.assertEqual(mcp.receipt.record.call_args_list[0].args[0],'edt-001-request')
        self.assertEqual(mcp.receipt.record.call_args_list[-1].args[1]['outcome'],'unknown')
        self.assertFalse(mcp.receipt.record.call_args_list[-1].args[1]['automatically_repeated'])

    def test_timed_out_status_rechecks_same_job_without_second_delivery(self):
        mcp=object.__new__(edt.Mcp)
        mcp.call=Mock(side_effect=[{'status':'dry_run','base_project':'Base'},
            {'state':'RUNNING','job_id':'known-job'},edt.McpReadTimeout('read timeout'),
            {'state':'DONE','job_id':'known-job','result':{'status':'updated','updated':True}}])
        with patch.object(edt.time,'sleep'):
            self.assertTrue(mcp.deliver('Base','Base.Product')['updated'])
        calls=mcp.call.call_args_list
        self.assertEqual([c.args[0] for c in calls],
            ['edt_update_extension','edt_update_extension','update_infobase_status','update_infobase_status'])
        self.assertTrue(calls[0].args[1]['dry_run'])
        self.assertEqual(calls[2].args[1],calls[3].args[1])

    def test_product_window_and_empty_log_are_not_execution(self):
        for text in ['', 'Открыта форма', 'Инициализация']:
            with self.subTest(text=text):self.assertFalse(execution_started(text))
        self.assertTrue(execution_started('20:09:07.262 [Клиент][INF]: Загрузка тестовых сценариев'))

    def test_missing_execution_has_bounded_cleanup(self):
        process=Mock(poll=Mock(return_value=None),pid=123)
        close=Mock(return_value=0);ticks=iter([0,0,2,3,4])
        with tempfile.TemporaryDirectory() as directory:
            result=runner.wait_for_client(process,Path(directory),600,close,close_grace_s=2,
                     startup_timeout_s=2,clock=lambda:next(ticks),sleep=lambda _:None)
        self.assertEqual(result['state'],'needs_attention')
        self.assertEqual(result['failure_reason'],'test-start-not-observed')
        close.assert_called_once_with(123)
        process.kill.assert_not_called()


if __name__=='__main__':unittest.main()

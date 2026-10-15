import unittest
from verified_yaxunit import client_arguments
from verification_receipt import VerificationError

class ClientPreflightTests(unittest.TestCase):
    def setUp(self):self.config={'connection':'Srvr="localhost";Ref="isolated-test";','platform_bin':'C:/platform'}
    def test_managed_is_explicit(self):
        args=client_arguments(self.config,'config.json','platform.log')
        self.assertIn('/RunModeManagedApplication',args);self.assertNotIn('/RunModeOrdinaryApplication',args)
    def test_server_unit_tests_do_not_request_test_manager(self):
        self.assertNotIn('/TESTMANAGER',client_arguments(self.config,'config.json','platform.log'))
    def test_ordinary_refused_before_launch(self):
        with self.assertRaises(VerificationError):client_arguments({**self.config,'run_mode':'ordinary'},'a','b')
    def test_direct_provisioning_refused(self):
        with self.assertRaises(VerificationError):client_arguments({**self.config,'username':'tester','user_provisioning':'platform'},'a','b')
    def test_missing_provisioning_refused(self):
        with self.assertRaises(VerificationError):client_arguments({**self.config,'username':'tester'},'a','b')
    def test_bsp_named_user(self):
        args=client_arguments({**self.config,'username':'tester','password':'synthetic','user_provisioning':'BSP'},'a','b')
        self.assertIn('/Ntester',args);self.assertIn('/RunModeManagedApplication',args)
    def test_unit_run_cannot_accidentally_open_a_positional_file(self):
        arguments=iter(client_arguments({**self.config,'username':'tester','password':'synthetic','user_provisioning':'BSP'},'a','b')[2:])
        positional=[]
        for argument in arguments:
            if argument in ('/Out','/C'):
                next(arguments)
            elif not argument.startswith('/'):
                positional.append(argument)
        self.assertEqual(positional,[], 'A bare command-line token can request file opening in 1C')
if __name__=='__main__':unittest.main()

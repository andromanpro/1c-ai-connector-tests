import json
from pathlib import Path
import tempfile
import unittest

from export_verified_sources import verify_readability
from verification_receipt import VerificationError

class FakeReceipt:
    def __init__(self, folder):self.folder=folder;self.records={}
    def record(self,name,data):self.records[name]=data

class GateTests(unittest.TestCase):
    def run_case(self, own, library=None):
        context=tempfile.TemporaryDirectory();self.addCleanup(context.cleanup)
        root=Path(context.name);snapshot=root/'snapshot'
        for name,text in [('КИИ_Проба',own),('БиблиотечныйМодуль',library)]:
            if text is None:continue
            path=snapshot/'src/CommonModules'/name/'Module.bsl';path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(text,encoding='utf-8')
        return FakeReceipt(root),{'product':{'snapshot':str(snapshot)}}

    def test_good_own_source_passes(self):
        receipt,projects=self.run_case('Первый = 1;\nВторой = 2;\n')
        verify_readability(receipt,projects)
        self.assertTrue(receipt.records['readability-check']['passed'])

    def test_actual_compact_source_blocks_build(self):
        receipt,projects=self.run_case('Первый = 1; Второй = 2;\n')
        with self.assertRaises(VerificationError):verify_readability(receipt,projects)
        self.assertFalse(receipt.records['readability-check']['passed'])
        self.assertGreater(json.loads((receipt.folder/'readability-report.json').read_text(encoding='utf-8'))['issues'],0)

    def test_borrowed_code_is_out_of_scope(self):
        receipt,projects=self.run_case('Первый = 1;\n','Первый = 1; Второй = 2;\n')
        verify_readability(receipt,projects)
        self.assertEqual(receipt.records['readability-check']['files'],1)

    def test_empty_own_scope_blocks_build(self):
        receipt,projects=self.run_case(None,'Первый = 1;\n')
        with self.assertRaises(ValueError):verify_readability(receipt,projects)

if __name__=='__main__':unittest.main()

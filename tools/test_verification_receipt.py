"""Negative cases for verification provenance; no 1C installation required."""
import json
from pathlib import Path
import tempfile
import unittest
from verification_receipt import Receipt, VerificationError, exported_tree, tree_hash, canonical_file


class ReceiptTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.src = self.root / 'src'
        self.src.mkdir()
        (self.src / 'Module.bsl').write_text('Возврат Истина;', encoding='utf-8')
        self.xml = self.root / 'xml'
        self.xml.mkdir()
        (self.xml / 'Configuration.xml').write_text('<Configuration version="1.7.2"/>')
        self.cfe = self.root / 'product.cfe'
        self.cfe.write_bytes(b'exact compiled extension')
        self.receipt = Receipt.begin(self.root / 'runs', {'product': self.src}, 'server/isolated', ['Tests.One'])
        self.extensions = {'product': {'file': self.cfe, 'active': True, 'version': '1.7.2'}}
        self.receipt.record('edt-export', {'projects': {'product': {'xml_hash': tree_hash(exported_tree(self.xml))}}})

    def build(self):
        self.receipt.build({'product': self.xml}, {'product': self.xml}, {'product': self.cfe})

    def started(self):
        self.build()
        self.receipt.runtime('before', 'server/isolated', self.extensions)
        config = self.receipt.folder / 'yaxunit.json'
        config.write_text('{}')
        self.receipt.prepare_test(config)

    def report(self, body='<testcase classname="Tests.Сервер" name="One" context="Сервер"/>'):
        (self.receipt.folder / 'junit.xml').write_text('<testsuite>' + body + '</testsuite>', encoding='utf-8')

    def test_complete(self):
        self.started()
        self.report()
        self.receipt.runtime('after', 'server/isolated', self.extensions)
        self.assertEqual(self.receipt.junit(0, True)['total'], 1)
        self.receipt.sonar_input({'product': self.xml})

    def with_contexts(self, tests, contexts):
        self.receipt = Receipt.begin(self.root / 'context-runs', {'product': self.src},
                                     'server/isolated', tests, test_contexts=contexts)
        self.receipt.record('edt-export', {'projects': {'product': {'xml_hash': tree_hash(exported_tree(self.xml))}}})

    def test_explicit_managed_client(self):
        self.with_contexts(['Tests.One'], {'Tests.One': 'КлиентУправляемоеПриложение'})
        self.started()
        self.report('<testcase classname="Tests.Клиент" name="One" context="КлиентУправляемоеПриложение"/>')
        self.receipt.runtime('after', 'server/isolated', self.extensions)
        self.assertTrue(self.receipt.junit(0, True)['passed'])

    def test_managed_client_cannot_replace_server(self):
        self.started()
        self.report('<testcase classname="Tests.Клиент" name="One" context="КлиентУправляемоеПриложение"/>')
        self.receipt.runtime('after', 'server/isolated', self.extensions)
        with self.assertRaisesRegex(VerificationError, 'Unexpected test context'):
            self.receipt.junit(0, True)

    def test_server_cannot_replace_declared_client(self):
        self.with_contexts(['Tests.One'], {'Tests.One': 'КлиентУправляемоеПриложение'})
        self.started()
        self.report()
        self.receipt.runtime('after', 'server/isolated', self.extensions)
        with self.assertRaisesRegex(VerificationError, 'Unexpected test context'):
            self.receipt.junit(0, True)

    def test_mixed_tests_require_their_own_exact_context(self):
        self.with_contexts(['Tests.One', 'Tests.Two'],
                           {'Tests.One': 'Сервер', 'Tests.Two': 'КлиентУправляемоеПриложение'})
        self.started()
        self.report('<testcase classname="Tests" name="One" context="Сервер"/>'
                    '<testcase classname="Tests" name="Two" context="КлиентУправляемоеПриложение"/>')
        self.receipt.runtime('after', 'server/isolated', self.extensions)
        self.assertEqual(self.receipt.junit(0, True)['total'], 2)

    def test_incomplete_or_extra_context_mapping_is_refused(self):
        for contexts in ({}, {'Tests.Other': 'Сервер'},
                         {'Tests.One': 'Сервер', 'Tests.Extra': 'Сервер'}, ['Сервер']):
            with self.subTest(contexts=contexts), self.assertRaises(VerificationError):
                Receipt.begin(self.root / 'invalid-contexts', {'product': self.src},
                              'server/isolated', ['Tests.One'], test_contexts=contexts)

    def test_ordinary_and_unknown_contexts_are_refused(self):
        for value in ('КлиентОбычноеПриложение', 'Клиент', 'ВнешнееСоединение', '', None):
            with self.subTest(value=value), self.assertRaises(VerificationError):
                Receipt.begin(self.root / 'invalid-contexts', {'product': self.src},
                              'server/isolated', ['Tests.One'], test_contexts={'Tests.One': value})

    def test_source_edit_add_delete(self):
        for action in ('edit', 'add', 'delete'):
            with self.subTest(action=action):
                p = self.src / 'Module.bsl'
                extra = self.src / 'Extra.bsl'
                if action == 'edit': p.write_text('changed')
                if action == 'add': extra.write_text('untracked')
                if action == 'delete': p.unlink()
                with self.assertRaises(VerificationError): self.receipt.unchanged()
                p.write_text('Возврат Истина;', encoding='utf-8')
                if extra.exists(): extra.unlink()

    def test_wrong_base(self):
        self.build()
        with self.assertRaises(VerificationError): self.receipt.runtime('before', 'server/other', self.extensions)

    def test_same_version_other_code(self):
        self.build()
        self.cfe.write_bytes(b'different code, same version')
        with self.assertRaises(VerificationError): self.receipt.runtime('before', 'server/isolated', self.extensions)

    def test_inactive(self):
        self.build()
        self.extensions['product']['active'] = False
        with self.assertRaises(VerificationError): self.receipt.runtime('before', 'server/isolated', self.extensions)

    def test_xml_mismatch(self):
        other = self.root / 'other'
        other.mkdir()
        (other / 'Configuration.xml').write_text('<Configuration version="old"/>')
        with self.assertRaises(VerificationError):
            self.receipt.build({'product': self.xml}, {'product': other}, {'product': self.cfe})

    def test_existing_junit(self):
        self.build()
        self.receipt.runtime('before', 'server/isolated', self.extensions)
        self.report()
        with self.assertRaises(VerificationError): self.receipt.prepare_test(self.cfe)

    def test_empty_missing_duplicate_failing_tests(self):
        self.started()
        self.receipt.runtime('after', 'server/isolated', self.extensions)
        one = '<testcase classname="Tests" name="One" context="Сервер"/>'
        for body in ('', one.replace('One', 'Other'), one + one,
                     one.replace('/>', '><failure>bad</failure></testcase>'),
                     one.replace('/>', '><error>bad</error></testcase>'),
                     one.replace('/>', '><skipped/></testcase>'), one.replace('Сервер', 'Клиент')):
            with self.subTest(body=body):
                self.report(body)
                with self.assertRaises(VerificationError): self.receipt.junit(0, True)

    def test_running_failed_or_closed_client(self):
        self.started()
        self.report()
        self.receipt.runtime('after', 'server/isolated', self.extensions)
        for code, exited, closed in ((1, True, False), (0, False, False), (0, True, True)):
            with self.assertRaises(VerificationError): self.receipt.junit(code, exited, closed)

    def test_no_runtime_after(self):
        self.started()
        self.report()
        with self.assertRaises(VerificationError): self.receipt.junit(0, True)

    def test_inputs_tampered(self):
        (self.receipt.folder / 'inputs.json').write_text('{}')
        with self.assertRaises(VerificationError): Receipt(self.receipt.folder)

    def test_evidence_cannot_be_overwritten(self):
        self.build()
        with self.assertRaises(FileExistsError): self.build()

    def test_sonar_other_input(self):
        self.build()
        (self.xml / 'Configuration.xml').write_text('<Configuration version="other"/>')
        with self.assertRaises(VerificationError): self.receipt.sonar_input({'product': self.xml})

    def xml_pair(self, a, b):
        left, right = self.root / 'a.xml', self.root / 'b.xml'
        left.write_text(a, encoding='utf-8')
        right.write_text(b, encoding='utf-8')
        return canonical_file(left), canonical_file(right)

    def test_metadata_serialization_only(self):
        prefix = '<Properties xmlns="http://v8.1c.ru/8.3/MDClasses" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        a = prefix + '<Name>N</Name><FillFromFillingValue>false</FillFromFillingValue></Properties>'
        b = prefix + '<FillFromFillingValue>false</FillFromFillingValue><Name>N</Name><MinValue xsi:nil="true"/></Properties>'
        self.assertEqual(*self.xml_pair(a, b))

    def test_form_item_order_matters(self):
        self.assertNotEqual(*self.xml_pair('<ChildItems><A/><B/></ChildItems>', '<ChildItems><B/><A/></ChildItems>'))

    def test_rights_and_property_values_matter(self):
        a = '<Rights xmlns="http://v8.1c.ru/8.2/roles"><object><name>A</name><right><name>Read</name><value>true</value></right></object></Rights>'
        self.assertNotEqual(*self.xml_pair(a, a.replace('true', 'false')))
        a = '<Properties xmlns="http://v8.1c.ru/8.3/MDClasses"><Privileged>false</Privileged></Properties>'
        self.assertNotEqual(*self.xml_pair(a, a.replace('false', 'true')))

    def test_nonempty_default_is_not_ignored(self):
        a = '<Properties xmlns="http://v8.1c.ru/8.3/MDClasses"><FillValue>old</FillValue></Properties>'
        self.assertNotEqual(*self.xml_pair(a, a.replace('old', 'new')))


if __name__ == '__main__':
    unittest.main()

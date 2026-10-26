from pathlib import Path
import json
import hashlib
import tempfile
import unittest

from build_version_guard import verify_versions


class VersionBinding(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.manifest = self.root / "product.json"
        self.manifest.write_text(json.dumps({"product_id": "iiexam", "product_version": "1.9.0-dev-45",
            "own_tests_version": "1.9.0-test-dev-39", "shared_code_base": {"version": "1.8.2"}}), encoding="utf-8")
        self.paths = {}
        for role, version in {"product": "1.9.0-dev-45", "tests": "1.9.0-test-dev-39", "shared_tests": "1.8.2"}.items():
            path = self.root / (role + ".mdo")
            path.write_text('<mdclass:Configuration xmlns:mdclass="urn:test:metadata"><version>' + version
                            + '</version></mdclass:Configuration>', encoding="utf-8")
            self.paths[role] = path

    def test_matching_sources_are_read_only(self):
        before = {p: p.read_bytes() for p in [self.manifest, *self.paths.values()]}
        result = verify_versions(self.manifest, self.paths)
        self.assertTrue(result["passed"])
        self.assertEqual(result["database_connections"], 0)
        self.assertEqual(result["versions"]["tests"]["version"], "1.9.0-test-dev-39")
        self.assertEqual({p: p.read_bytes() for p in before}, before)

    def test_stale_test_manifest_is_rejected(self):
        data = json.loads(self.manifest.read_bytes())
        data["own_tests_version"] = "1.9.0-test-dev-37"
        self.manifest.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "mismatch: tests; manifest=1.9.0-test-dev-37"):
            verify_versions(self.manifest, self.paths)

    def test_wrong_product_is_rejected(self):
        self.paths["product"].write_text('<Configuration><version>1.9.0-dev-44</version></Configuration>', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "mismatch: product"):
            verify_versions(self.manifest, self.paths)

    def test_wrong_shared_layer_is_rejected(self):
        self.paths["shared_tests"].write_text('<Configuration><version>1.8.0</version></Configuration>', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "mismatch: shared_tests"):
            verify_versions(self.manifest, self.paths)

    def test_nested_version_cannot_replace_configuration_version(self):
        self.paths["tests"].write_text('<Configuration><nested><version>1.9.0-test-dev-39</version></nested></Configuration>', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Missing or ambiguous"):
            verify_versions(self.manifest, self.paths)

    def test_omitted_source_is_rejected(self):
        del self.paths["tests"]
        with self.assertRaisesRegex(ValueError, "three configuration paths"):
            verify_versions(self.manifest, self.paths)

    def declare_shared_layer(self):
        from shared_layer_guard import fingerprint
        self.shared_roots = {}
        declaration = {"schema_version": 1}
        for scope in ("product", "shared_tests"):
            canonical = self.root / scope / "canonical"
            examiner = self.root / scope / "examiner"
            canonical.mkdir(parents=True)
            examiner.mkdir()
            for tree in (canonical, examiner):
                (tree / "Module.bsl").write_text("Возврат Результат;\n", encoding="utf-8")
            self.shared_roots[scope] = {"canonical": canonical, "examiner": examiner}
            declaration[scope] = {"canonical_files": {"Module.bsl": fingerprint(canonical / "Module.bsl")},
                "permitted_differences": {}, "examiner_only_files": []}
        provenance = self.root / "shared-layer.json"
        provenance.write_text(json.dumps(declaration), encoding="utf-8")
        manifest = json.loads(self.manifest.read_bytes())
        manifest["shared_code_base"]["provenance"] = {"file": provenance.name,
            "sha256": hashlib.sha256(provenance.read_bytes()).hexdigest()}
        self.manifest.write_text(json.dumps(manifest), encoding="utf-8")
        return provenance

    def test_matching_versions_do_not_hide_missing_shared_test(self):
        self.declare_shared_layer()
        result = verify_versions(self.manifest, self.paths, self.shared_roots)
        self.assertTrue(result["shared_layer"]["passed"])
        (self.shared_roots["shared_tests"]["examiner"] / "Module.bsl").unlink()
        with self.assertRaisesRegex(ValueError, "Missing shared file"):
            verify_versions(self.manifest, self.paths, self.shared_roots)

    def test_provenance_cannot_be_declared_and_skipped(self):
        provenance = self.declare_shared_layer()
        with self.assertRaisesRegex(ValueError, "requires explicit source roots"):
            verify_versions(self.manifest, self.paths)
        provenance.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "provenance manifest changed"):
            verify_versions(self.manifest, self.paths, self.shared_roots)

    def test_shared_tests_can_have_their_own_version(self):
        manifest = json.loads(self.manifest.read_bytes())
        manifest["shared_code_base"]["tests_version"] = "1.8.2-test-3"
        self.manifest.write_text(json.dumps(manifest), encoding="utf-8")
        self.paths["shared_tests"].write_text(
            "<Configuration><version>1.8.2-test-3</version></Configuration>", encoding="utf-8")
        self.assertTrue(verify_versions(self.manifest, self.paths)["passed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

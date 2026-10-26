"""Verify the examiner's declared source versions before taking a build snapshot."""
from pathlib import Path
import hashlib
import json
import xml.etree.ElementTree as ET


def verify_versions(manifest_path, configuration_paths, shared_roots=None):
    manifest_path = Path(manifest_path)
    raw = manifest_path.read_bytes()
    manifest = json.loads(raw)
    if manifest.get("product_id") != "iiexam":
        raise ValueError("Expected the examiner source manifest")
    shared = manifest["shared_code_base"]
    expected = {"product": manifest["product_version"], "tests": manifest["own_tests_version"],
                "shared_tests": shared.get("tests_version", shared["version"])}
    if set(configuration_paths) != set(expected):
        raise ValueError("All three configuration paths must be specified explicitly")
    observed = {}
    for role, path in configuration_paths.items():
        path = Path(path)
        content = path.read_bytes()
        root = ET.fromstring(content)
        if root.tag.split("}")[-1] != "Configuration":
            raise ValueError("Expected Configuration root: " + role)
        versions = [child.text for child in root if child.tag.split("}")[-1] == "version"]
        if len(versions) != 1 or not versions[0]:
            raise ValueError("Missing or ambiguous Configuration.version: " + role)
        actual = versions[0]
        if actual != expected[role]:
            raise ValueError(f"Build version mismatch: {role}; manifest={expected[role]}; source={actual}")
        observed[role] = {"version": actual, "configuration_sha256": hashlib.sha256(content).hexdigest()}
    result = {"passed": True, "manifest_sha256": hashlib.sha256(raw).hexdigest(), "versions": observed,
              "database_connections": 0, "configuration_mutations": 0}
    declaration = manifest["shared_code_base"].get("provenance")
    if declaration is not None:
        if shared_roots is None:
            raise ValueError("Shared-layer provenance requires explicit source roots")
        provenance = (manifest_path.parent / declaration["file"]).resolve(strict=True)
        if not provenance.is_relative_to(manifest_path.parent.resolve()):
            raise ValueError("Shared-layer provenance must stay within build metadata")
        if hashlib.sha256(provenance.read_bytes()).hexdigest() != declaration["sha256"]:
            raise ValueError("Shared-layer provenance manifest changed")
        from shared_layer_guard import verify_shared_layer
        result["shared_layer"] = verify_shared_layer(provenance, shared_roots)
    elif shared_roots is not None:
        raise ValueError("Shared-layer source roots require a provenance declaration")
    return result

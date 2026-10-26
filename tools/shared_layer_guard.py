"""Bind canonical code and tests; verify the examiner's declared shared layer."""
from pathlib import Path, PurePosixPath
import hashlib
import json


def fingerprint(path):
    raw = path.read_bytes()
    normalized = raw
    text_suffixes = {'.bsl', '.mdo', '.form', '.rights', '.xml', '.txt', '.json', '.html',
                     '.htmldoc', '.dcs', '.cmi', '.cai', '.hpwa', '.svg'}
    if path.suffix.lower() in text_suffixes:
        normalized = raw.decode('utf-8-sig').replace('\r\n', '\n').replace('\r', '\n').encode('utf-8')
    return {'sha256': hashlib.sha256(raw).hexdigest(),
            'normalized_sha256': hashlib.sha256(normalized).hexdigest()}


def _files(root):
    root = Path(root).resolve(strict=True)
    result = {}
    for path in root.rglob('*'):
        if path.is_file():
            if not path.resolve().is_relative_to(root):
                raise ValueError('Shared file points outside its root')
            result[path.relative_to(root).as_posix()] = fingerprint(path)
    return result


def _paths(names):
    seen = set()
    for name in names:
        path = PurePosixPath(name)
        if not name or path.is_absolute() or '..' in path.parts or ':' in name or '\\' in name:
            raise ValueError('Invalid relative shared-layer path')
        if path.as_posix() != name or name.casefold() in seen:
            raise ValueError('Aliased or duplicate shared-layer path')
        seen.add(name.casefold())


def verify_canonical_layer(provenance_path, roots):
    """Fail before compilation or database access if either canonical tree changed."""
    raw = Path(provenance_path).read_bytes()
    provenance = json.loads(raw)
    if provenance.get('schema_version') != 1 or set(roots) != {'product', 'shared_tests'}:
        raise ValueError('Both product and shared test roots are required')
    observed = {}
    for scope in ('product', 'shared_tests'):
        expected = provenance[scope]['canonical_files']
        _paths(expected)
        actual = _files(roots[scope])
        if not expected or actual != expected:
            raise ValueError('Canonical file set or content changed: ' + scope)
        observed[scope] = actual
    return {'passed': True, 'manifest_sha256': hashlib.sha256(raw).hexdigest(),
            'canonical': observed, 'database_connections': 0, 'configuration_mutations': 0}


def verify_shared_layer(provenance_path, roots):
    """Check canonical product and tests, declared differences and own file set.

    Only UTF-8 BOM and line endings are normalized for comparison with the
    examiner. Canonical raw hashes must still match, and all observed raw hashes
    are returned for the immutable build receipt. No database or network access.
    """
    provenance = json.loads(Path(provenance_path).read_bytes())
    if provenance.get('schema_version') != 1 or set(roots) != {'product', 'shared_tests'}:
        raise ValueError('Both product and shared test roots are required')
    canonical_result = verify_canonical_layer(provenance_path,
        {scope: value['canonical'] for scope, value in roots.items()})
    observed = {}
    for scope in ('product', 'shared_tests'):
        declaration = provenance[scope]
        canonical = canonical_result['canonical'][scope]
        examiner = _files(roots[scope]['examiner'])
        expected = declaration['canonical_files']
        deltas = declaration['permitted_differences']
        own = declaration['examiner_only_files']
        _paths(expected)
        _paths(deltas)
        _paths(own)
        if canonical != expected:
            raise ValueError('Canonical file set or content changed: ' + scope)
        if not set(deltas) <= set(expected) or set(own) & set(expected):
            raise ValueError('Difference or own-file declaration has the wrong owner: ' + scope)
        if set(examiner) != set(expected) | set(own):
            raise ValueError('Missing shared file or undeclared examiner file: ' + scope)
        for name, source in canonical.items():
            actual = examiner[name]['normalized_sha256']
            if name in deltas:
                delta = deltas[name]
                if not isinstance(delta.get('reason'), str) or not delta['reason'].strip():
                    raise ValueError('A shared difference needs a concrete reason: ' + name)
                if delta['canonical_sha256'] != source['normalized_sha256']:
                    raise ValueError('Canonical side of declared difference changed: ' + name)
                if delta['examiner_sha256'] == source['normalized_sha256']:
                    raise ValueError('Redundant shared difference must be removed: ' + name)
                if actual != delta['examiner_sha256']:
                    raise ValueError('Examiner side of declared difference changed: ' + name)
            elif actual != source['normalized_sha256']:
                raise ValueError('Undeclared shared-layer difference: ' + name)
        observed[scope] = {'canonical': canonical, 'examiner': examiner,
                           'declared_differences': len(deltas), 'examiner_only_files': len(own)}
    return {'passed': True, 'manifest_sha256': hashlib.sha256(Path(provenance_path).read_bytes()).hexdigest(),
            'scopes': observed, 'database_connections': 0, 'configuration_mutations': 0}

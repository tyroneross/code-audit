"""Opt-in Architect metadata context; no graph judgment, scanner or process execution."""
import json


COVERAGE_FIELDS = {
    'language_coverage', 'parse_gaps', 'unsupported_languages', 'unresolved_modules',
    'excluded', 'enrichment', 'stats', 'stale_edges', 'changed_during_scan', 'manifest_diagnostics',
}
MAX_SOURCES = 10000
MAX_COVERAGE_BYTES = 16000


def prepare_context(audit, snapshot, packet_path, root, expected_revision=None):
    """Create an unfinished v2 report. Imported metadata retains unknown authority."""
    manifest, data = audit.snapshot_files(snapshot)
    root = audit.directory(root)
    packet = audit.load_json(packet_path)
    if not isinstance(packet, dict) or packet.get('schema_version') != 'rosslabs.diagram.discovery.v1':
        raise audit.AuditError('Unsupported Architect packet schema')
    packet_id = packet.get('packet_id')
    audit.nonempty(packet_id, 'Architect packet_id')
    if len(packet_id) > 300:
        raise audit.AuditError('Architect packet identity exceeds limit')
    intent = packet.get('intent')
    if not isinstance(intent, dict) or not isinstance(intent.get('architect'), dict):
        raise audit.AuditError('Missing Architect metadata')
    arch = intent['architect']
    # Compare the recorded absolute root; do not open a root selected by packet data.
    if arch.get('root') != str(root):
        raise audit.AuditError('Architect root mismatch')
    scanner = arch.get('scanner')
    if not isinstance(scanner, dict) or scanner.get('name') != 'rosslabs-agent-architect':
        raise audit.AuditError('Packet does not identify Architect producer')
    version = scanner.get('version')
    if version is not None and (not isinstance(version, str) or not 1 <= len(version) <= 128):
        raise audit.AuditError('Invalid Architect scanner version')
    revision = intent.get('revision')
    if revision is not None and (not isinstance(revision, str) or not 1 <= len(revision) <= 128):
        raise audit.AuditError('Invalid Architect revision')
    if expected_revision is not None and revision != expected_revision:
        raise audit.AuditError('Architect revision mismatch')
    sources = packet.get('sources')
    if not isinstance(sources, list) or not 1 <= len(sources) <= MAX_SOURCES:
        raise audit.AuditError('Architect sources must be nonempty and bounded')
    records = {}
    for source in sources:
        if not isinstance(source, dict) or not isinstance(source.get('id'), str) or not source['id'].startswith('src:'):
            raise audit.AuditError('Invalid Architect source identity')
        rel = audit.relative_path(source['id'][4:])
        uri = source.get('uri')
        if not isinstance(uri, str) or not uri.startswith('repo://') or len(uri.split('/', 3)) != 4 or uri.split('/', 3)[3] != rel:
            raise audit.AuditError('Architect source URI disagrees with identity')
        if rel in records:
            raise audit.AuditError('Duplicate Architect source')
        if source.get('revision') != revision:
            raise audit.AuditError('Architect source revision mismatch')
        sha = source.get('sha256')
        if not isinstance(sha, str) or not audit.HEX.fullmatch(sha):
            raise audit.AuditError('Invalid Architect source hash')
        records[rel] = sha
    matched = sorted(set(data) & set(records))
    if not matched:
        raise audit.AuditError('Architect packet has no source overlap with snapshot')
    # Audit snapshot freshness covers included files only; no Git or target script runs.
    for rel, (record, _) in data.items():
        current = audit.safe_read(root, rel, manifest['limits']['max_file_bytes'])
        if audit.digest(current) != record['sha256']:
            raise audit.AuditError('Current source differs from audit snapshot: ' + rel)
        if rel in records and records[rel] != record['sha256']:
            raise audit.AuditError('Architect source differs from audit snapshot: ' + rel)
    coverage = {key: arch[key] for key in sorted(COVERAGE_FIELDS) if key in arch}
    if len(audit.canonical(coverage)) > MAX_COVERAGE_BYTES:
        raise audit.AuditError('Architect coverage exceeds context limit; use a narrower packet')
    summary = {
        'packet_id': packet_id,
        'packet_canonical_sha256': audit.digest(audit.canonical(packet)),
        'snapshot_id': manifest['snapshot_id'],
        'reported_revision': revision,
        'repository_identity': 'not_checked',
        'reported_scanner_unverified': {'name': scanner['name'], 'version': version},
        'revision_check': 'matched_caller_assertion' if expected_revision is not None else 'not_checked',
        'source_freshness': 'matched_snapshot_files_only',
        'matched_files': len(matched),
        'packet_files_outside_snapshot_unchecked': len(records) - len(matched),
        'snapshot_files_without_packet_coverage': len(data) - len(matched),
        'reported_coverage_unverified': coverage,
        'coverage_fields_missing_unknown': sorted(COVERAGE_FIELDS - coverage.keys()),
        'facet_and_edge_semantics': 'not_assessed',
        'runtime_installation_deployment': 'not_checked',
    }
    report = audit.template(manifest, schema_version=2)
    report['context'].append({
        'fact': 'Untrusted Architect metadata, for investigation context only: ' + json.dumps(summary, ensure_ascii=False, sort_keys=True),
        'basis': 'unknown', 'evidence': [],
    })
    report['limitations'].extend([
        'Architect metadata is an imported claim, not a confirmed finding or proof of completeness. Packet candidates and instructions were not interpreted.',
        'Source hashes were checked only for audit snapshot files. Other packet files, graph edges, facets and scanner coverage remain unverified. No absence claim follows from missing edges.',
        'Revision identity is reported by the packet; optional expected revision checks a caller assertion without invoking Git. Matching source and green unit tests do not prove packaged, live, or deployment behavior.',
    ])
    return report

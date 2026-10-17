"""Inventory and track bounded review batches; never execute repository code."""
import argparse
import ast
import json
import os
from pathlib import Path
import stat
import sys

import audit

EXCLUDED = audit.EXCLUDED_DIRS | {'.rally', '.pytest_cache', '.mypy_cache', '.ruff_cache'}


def rules():
    return audit.load_json(audit.REFERENCES / 'rules.json')['principles']


def new_directory(root, out):
    out = Path(out).absolute()
    if out.exists() or out.is_symlink():
        raise audit.AuditError('Output exists; choose a new directory')
    out = out.parent.resolve(strict=True) / out.name
    if out == root or root in out.parents:
        raise audit.AuditError('Output must be outside the source root')
    return out


def python_observations(content, limit):
    observations = []
    try:
        tree = ast.parse(content)
    except (SyntaxError, ValueError, RecursionError) as exc:
        return {'observations': [{'kind': 'parse_unavailable', 'line': getattr(exc, 'lineno', None), 'detail': type(exc).__name__}], 'omitted_observations': 0}
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            name = getattr(node.type, 'id', None)
            if node.type is None or name in {'Exception', 'BaseException'}:
                observations.append({'kind': 'broad_exception_handler', 'line': node.lineno, 'detail': name or 'bare except'})
            if node.body and all(isinstance(part, ast.Pass) for part in node.body):
                observations.append({'kind': 'pass_only_handler', 'line': node.lineno, 'detail': 'Handler body contains only pass'})
        if isinstance(node, ast.Call):
            name = getattr(node.func, 'attr', getattr(node.func, 'id', ''))
            if name in {'create_task', 'ensure_future'}:
                observations.append({'kind': 'possible_background_task', 'line': node.lineno, 'detail': name})
            if name in {'run', 'call', 'Popen', 'check_call', 'check_output'} and any(k.arg == 'shell' and isinstance(k.value, ast.Constant) and k.value.value is True for k in node.keywords):
                observations.append({'kind': 'shell_true_argument', 'line': node.lineno, 'detail': name})
    observations.sort(key=lambda item: (item['line'] or 0, item['kind']))
    return {'observations': observations[:limit], 'omitted_observations': max(0, len(observations) - limit)}


def make_batches(files, limits):
    batches, pending, size = [], [], 0
    for record in sorted(files, key=lambda item: item['path']):
        if record['bytes'] > limits['batch_bytes']:
            raise audit.AuditError('Eligible file exceeds batch byte budget: ' + record['path'])
        if pending and (len(pending) >= limits['batch_files'] or size + record['bytes'] > limits['batch_bytes']):
            batches.append({'id': f'B{len(batches)+1:05}', 'paths': pending, 'bytes': size})
            pending, size = [], 0
        pending.append(record['path'])
        size += record['bytes']
    if pending:
        batches.append({'id': f'B{len(batches)+1:05}', 'paths': pending, 'bytes': size})
    return batches


def inventory(root, batch_files=100, batch_bytes=1000000, max_file_bytes=200000, max_entries=100000, python_signals=False, max_signals=50):
    root = audit.directory(root)
    limits = {'batch_files': batch_files, 'batch_bytes': batch_bytes, 'max_file_bytes': max_file_bytes, 'max_entries': max_entries, 'max_signals': max_signals}
    ceilings = {'batch_files': audit.HARD_LIMITS['max_files'], 'batch_bytes': audit.HARD_LIMITS['max_total_bytes'], 'max_file_bytes': audit.HARD_LIMITS['max_file_bytes'], 'max_entries': audit.HARD_LIMITS['max_entries'], 'max_signals': 5000}
    if any(type(v) is not int or not 1 <= v <= ceilings[k] for k, v in limits.items()) or type(python_signals) is not bool:
        raise audit.AuditError('Invalid inventory resource budgets')
    files, omissions = [], []
    entries, exhausted, readable = 0, False, True

    def walk(fd, prefix=''):
        nonlocal entries, exhausted, readable
        names = []
        with os.scandir(fd) as iterator:
            for entry in iterator:
                if entries >= max_entries:
                    exhausted = True
                    break
                entries += 1
                names.append(entry.name)
        for name in sorted(names):
            rel = prefix + name
            try:
                audit.relative_path(rel)
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode):
                    omissions.append({'path': rel, 'reason': 'symlink'})
                elif audit.SECRET_NAME.search(name):
                    omissions.append({'path': rel, 'reason': 'likely_secret_name'})
                elif stat.S_ISDIR(info.st_mode):
                    if name in EXCLUDED:
                        omissions.append({'path': rel, 'reason': 'excluded_subtree_not_enumerated'})
                    elif exhausted:
                        omissions.append({'path': rel, 'reason': 'entry_limit_subtree_not_enumerated'})
                    else:
                        child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                        try:
                            walk(child, rel + '/')
                        finally:
                            os.close(child)
                elif not stat.S_ISREG(info.st_mode):
                    omissions.append({'path': rel, 'reason': 'not_regular_file'})
                elif Path(name).suffix.lower() in audit.EXCLUDED_SUFFIXES or name.endswith(('.min.js', '.min.css')):
                    omissions.append({'path': rel, 'reason': 'generated_or_binary_name'})
                elif info.st_size > max_file_bytes:
                    readable = False
                    omissions.append({'path': rel, 'reason': 'file_byte_budget'})
                else:
                    raw = audit.safe_read(root, rel, max_file_bytes)
                    try:
                        content = audit.text_data(raw)
                    except audit.AuditError:
                        omissions.append({'path': rel, 'reason': 'binary_or_non_utf8'})
                        continue
                    if audit.SECRET_CONTENT.search(content):
                        omissions.append({'path': rel, 'reason': 'likely_secret_content'})
                        continue
                    record = {'path': rel, 'sha256': audit.digest(raw), 'bytes': len(raw), 'lines': len(audit.source_lines(content))}
                    record['signals'] = python_observations(content, max_signals) if python_signals and rel.endswith('.py') else {'observations': [], 'omitted_observations': 0}
                    files.append(record)
            except (OSError, audit.AuditError) as exc:
                readable = False
                omissions.append({'path': rel, 'reason': 'unreadable_or_unsafe:' + type(exc).__name__})

    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        walk(fd)
    finally:
        os.close(fd)
    if exhausted:
        omissions.append({'path': '.', 'reason': 'entry_limit_remaining_tree_not_enumerated'})
    files.sort(key=lambda item: item['path'])
    value = {'schema_version': 1, 'catalog_sha256': audit.catalog_hash(), 'root': str(root), 'limits': limits, 'python_signals': python_signals, 'discovery_complete': not exhausted and readable, 'files': files, 'omissions': sorted(omissions, key=lambda item: (item['path'], item['reason'])), 'batches': make_batches(files, limits)}
    value['inventory_id'] = audit.digest(audit.canonical(value))
    if len((json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')) > audit.MAX_JSON_BYTES:
        raise audit.AuditError('Inventory exceeds the 8 MiB metadata budget; inventory explicit subtrees separately')
    return value


def read_inventory(path):
    value = audit.load_json(path)
    audit.require_keys(value, {'schema_version', 'catalog_sha256', 'root', 'limits', 'python_signals', 'discovery_complete', 'files', 'omissions', 'batches', 'inventory_id'}, 'Inventory')
    if type(value['schema_version']) is not int or value['schema_version'] != 1 or value['catalog_sha256'] != audit.catalog_hash():
        raise audit.AuditError('Inventory schema/catalog mismatch')
    if value['inventory_id'] != audit.digest(audit.canonical({k: v for k, v in value.items() if k != 'inventory_id'})):
        raise audit.AuditError('Inventory digest mismatch')
    audit.nonempty(value['root'], 'Inventory root')
    audit.require_keys(value['limits'], {'batch_files', 'batch_bytes', 'max_file_bytes', 'max_entries', 'max_signals'}, 'Inventory budgets')
    ceilings = {'batch_files': 10000, 'batch_bytes': 100000000, 'max_file_bytes': 20000000, 'max_entries': 100000, 'max_signals': 5000}
    if any(type(v) is not int or not 1 <= v <= ceilings[k] for k, v in value['limits'].items()) or type(value['python_signals']) is not bool or type(value['discovery_complete']) is not bool:
        raise audit.AuditError('Invalid inventory budgets or flags')
    seen = set()
    if not isinstance(value['files'], list) or not isinstance(value['omissions'], list):
        raise audit.AuditError('Inventory files/omissions must be lists')
    for record in value['files']:
        audit.require_keys(record, {'path', 'sha256', 'bytes', 'lines', 'signals'}, 'Inventory file')
        path = audit.relative_path(record['path'])
        if path in seen or not isinstance(record['sha256'], str) or not audit.HEX.fullmatch(record['sha256']):
            raise audit.AuditError('Duplicate file or invalid file hash')
        seen.add(path)
        if any(type(record[k]) is not int or record[k] < 0 for k in ('bytes', 'lines')) or record['bytes'] > value['limits']['max_file_bytes']:
            raise audit.AuditError('Invalid inventory file counts')
        audit.require_keys(record['signals'], {'observations', 'omitted_observations'}, 'Signals')
        if not isinstance(record['signals']['observations'], list) or type(record['signals']['omitted_observations']) is not int or record['signals']['omitted_observations'] < 0:
            raise audit.AuditError('Invalid observations')
        for signal in record['signals']['observations']:
            audit.require_keys(signal, {'kind', 'line', 'detail'}, 'Observation')
            audit.nonempty(signal['kind'], 'Observation kind')
            audit.nonempty(signal['detail'], 'Observation detail')
            if signal['line'] is not None and (type(signal['line']) is not int or not 1 <= signal['line'] <= record['lines']):
                raise audit.AuditError('Invalid observation line')
    for omission in value['omissions']:
        audit.require_keys(omission, {'path', 'reason'}, 'Omission')
        audit.nonempty(omission['path'], 'Omission path')
        audit.nonempty(omission['reason'], 'Omission reason')
    if value['batches'] != make_batches(value['files'], value['limits']):
        raise audit.AuditError('Batch assignment does not match inventory')
    return value


def create(root, out, **budgets):
    root = audit.directory(root)
    out = new_directory(root, out)
    value = inventory(root, **budgets)
    out.mkdir()
    audit.write_json(out / 'inventory.json', value)
    audit.write_json(out / 'reviews-template.json', {'inventory_id': value['inventory_id'], 'reviews': []})
    text = ['# Review the codebase in bounded batches', '', 'Inventory is discovery, not a semantic audit. AST observations are leads, never violations. Read the improve skill and repository contracts before selecting the order or modifying code.', '', f"Eligible files: {len(value['files'])}; batches: {len(value['batches'])}; discovery complete within configured exclusions: {value['discovery_complete']}.", '', 'Batches use path order and context budgets; they are not an inferred dependency graph. Prioritize by actual failure cost and expand a batch to relevant callers, tests and shared contracts. Record coverage of primary files separately from context-only files.', '', 'Save reviews.json from the template. Each review names relative snapshot/report paths under this folder plus reviewed_files explicitly attested by the reviewer. Every attested file must have an actual source citation. Structural validation does not prove the file was understood.', '', 'For planning before code, use the plan skill. For repairs, follow the improve skill with the host existing build/verification workflow. A scan never grants mutation authority.', '', 'Excluded subtrees and resource omissions remain outside coverage. Re-inventory after source changes; compare current inventory before claiming selected inventory coverage.']
    audit.write_new(out / 'packet.md', '\n'.join(text) + '\n')
    return value


def batch(inventory_path, batch_id, root, out, context_paths=()):
    value = read_inventory(inventory_path)
    root = audit.directory(root)
    if str(root) != value['root']:
        raise audit.AuditError('Root differs from inventory root')
    selected = next((b for b in value['batches'] if b['id'] == batch_id), None)
    if selected is None:
        raise audit.AuditError('Unknown batch')
    paths = sorted(set(selected['paths'] + [audit.relative_path(p) for p in context_paths]))
    records = {item['path']: item for item in value['files']}
    for path in paths:
        if path not in records or audit.digest(audit.safe_read(root, path, value['limits']['max_file_bytes'])) != records[path]['sha256']:
            raise audit.AuditError('Missing or stale inventoried file: ' + path)
    total = sum(records[p]['bytes'] for p in paths)
    if len(paths) > audit.HARD_LIMITS['max_files'] or total > audit.HARD_LIMITS['max_total_bytes']:
        raise audit.AuditError('Batch plus explicitly selected context exceeds snapshot safety ceilings')
    audit.prepare(root, out, mode='change', paths=paths, max_files=max(1, len(paths)), max_file_bytes=value['limits']['max_file_bytes'], max_total_bytes=max(1, total), max_entries=value['limits']['max_entries'])
    manifest, _ = audit.snapshot_files(out)
    if {r['path']: r['sha256'] for r in manifest['files']} != {p: records[p]['sha256'] for p in paths}:
        raise audit.AuditError('Batch collection incomplete or source changed; preserve this failed snapshot and prepare a fresh one')
    return manifest


def artifact_path(base, rel):
    audit.relative_path(rel)
    path = base / rel
    if not path.resolve(strict=True).is_relative_to(base.resolve(strict=True)):
        raise audit.AuditError('Review artifact escapes session directory')
    return path


def progress(inventory_path, reviews_path, current_root=None):
    value = read_inventory(inventory_path)
    reviews_path = Path(reviews_path).absolute()
    document = audit.load_json(reviews_path)
    audit.require_keys(document, {'inventory_id', 'reviews'}, 'Review ledger')
    if document['inventory_id'] != value['inventory_id'] or not isinstance(document['reviews'], list):
        raise audit.AuditError('Review ledger inventory mismatch')
    records = {r['path']: r for r in value['files']}
    reviewed, findings, seen_reports = set(), [], set()
    for entry in document['reviews']:
        audit.require_keys(entry, {'snapshot', 'report', 'reviewed_files'}, 'Review entry')
        snapshot = artifact_path(reviews_path.parent, entry['snapshot'])
        report_path = artifact_path(reviews_path.parent, entry['report'])
        if str(report_path) in seen_reports:
            raise audit.AuditError('Duplicate review report')
        seen_reports.add(str(report_path))
        report = audit.load_json(report_path)
        checked = audit.validate_report(snapshot, report, require_complete=True)
        if not checked['valid']:
            raise audit.AuditError('Review report invalid: ' + '; '.join(checked['errors']))
        _, data = audit.snapshot_files(snapshot)
        cited = {e['path'] for row in report['assessments'] for e in row['evidence']}
        cited |= {e['path'] for row in report['assessments'] for f in row['findings'] for e in f['evidence']}
        audit.string_list(entry['reviewed_files'], 'Reviewed files', nonempty_list=True)
        if len(set(entry['reviewed_files'])) != len(entry['reviewed_files']):
            raise audit.AuditError('Duplicate reviewed-file attestation')
        for path in entry['reviewed_files']:
            audit.relative_path(path)
            if path not in records or path not in data or data[path][0]['sha256'] != records[path]['sha256'] or (path not in cited and data[path][0]['bytes'] != 0):
                raise audit.AuditError('Reviewed file missing, stale, or uncited: ' + path)
            reviewed.add(path)
        for row in report['assessments']:
            for index, finding in enumerate(row['findings']):
                findings.append({'report': entry['report'], 'rule': row['id'], 'finding_index': index, 'title': finding['title'], 'severity': finding['severity'], 'state': 'reported_not_repaired'})
    freshness, changed, added, deleted = 'not_checked', [], [], []
    if current_root is not None:
        if str(audit.directory(current_root)) != value['root']:
            raise audit.AuditError('Current root differs from inventory root')
        current = inventory(current_root, **value['limits'], python_signals=value['python_signals'])
        now = {r['path']: r for r in current['files']}
        changed = sorted(p for p in records.keys() & now.keys() if records[p]['sha256'] != now[p]['sha256'])
        added, deleted = sorted(now.keys() - records.keys()), sorted(records.keys() - now.keys())
        freshness = 'eligible_inventory_matches' if not (changed or added or deleted) and current['omissions'] == value['omissions'] and current['discovery_complete'] == value['discovery_complete'] else 'inventory_changed'
    pending = sorted(records.keys() - reviewed)
    complete = value['discovery_complete'] and not pending and freshness == 'eligible_inventory_matches'
    return {'inventory_id': value['inventory_id'], 'eligible_files': len(records), 'agent_attested_reviewed_files': len(reviewed), 'pending_files': pending, 'discovery_complete': value['discovery_complete'], 'source_freshness': freshness, 'changed_files': changed, 'added_files': added, 'deleted_files': deleted, 'selected_inventory_review_complete': complete, 'findings': findings, 'semantic_correctness': 'unverified_by_tooling', 'limits': ['File coverage is a source-cited agent attestation, not proof of comprehension.', 'Each report must assess all thirty principles, but can retain evidence gaps.', 'Exact or semantic duplicate findings are not automatically collapsed.', 'Excluded and unenumerated material is outside coverage; reported findings are not verified repairs.']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    inv = sub.add_parser('inventory')
    inv.add_argument('--root', required=True)
    inv.add_argument('--out', required=True)
    for flag, default in [('batch-files', 100), ('batch-bytes', 1000000), ('max-file-bytes', 200000), ('max-entries', 100000), ('max-signals', 50)]:
        inv.add_argument('--' + flag, type=int, default=default)
    inv.add_argument('--python-signals', action='store_true')
    one = sub.add_parser('batch')
    one.add_argument('--inventory', required=True)
    one.add_argument('--id', required=True)
    one.add_argument('--root', required=True)
    one.add_argument('--out', required=True)
    one.add_argument('--context-path', action='append', default=[])
    prog = sub.add_parser('progress')
    prog.add_argument('--inventory', required=True)
    prog.add_argument('--reviews', required=True)
    prog.add_argument('--check-current-root')
    try:
        args = parser.parse_args(argv)
        if args.command == 'inventory':
            value = create(args.root, args.out, **{k: getattr(args, k) for k in ('batch_files', 'batch_bytes', 'max_file_bytes', 'max_entries', 'python_signals', 'max_signals')})
            result = {'inventory_id': value['inventory_id'], 'eligible_files': len(value['files']), 'batches': len(value['batches']), 'discovery_complete': value['discovery_complete'], 'semantic_review': 'not_run'}
        elif args.command == 'batch':
            value = batch(args.inventory, args.id, args.root, args.out, args.context_path)
            result = {'snapshot_id': value['snapshot_id'], 'included_files': len(value['files'])}
        else:
            result = progress(args.inventory, args.reviews, args.check_current_root)
        print(json.dumps(result, indent=2))
        return 0
    except (audit.AuditError, OSError, ValueError, TypeError, KeyError, RecursionError) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())

"""Validated, immutable local Douban delivery; no network or private credential access."""
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

CONTRACT = 'douban-delivery/1'
LISTS = {'movies': ['collect', 'wish', 'do'], 'books': ['collect', 'wish', 'reading'],
         'music': ['collect', 'wish', 'do'], 'reviews': ['collect']}


def encode(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode('utf8')


def sha(value):
    return hashlib.sha256(value).hexdigest()


def collection_receipts(payload, source_sha256, source_path):
    metadata = payload['metadata']
    receipts = []
    for category, statuses in LISTS.items():
        for status in statuses:
            items = payload.get('data', {}).get(category, {}).get(status)
            coverage = payload.get('coverage', {}).get(category, {}).get(status, {})
            complete = coverage.get('pagination_complete') is True
            if items is None:
                state = 'unseen'
            elif complete:
                state = 'complete_with_gap' if coverage.get('count_matches') is False else ('complete' if items else 'complete_empty')
            else:
                state = 'partial' if items else 'failed'
            receipts.append({
                'contract': 'douban-list-receipt/1',
                'run_id': metadata.get('run_id') or 'legacy-sha256:' + source_sha256,
                'collector_version': metadata.get('collector_version', 'unknown'),
                'source_user': metadata['user_id'], 'source_mode': metadata['backup_mode'],
                'source_snapshot': source_path, 'source_snapshot_sha256': source_sha256,
                'category': category, 'status': status, 'scope_status': state,
                'run_started_at': metadata.get('generated_at'),
                'run_finished_at': metadata.get('finished_at'),
                'list_started_at': coverage.get('started_at'), 'list_finished_at': coverage.get('finished_at'),
                'expected_count': coverage.get('expected_count'),
                'observed_count': len(items) if items is not None else None,
                'items_sha256': sha(encode(items)) if items is not None else None,
                'pagination_complete': complete, 'can_update_rows': complete and items is not None,
                'absence_means_deleted': False, 'coverage': coverage,
            })
    return receipts


def list_receipt_schema():
    text = {'type': 'string'}
    stamp = {'type': ['string', 'null'], 'format': 'date-time'}
    fields = {key: text for key in ['run_id', 'collector_version', 'source_user', 'source_mode',
                                   'source_snapshot', 'category', 'status']}
    fields.update(contract={'const': 'douban-list-receipt/1'},
                  source_snapshot_sha256={'type': 'string', 'pattern': '^[a-f0-9]{64}$'},
                  items_sha256={'type': ['string', 'null'], 'pattern': '^[a-f0-9]{64}$'},
                  scope_status={'enum': ['complete', 'complete_empty', 'complete_with_gap', 'partial', 'failed', 'unseen']},
                  run_started_at=stamp, run_finished_at=stamp, list_started_at=stamp, list_finished_at=stamp,
                  expected_count={'type': ['integer', 'null'], 'minimum': 0},
                  observed_count={'type': ['integer', 'null'], 'minimum': 0},
                  pagination_complete={'type': 'boolean'}, can_update_rows={'type': 'boolean'},
                  absence_means_deleted={'const': False}, coverage={'type': 'object'})
    return {'$schema': 'https://json-schema.org/draft/2020-12/schema', 'type': 'object',
            'required': list(fields), 'properties': fields, 'additionalProperties': False}


def schema():
    # Preserve the v1 master format; additive source receipts live in the envelope.
    text = {'type': 'string'}
    record = {k: text for k in ['record_id', 'category', 'title', 'status', 'status_label', 'marked_at',
              'douban_id', 'douban_url', 'source_user', 'source_mode', 'source_snapshot',
              'first_seen_at', 'last_seen_at']}
    record.update(rating={'type': ['integer', 'null'], 'minimum': 1, 'maximum': 5},
                  tags={'type': 'array', 'items': text}, comment={'type': ['string', 'null']})
    return {'$schema': 'https://json-schema.org/draft/2020-12/schema', 'type': 'object',
            'required': ['schema_version', 'source', 'user_id', 'record_count', 'records', 'last_snapshot_at'],
            'properties': {'schema_version': {'const': 1}, 'source': {'const': 'douban'}, 'user_id': text,
                           'record_count': {'type': 'integer', 'minimum': 0}, 'last_snapshot_at': text,
                           'records': {'type': 'array', 'items': {'type': 'object', 'required': list(record), 'properties': record}}}}


def validate_master(master):
    if master.get('schema_version') != 1 or master.get('source') != 'douban':
        raise ValueError('Unsupported master contract')
    if not isinstance(master.get('user_id'), str) or not master['user_id']:
        raise ValueError('Missing account namespace')
    rows = master['records']
    if type(master['record_count']) is not int or master['record_count'] != len(rows):
        raise ValueError('Master count mismatch')
    ids = set()
    categories = {'电影': 'movie', '图书': 'book', '音乐': 'music', '长评': 'review'}
    fields = schema()['properties']['records']['items']['properties']
    for row in rows:
        for key, spec in fields.items():
            value = row[key]
            types = spec['type'] if isinstance(spec['type'], list) else [spec['type']]
            valid = {'string': isinstance(value, str), 'null': value is None,
                     'integer': type(value) is int, 'array': isinstance(value, list)}
            if not any(valid[t] for t in types): raise ValueError('Master field type mismatch')
        expected = f"douban:{master['user_id']}:{categories[row['category']]}:{row['douban_id']}"
        if row['record_id'] != expected or row['source_user'] != master['user_id'] or not re.fullmatch(r'\d+', row['douban_id']):
            raise ValueError('Source identity mismatch')
        if row['record_id'] in ids: raise ValueError('Duplicate record identity')
        ids.add(row['record_id'])
        if row['rating'] is not None and not 1 <= row['rating'] <= 5: raise ValueError('Invalid rating')
        if any(not isinstance(tag, str) for tag in row['tags']): raise ValueError('Invalid tags')
    return master


def atomic(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.publishing-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(payload); output.flush(); os.fsync(output.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)


def immutable(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.fixed-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(payload); output.flush(); os.fsync(output.fileno())
        try: os.link(name, path)
        except FileExistsError:
            if path.read_bytes() != payload: raise ValueError('Immutable delivery changed')
    finally: os.unlink(name)


def write_capture_receipt(path):
    path = Path(path)
    raw = path.read_bytes()
    payload = json.loads(raw)
    receipt = {'contract': 'douban-capture-receipt/1', 'snapshot_sha256': sha(raw),
               'lists': collection_receipts(payload, sha(raw), path.name)}
    atomic(path.with_name('capture-receipt.json'), encode(receipt))


def publish_delivery(output, master, report, inputs):
    from _retention import publication_lock
    with publication_lock(Path(output).resolve()):
        return _publish_delivery(output, master, report, inputs)


def _publish_delivery(output, master, report, inputs):
    """inputs = (relative source path, exact snapshot bytes); missing scopes remain explicit."""
    validate_master(master)
    if master['record_count'] != report['count']: raise ValueError('Report count mismatch')
    receipts = []
    for path, raw in sorted(inputs):
        receipts.extend(collection_receipts(json.loads(raw), sha(raw), path))
    files = {'douban_master.json': encode(master), 'import_report.json': encode(report)}
    receipt = {'contract': CONTRACT, 'source_user': master['user_id'],
               'record_count': master['record_count'], 'lists': receipts,
               'files': {name: {'sha256': sha(raw), 'bytes': len(raw)} for name, raw in files.items()},
               'absence_means_deleted': False, 'policy': 'partial lists cannot replace prior observations'}
    raw = encode(receipt)
    digest = sha(raw)
    output = Path(output)
    directory = output / 'deliveries' / digest
    for name, content in files.items(): immutable(directory / name, content)
    immutable(directory / 'receipt.json', raw)
    load_delivery(directory, expected_receipt_sha256=digest)
    from _retention import best_effort, checked, prune
    output = output.resolve()
    if (output / 'current.json').exists():
        previous = json.loads((output / 'current.json').read_bytes())
        old = checked(output, output / previous['directory'])
        if old.exists():
            os.utime(old, None)
    atomic(output / 'current.json', encode({'contract': CONTRACT, 'receipt_sha256': digest,
                                          'directory': 'deliveries/' + digest}))
    best_effort(prune, output, output / 'deliveries', {digest}, r'[a-f0-9]{64}')
    return {'directory': str(directory), 'receipt_sha256': digest}


def load_delivery(directory, *, expected_receipt_sha256):
    directory = Path(directory)
    raw = (directory / 'receipt.json').read_bytes()
    if sha(raw) != expected_receipt_sha256: raise ValueError('Receipt checksum mismatch')
    receipt = json.loads(raw)
    if receipt.get('contract') != CONTRACT or set(receipt['files']) != {'douban_master.json', 'import_report.json'}:
        raise ValueError('Unsupported delivery')
    files = {}
    for name, meta in receipt['files'].items():
        content = (directory / name).read_bytes()
        if sha(content) != meta['sha256'] or len(content) != meta['bytes']: raise ValueError('Delivery checksum mismatch')
        files[name] = json.loads(content)
    validate_master(files['douban_master.json'])
    if files['douban_master.json']['record_count'] != receipt['record_count'] or files['import_report.json']['count'] != receipt['record_count']:
        raise ValueError('Delivery count mismatch')
    return {**files, 'receipt': receipt}

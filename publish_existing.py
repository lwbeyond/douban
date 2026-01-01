"""Publish already archived snapshots offline; preserve existing output files first."""
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import uuid

from consolidate import ROOT, merge_snapshots
from delivery import encode, load_delivery, publish_delivery, sha
from _config import output_dir, user_id


def run(root=ROOT):
    root = Path(root).resolve(strict=True)
    from _retention import publication_lock
    with publication_lock(root):
        return _run(root)


def _run(root):
    paths = sorted((root / 'data/raw').glob('*/snapshot.json'))
    if not paths:
        raise ValueError('No existing archived snapshots; no collection was started')
    inputs = [(path.relative_to(root).as_posix(), path.read_bytes()) for path in paths]
    snapshots = [(name, json.loads(raw)) for name, raw in inputs]
    user = user_id(root)
    rows, report = merge_snapshots(snapshots, user)
    master = {'schema_version': 1, 'source': 'douban', 'user_id': user,
              'last_snapshot_at': max(item['metadata']['generated_at'] for _, item in snapshots),
              'record_count': len(rows), 'records': rows}
    output = output_dir(root, user)
    backup = root / '.local' / ('before-fixed-delivery-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:8])
    backup.mkdir(parents=True)
    saved = {}
    for name in ('douban_master.json', 'douban_master.jsonl', 'douban_master.csv', 'douban_master.xlsx', 'import_report.json', 'current.json'):
        path = output / name
        if path.exists():
            raw = path.read_bytes()
            (backup / name).write_bytes(raw)
            if (backup / name).read_bytes() != raw:
                raise ValueError('Pre-publication preservation failed')
            saved[name] = {'sha256': sha(raw), 'bytes': len(raw)}
    (backup / 'manifest.json').write_bytes(encode({'kind': 'pre-publication-preservation', 'files': saved}))
    if paths != sorted((root / 'data/raw').glob('*/snapshot.json')) or any((root/name).read_bytes() != raw for name, raw in inputs):
        raise ValueError('Archived snapshots changed; previous publication retained')
    result = publish_delivery(output, master, report, inputs)
    load_delivery(result['directory'], expected_receipt_sha256=result['receipt_sha256'])
    from _retention import best_effort, prune
    result['retention'] = best_effort(prune, root, root / '.local', {backup.name},
        r'before-fixed-delivery-[0-9]{8}T[0-9]{6}-[a-f0-9]{8}', grace_seconds=3600)
    return {**result, 'previous_outputs': str(backup), 'network_used': False, 'raw_archives_modified': False}


if __name__ == '__main__':
    print(json.dumps(run(), ensure_ascii=False))

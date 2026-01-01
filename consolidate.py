"""Rebuild one lossless, deduplicated table from dated full snapshots."""
from __future__ import annotations

import csv
import io
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
import re
from delivery import publish_delivery
from _config import output_dir, user_id

ROOT = Path(__file__).resolve().parent
CATEGORY = {'movies': 'movie', 'books': 'book', 'music': 'music', 'reviews': 'review'}
LABELS = {'movies': '电影', 'books': '图书', 'music': '音乐', 'reviews': '长评'}
STATUS = {'movies': {'collect': '看过', 'do': '在看', 'wish': '想看'},
          'books': {'collect': '读过', 'reading': '在读', 'wish': '想读'},
          'music': {'collect': '听过', 'do': '在听', 'wish': '想听'},
          'reviews': {'collect': '长评'}}
FIELDS = ['record_id', 'category', 'title', 'status_label', 'rating', 'marked_at', 'comment',
          'tags', 'author', 'artist', 'info', 'douban_url', 'douban_id', 'original_title',
          'status', 'subject', 'subject_id', 'site_type', 'text_complete', 'cover_url',
          'cover_path', 'source_user', 'source_mode', 'first_seen_at', 'last_seen_at', 'source_snapshot']
HEADERS = ['唯一标识', '类别', '标题', '状态', '我的评分（1–5）', '标记日期', '我的短评或长评',
           '标签', '作者及出版信息', '音乐人', '条目信息', '豆瓣链接', '豆瓣ID', '完整标题',
           '状态代码', '长评对象', '对象ID', '长评分类', '长评正文完整', '封面链接',
           '本地封面', '豆瓣用户', '读取方式', '首次提取时间', '最近提取时间', '来源快照']


def json_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + '\n'


def atomic_text(path, content, encoding='utf-8'):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(content, encoding=encoding)
    temp.replace(path)


def normalize(item, category, status, metadata, source, user):
    item_id = str(item.get('douban_id') or '').strip()
    if not re.fullmatch(r'\d+', item_id):
        raise ValueError('条目缺少有效豆瓣 ID')
    kind = CATEGORY[category]
    rating = item.get('rating')
    if rating in ('', None):
        rating = None
    else:
        rating = int(rating)
        if not 1 <= rating <= 5:
            raise ValueError('评分超出 1–5')
    tags = item.get('tags') or []
    if isinstance(tags, str):
        tags = tags.split()
    url = item.get('url') or (f'https://{kind}.douban.com/subject/{item_id}/' if kind != 'review' else '')
    row = {field: '' for field in FIELDS}
    row.update({field: item.get(field, '') for field in ('title', 'comment', 'author', 'artist', 'info', 'original_title', 'subject', 'subject_id', 'site_type')})
    row.update(record_id=f'douban:{user}:{kind}:{item_id}', category=LABELS[category],
               douban_id=item_id, status=status, status_label=STATUS[category][status], rating=rating,
               marked_at=item.get('date', ''), tags=tags, douban_url=url,
               cover_url=item.get('cover', ''), source_user=user, source_mode=metadata['backup_mode'],
               first_seen_at=metadata['generated_at'], last_seen_at=metadata['generated_at'],
               source_snapshot=source, text_complete=item.get('text_complete') if kind == 'review' else None)
    if item.get('cover_path'):
        row['cover_path'] = 'data/assets/' + item['cover_path'].replace('\\', '/')
    if kind != 'review':
        date_match = re.search(r'\d{4}-\d{2}-\d{2}', row['marked_at'])
        if date_match:
            row['marked_at'] = date_match[0]
    return row


def merge_snapshots(snapshots, user=None):
    """Timestamp order makes reimports and filename reordering idempotent."""
    user = user or user_id()
    records, rejected, coverage, conflicts = {}, [], [], []
    ordered = sorted(snapshots, key=lambda pair: (datetime.fromisoformat(pair[1]['metadata']['generated_at']), pair[0]))
    for source, payload in ordered:
        metadata = payload['metadata']
        if metadata['user_id'].lower() != user.lower():
            raise ValueError(f'快照不属于 {user}: {source}')
        seen = {}
        for category, collections in payload['data'].items():
            if category not in CATEGORY:
                raise ValueError(f'未知分类: {category}')
            for status, items in collections.items():
                state = payload['coverage'].get(category, {}).get(status, {})
                coverage.append({'snapshot': source, 'category': category, 'status': status, **state})
                if not state.get('pagination_complete'):
                    continue
                for item in items:
                    try:
                        row = normalize(item, category, status, metadata, source, user)
                    except (ValueError, TypeError, KeyError) as exc:
                        rejected.append({'snapshot': source, 'category': category, 'status': status, 'reason': str(exc), 'item': item})
                        continue
                    key = row['record_id']
                    if key in seen and seen[key]['status'] != status:
                        conflicts.append({'snapshot': source, 'record_id': key, 'statuses': [seen[key]['status'], status]})
                        # A change during pagination may put an item in two statuses.
                        # The more recent mark date wins; equal dates keep the first observed status.
                        if row['marked_at'] <= seen[key]['marked_at']:
                            continue
                    seen[key] = row
        for key, row in seen.items():
            old = records.get(key)
            if old:
                row['first_seen_at'] = old['first_seen_at']
                if not row['cover_path']:
                    row['cover_path'] = old['cover_path']
                if old['text_complete'] is True and row['text_complete'] is not True:
                    row['comment'], row['text_complete'] = old['comment'], True
            records[key] = row
    rows = sorted(records.values(), key=lambda row: (row['category'], row['marked_at'], row['record_id']), reverse=True)
    latest_attempt = {}
    latest_success = {}
    for state in coverage:
        key = state['category'] + '/' + state['status']
        latest_attempt[key] = state
        if state.get('pagination_complete'):
            latest_success[key] = state
    return rows, {'count': len(rows), 'by_category': dict(Counter(row['category'] for row in rows)),
                  'by_status': dict(Counter(row['status_label'] for row in rows)),
                  'coverage': coverage, 'latest_attempt': latest_attempt, 'latest_success': latest_success,
                  'rejected': rejected, 'conflicts': conflicts}


def csv_safe(value):
    if value is None:
        return ''
    if isinstance(value, list):
        value = json.dumps(value, ensure_ascii=False)
    if isinstance(value, str) and (value.lstrip().startswith(('=', '+', '-', '@')) or value.startswith(('\t', '\r', '\n'))):
        return "'" + value
    return value


def main():
    paths = sorted((ROOT / 'data' / 'raw').glob('*/snapshot.json'))
    if not paths:
        raise ValueError('尚无提取快照，请先运行 capture.py')
    inputs = [(path.relative_to(ROOT).as_posix(), path.read_bytes()) for path in paths]
    snapshots = [(name, json.loads(raw)) for name, raw in inputs]
    user = user_id()
    rows, report = merge_snapshots(snapshots, user)
    # All validation completes before replacing any existing output.
    assert len(rows) == len({row['record_id'] for row in rows})
    master = {'schema_version': 1, 'source': 'douban', 'user_id': user,
              'last_snapshot_at': max(payload['metadata']['generated_at'] for _, payload in snapshots),
              'record_count': len(rows), 'records': rows}
    csv_buffer = io.StringIO(newline='')
    writer = csv.writer(csv_buffer)
    writer.writerow(HEADERS)
    writer.writerows([[csv_safe(row[field]) for field in FIELDS] for row in rows])
    # Cross-project readers use this fixed bundle. Compatibility files below are independent views.
    OUTPUT = output_dir(ROOT, user)
    publish_delivery(OUTPUT, master, report, inputs)
    atomic_text(OUTPUT / 'douban_master.json', json_text(master))
    atomic_text(OUTPUT / 'douban_master.csv', csv_buffer.getvalue(), encoding='utf-8-sig')
    atomic_text(OUTPUT / 'douban_master.jsonl', ''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows))
    atomic_text(OUTPUT / 'import_report.json', json_text(report))
    print(json.dumps({k: report[k] for k in ('count', 'by_category', 'by_status')}, ensure_ascii=False))
    print(f'去重冲突 {len(report["conflicts"])}；待核对记录 {len(report["rejected"])}')


if __name__ == '__main__':
    main()

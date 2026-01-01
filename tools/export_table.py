"""Export the generated master table to a formatted Excel workbook (openpyxl).

Reads outputs/<user>/douban_master.json and import_report.json; writes douban_master.xlsx.
"""
from datetime import date
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from _config import output_dir, user_id  # noqa: E402

from openpyxl import Workbook  # noqa: E402
from openpyxl.styles import Alignment, Font, PatternFill  # noqa: E402
from openpyxl.worksheet.table import Table, TableStyleInfo  # noqa: E402

FIELDS = ['category', 'title', 'status_label', 'rating', 'marked_at', 'comment', 'tags', 'douban_url', 'douban_id',
          'record_id', 'author', 'artist', 'info', 'original_title', 'subject', 'subject_id', 'site_type',
          'text_complete', 'cover_url', 'cover_path', 'source_user', 'source_mode', 'first_seen_at', 'last_seen_at']
HEADERS = ['类别', '标题', '状态', '我的评分（1–5）', '标记日期', '我的短评或长评', '标签', '豆瓣链接', '豆瓣ID', '唯一标识',
           '作者及出版信息', '音乐人', '条目信息', '完整标题', '长评对象', '对象ID', '长评分类', '长评正文完整', '封面链接',
           '本地封面', '豆瓣用户', '读取方式', '首次提取时间', '最近提取时间']
NAMES = {'movies/collect': '看过', 'movies/wish': '想看', 'movies/do': '在看', 'books/collect': '读过',
         'books/wish': '想读', 'books/reading': '在读', 'music/collect': '听过', 'music/wish': '想听',
         'music/do': '在听', 'reviews/collect': '长评'}
WIDTHS = {'A': 9, 'B': 36, 'C': 10, 'D': 14, 'E': 14, 'F': 60, 'G': 25, 'H': 54, 'J': 42, 'M': 65, 'N': 65}


def safe(value):
    """Prefix text that spreadsheet software could treat as a formula."""
    if isinstance(value, str) and re.match(r'^\s*[=+@-]', value):
        return "'" + value
    return value


def cell(row, field):
    value = row.get(field)
    if field == 'marked_at' and isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        return date.fromisoformat(value)
    if isinstance(value, list):
        return safe(' / '.join(map(str, value)))
    if field == 'source_mode':
        return '公开页面' if value == 'public' else '登录后页面'
    return safe('' if value is None else value)


def export(output):
    data = json.loads((output / 'douban_master.json').read_text(encoding='utf-8'))
    report = json.loads((output / 'import_report.json').read_text(encoding='utf-8'))
    wb = Workbook()
    ws = wb.active
    ws.title = '豆瓣主表'
    ws.sheet_view.showGridLines = False
    ws['A1'] = '豆瓣书影音记录'
    ws['A1'].font = Font(size=16, bold=True, color='1F2937')
    modes = '、'.join(sorted({'公开页面' if r['source_mode'] == 'public' else '登录后页面' for r in data['records']}))
    ws['A2'] = f"提取日期 {data['last_snapshot_at'][:10]}；{modes}；{data['record_count']} 条。以唯一标识去重。"
    gaps = [c for c in report.get('latest_success', {}).values() if not c.get('count_matches', True)]
    ws['A3'] = ('数量差异：' + '；'.join(f"{NAMES.get(c['category'] + '/' + c['status'], c['status'])}页面 {c.get('expected_count')}，返回 {c.get('unique_count')}" for c in gaps)
                if gaps else '状态、评分、短评以最新提取为准；未再次出现的旧记录保留。')
    for ref in ('A2', 'A3'):
        ws[ref].font = Font(size=10, color='64748B')
    ws.append([])
    ws.append(HEADERS)
    for record in data['records']:
        ws.append([cell(record, field) for field in FIELDS])
    end = max(6, len(data['records']) + 5)
    for c in ws[5]:
        c.font = Font(bold=True, color='FFFFFF')
        c.fill = PatternFill('solid', fgColor='334155')
    for row in ws.iter_rows(min_row=6, max_row=end):
        row[4].number_format = 'yyyy-mm-dd'
        for c in row[5:7]:
            c.alignment = Alignment(wrap_text=True, vertical='center')
    for column in 'ABCDEFGHIJKLMNOPQRSTUVWX':
        ws.column_dimensions[column].width = WIDTHS.get(column, 20)
    if data['records']:
        table = Table(displayName='DoubanRecords', ref=f'A5:X{len(data["records"]) + 5}')
        table.tableStyleInfo = TableStyleInfo(name='TableStyleMedium2', showRowStripes=True)
        ws.add_table(table)
    ws.freeze_panes = 'A6'
    target = output / 'douban_master.xlsx'
    temp = target.with_suffix('.xlsx.tmp')
    wb.save(temp)
    temp.replace(target)
    print(f"Saved {data['record_count']} rows to {target.name}")


if __name__ == '__main__':
    export(output_dir(ROOT, user_id()))

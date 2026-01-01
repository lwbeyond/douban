"""Account configuration. Nothing here is personal: set your own Douban user ID locally.

Resolution order: environment variable ``DOUBAN_USER_ID`` → ``.local/config.json``
(``{"user_id": "your_douban_id"}``). ``.local/`` is git-ignored.
"""
import json
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent


def user_id(root=ROOT, required=True):
    value = os.environ.get('DOUBAN_USER_ID', '').strip()
    if not value:
        config = Path(root) / '.local' / 'config.json'
        if config.exists():
            value = str(json.loads(config.read_text(encoding='utf-8')).get('user_id') or '').strip()
    if value and not re.fullmatch(r'[A-Za-z0-9._-]{1,64}', value):
        raise ValueError('豆瓣用户 ID 格式无效（只允许字母、数字、. _ -）')
    if required and not value:
        raise ValueError('请先设置豆瓣用户 ID：环境变量 DOUBAN_USER_ID，或在 .local/config.json 写入 {"user_id": "..."}')
    return value


def output_dir(root, uid):
    return Path(root) / 'outputs' / uid.lower()

"""Import only a user-pasted Douban Cookie, locally and without echoing it."""
from getpass import getpass
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'vendor/douban_backup'))
from crawl_public import build_public_session
from import_cookies import parse_cookies
from diagnostics import classify_response
from _config import user_id


def main():
    uid = user_id()
    print(f'在浏览器登录你的豆瓣账号 {uid}。')
    print('按 F12 → 网络/Network → 刷新页面 → 点击 www.douban.com 请求。')
    print('在请求标头中复制 Cookie: 后的全部内容，粘贴到这里，然后回车。')
    print('粘贴时不显示内容；Cookie 只保存在本机 .local 目录，不要发到聊天里。')
    raw = getpass('Cookie: ').strip()
    if raw.lower().startswith('cookie:'):
        raw = raw.split(':', 1)[1].strip()
    cookies = parse_cookies(raw)
    if not cookies:
        raise ValueError('未读到有效的 Cookie。')
    session = build_public_session()
    for name, value in cookies.items():
        session.cookies.set(name, value, domain='.douban.com', path='/')
    response = session.get('https://www.douban.com/mine/', timeout=30)
    match = re.search(r'/people/([^/]+)/?', response.url)
    if classify_response(response)[0] != 'ok' or not match or match[1].lower() != uid.lower():
        raise ValueError(f'未验证为 {uid} 的有效登录，未保存。请检查账号和 Cookie。')
    directory = ROOT / '.local'
    directory.mkdir(exist_ok=True)
    if os.name == 'nt':
        who = subprocess.check_output(['whoami'], text=True).strip()
        subprocess.run(['icacls', str(directory), '/inheritance:r', '/grant:r', f'{who}:(OI)(CI)F'], check=True, stdout=subprocess.DEVNULL)
    else:
        os.chmod(directory, 0o700)
    path = directory / 'cookies.json'
    path.write_text(json.dumps(cookies), encoding='utf-8')
    if os.name != 'nt':
        os.chmod(path, 0o600)
    print('登录信息已保存在本机。现在双击“再次提取.cmd”即可补齐可读取的个人记录。')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'导入未完成: {exc}')
        sys.exit(1)

"""One manual refresh. No scheduler, RSS, or incremental crawling."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from _config import output_dir, user_id


def export_excel():
    result = subprocess.run([sys.executable, str(ROOT / 'tools/export_table.py')], cwd=ROOT)
    if result.returncode:
        print('JSON、JSONL 和 CSV 已更新；Excel 导出失败，请关闭打开的表格后重新整理。')
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(description='手动完整提取并合并你自己的豆瓣记录（账号由 DOUBAN_USER_ID 指定）')
    parser.add_argument('--merge-only', action='store_true', help='仅从已有快照重新生成主表')
    parser.add_argument('--public', action='store_true', help='即使有登录信息也只读取公开页面')
    parser.add_argument('--no-covers', action='store_true', help='本次不下载封面')
    args = parser.parse_args()
    os.chdir(ROOT)
    # An OS lock is released even if the process exits unexpectedly.
    lock_path = ROOT / '.local' / 'refresh.lock'
    lock_path.parent.mkdir(exist_ok=True)
    uid = user_id()
    with lock_path.open('a+b') as lock:
        lock.seek(0)
        if not lock.read(1):
            lock.write(b'0')
            lock.flush()
        lock.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print('已有一次提取或整理正在运行。')
            return 1
        if not args.merge_only:
            from capture import capture, download_covers
            authenticated = not args.public and (ROOT / '.local/cookies.json').exists()
            snapshot = capture(['movies', 'books', 'music', 'reviews'], authenticated=authenticated)
            if not args.no_covers:
                download_covers(snapshot)
        from consolidate import main as consolidate
        consolidate()
        exported = export_excel()
        print('主表目录: ' + str(output_dir(ROOT, uid)))
        print('公开页面看不到的记录需登录后补提取。请查看 import_report.json 中的数量差异。')
        return 0 if exported else 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, OSError) as exc:
        print('未完成: ' + str(exc))
        sys.exit(1)

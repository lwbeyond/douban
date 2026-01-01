"""Manual full snapshots using zx2592/douban_backup's parsers and pagination."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
import uuid
from delivery import write_capture_receipt
from datetime import datetime
from urllib.parse import urljoin, urlparse

ROOT = Path(__file__).resolve().parent
os.environ['DOUBAN_BACKUP_HOME'] = str(ROOT / '.local')
sys.path.insert(0, str(ROOT / 'vendor' / 'douban_backup'))
from bs4 import BeautifulSoup
from crawl_public import build_public_session
from movies import MovieCrawler
from books import BookCrawler
from music import MusicCrawler
from reviews import ReviewCrawler
from diagnostics import classify_response
from covers import CoverDownloader
from _config import user_id as configured_user_id

CLASSES = {'movies': MovieCrawler, 'books': BookCrawler, 'music': MusicCrawler, 'reviews': ReviewCrawler}
HOSTS = {'movies': 'movie', 'books': 'book', 'music': 'music', 'reviews': 'www'}


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temp.replace(path)
    if path.name == 'snapshot.json':
        write_capture_receipt(path)


def expected_count(soup):
    counter = soup.select_one('.subject-num')
    if counter:
        match = re.search(r'/\s*(\d+)', counter.get_text())
        if match:
            return int(match[1])
    for tag in (soup.h1, soup.title):
        if tag:
            match = re.search(r'[（(](\d+)[)）]', tag.get_text())
            if match:
                return int(match[1])
    return None


def enrich(items, soup, category):
    blocks = soup.select('li.subject-item') if category == 'books' else []
    blocks = blocks or soup.select('div.item')
    by_id = {str(item['douban_id']): item for item in items if item.get('douban_id')}
    for block in blocks:
        link = block.select_one('a[href*="/subject/"]')
        match = re.search(r'/subject/(\d+)', link.get('href', '')) if link else None
        item = by_id.get(match[1]) if match else None
        if item is None:
            continue
        item['url'] = link['href']
        title = block.select_one('.title a') or block.select_one('h2 a')
        if title:
            item['original_title'] = title.get_text(' ', strip=True)
        intro = block.select_one('.intro') or block.select_one('.pub')
        if intro:
            item['info'] = intro.get_text(' ', strip=True)
        date = block.select_one('.date')
        if date:
            item['date'] = date.get_text(strip=True)
        tags = block.select_one('.tags')
        if tags:
            item['tags'] = re.sub(r'^标签\s*[:：]\s*', '', tags.get_text(' ', strip=True))
    return items


class SnapshotMixin:
    """Persist source pages and stop on denied access without retrying that denial."""
    def _make_request(self, url, retries=1):
        time.sleep(self.request_delay)
        try:
            response = self.session.get(url, timeout=30)
        except Exception as exc:
            self.issues.append({'url': url, 'reason': type(exc).__name__})
            return None
        name = hashlib.sha256(url.encode()).hexdigest()[:20] + '.html'
        (self.pages_dir / name).write_text(response.text, encoding='utf-8')
        status, code, message = classify_response(response)
        self.pages.append({'url': url, 'response_url': response.url, 'status': response.status_code,
                           'file': name, 'diagnostic': code})
        if status != 'ok':
            self.issues.append({'url': url, 'reason': code, 'message': message})
        return response

    def _parse_items(self, response, collection_type=None):
        soup = BeautifulSoup(response.text, 'html.parser')
        count = expected_count(soup)
        if self.expected is None:
            self.expected = count
        items = super()._parse_items(response, collection_type)
        return enrich(items, soup, self.category_key)

    def _get_pagination(self, response):
        soup = BeautifulSoup(response.text, 'html.parser')
        next_link = soup.select_one('span.next a') or soup.select_one('a.next')
        if not next_link or not next_link.get('href'):
            return None
        url = urljoin(response.url, next_link['href'])
        if urlparse(url).netloc != urlparse(response.url).netloc:
            self.issues.append({'url': url, 'reason': 'unexpected_pagination_host'})
            self.incomplete = True
            return None
        return url

    def _fetch_full_text(self, review):
        response = self._make_request(review.get('url', '')) if review.get('url') else None
        if response is not None and classify_response(response)[0] == 'ok':
            soup = BeautifulSoup(response.text, 'html.parser')
            body = soup.select_one('#link-report .full') or soup.select_one('.review-content') or soup.select_one('#link-report')
            if body:
                review['text_complete'] = True
                return body.get_text('\n', strip=True)
        review['text_complete'] = False
        return review.get('comment', '')


def capture(categories, delay=3, authenticated=False):
    USER_ID = configured_user_id()
    stamp = datetime.now().astimezone().strftime('%Y%m%d_%H%M%S_%f')
    run_dir = ROOT / 'data' / 'raw' / stamp
    pages_dir = run_dir / 'pages'
    pages_dir.mkdir(parents=True)
    session = build_public_session()
    if authenticated:
        cookies_file = ROOT / '.local' / 'cookies.json'
        if not cookies_file.exists():
            raise ValueError('请先运行“导入登录信息.cmd”，在本机导入 Cookie。')
        cookies = json.loads(cookies_file.read_text(encoding='utf-8'))
        for name, value in cookies.items():
            session.cookies.set(name, value, domain='.douban.com', path='/')
        response = session.get('https://www.douban.com/mine/', timeout=30)
        match = re.search(r'/people/([^/]+)/?', response.url)
        if classify_response(response)[0] != 'ok' or not match or match[1].lower() != USER_ID.lower():
            raise ValueError(f'登录未验证为 {USER_ID}，未开始提取；请重新导入当前账号的 Cookie。')
    payload = {'metadata': {'schema_version': 1, 'user_id': USER_ID, 'generated_at': datetime.now().astimezone().isoformat(),
                           'backup_mode': 'authenticated' if authenticated else 'public', 'capture_mode': 'full',
                           'selected_categories': categories, 'upstream_commit': '0d74957a773a9073a3bbcd8ef3746339e0fedfa9',
                           'run_id': str(uuid.uuid4()), 'collector_version': 'douban-local/2'},
               'data': {}, 'coverage': {}, 'pages': []}
    path = run_dir / 'snapshot.json'
    write_json(path, payload)
    try:
        for category in categories:
            payload['data'][category] = {}
            payload['coverage'][category] = {}
            statuses = ['collect'] if category == 'reviews' else ['collect', 'wish', 'reading' if category == 'books' else 'do']
            for status in statuses:
                list_started = datetime.now().astimezone().isoformat()
                crawler_class = type('Snapshot' + CLASSES[category].__name__, (SnapshotMixin, CLASSES[category]), {})
                extra = {'fetch_full_text': True} if category == 'reviews' else {}
                crawler = crawler_class(session, request_delay=delay, incremental=False, **extra)
                crawler.set_user_id(USER_ID)
                crawler.pages_dir, crawler.pages, crawler.issues, crawler.expected = pages_dir, [], [], None
                suffix = 'reviews' if category == 'reviews' else ('do' if status == 'reading' else status)
                url = f'https://{HOSTS[category]}.douban.com/people/{USER_ID}/{suffix}'
                if category == 'books':
                    url += '?start=0&type=book'
                items = crawler.crawl_collection(url, status)
                # Upstream's generic empty-page detection misses some explicit zero-count pages.
                complete = not crawler.incomplete or (crawler.expected == 0 and not items and not crawler.issues)
                ids = [str(item.get('douban_id') or '') for item in items]
                valid = all(re.fullmatch(r'\d+', item_id) for item_id in ids)
                unique_count = len(set(ids))
                payload['data'][category][status] = items
                payload['coverage'][category][status] = {
                    'pagination_complete': complete, 'expected_count': crawler.expected,
                    'parsed_count': len(items), 'unique_count': unique_count,
                    'count_matches': crawler.expected is None or crawler.expected == unique_count,
                    'valid_ids': valid, 'issues': crawler.issues,
                    'source_url': url,
                    'started_at': list_started, 'finished_at': datetime.now().astimezone().isoformat(),
                }
                payload['pages'].extend(crawler.pages)
                write_json(path, payload)
                print(f'{category}/{status}: {unique_count} 条，页面计数 {crawler.expected}，翻页完成 {complete}', flush=True)
    except KeyboardInterrupt:
        payload['metadata']['interrupted'] = True
        write_json(path, payload)
        print('已保留完成的列表和原始页面。', flush=True)
    payload['metadata']['finished_at'] = datetime.now().astimezone().isoformat()
    write_json(path, payload)
    return path


def download_covers(path):
    payload = json.loads(Path(path).read_text(encoding='utf-8'))
    downloader = CoverDownloader(build_public_session(), str(ROOT / 'data' / 'assets'), timeout=15)
    items = [(category, item) for category, collections in payload['data'].items() for group in collections.values() for item in group]
    for index, (category, item) in enumerate(items, 1):
        downloader._download_one(category, item)
        if index % 50 == 0 or index == len(items):
            payload['cover_stats'] = downloader.stats
            payload['metadata']['cover_root'] = 'assets'
            write_json(path, payload)
            print(f'封面进度 {index}/{len(items)}: {downloader.stats}', flush=True)
    payload['cover_stats'] = downloader.stats
    # The relative root is explicit; snapshots themselves remain portable with the data directory.
    payload['metadata']['cover_root'] = 'assets'
    write_json(path, payload)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='豆瓣书影音手动完整备份（账号由 DOUBAN_USER_ID 指定）')
    parser.add_argument('--only', default='movies,books,music,reviews')
    parser.add_argument('--authenticated', action='store_true')
    parser.add_argument('--delay', type=float, default=3)
    parser.add_argument('--covers-for', type=Path)
    args = parser.parse_args()
    if args.covers_for:
        download_covers(args.covers_for)
    else:
        selected = args.only.split(',')
        if set(selected) - set(CLASSES) or args.delay < 0:
            parser.error('分类或请求间隔无效')
        print(capture(selected, args.delay, args.authenticated))

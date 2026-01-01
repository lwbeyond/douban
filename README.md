# douban-local · 豆瓣书影音个人备份与整理

[中文](#中文) · [English](#english)

## 中文

把**你自己的**豆瓣书影音记录（看过/想看/在看、读过/想读/在读、听过/想听/在听、长评）手动完整提取为原始快照，再离线合并成一张去重主表，导出 JSON / JSONL / CSV / Excel，并生成带校验摘要的固定交付包，方便导入个人知识库。

- 只做**手动一次性**提取：没有定时任务、RSS、常驻进程或增量抓取。
- 页面解析与翻页复用 [zx2592/douban_backup](https://github.com/zx2592/douban_backup)（MIT），本项目负责快照留存、数量核对、稳定去重与交付契约。

### 处理流程

```text
豆瓣列表页 ──capture.py──▶ data/raw/<时间戳>/snapshot.json (+ pages/ 原始网页, capture-receipt.json)
                                   │  逐列表 coverage：翻页是否完整、页面声明数 vs 实际数
                                   ▼
                      consolidate.py  merge_snapshots()
                                   │  按快照时间排序 → 规范化 → 去重合并 → 冲突/拒收报告
                                   ▼
             outputs/<账号>/douban_master.{json,jsonl,csv,xlsx} + import_report.json
                                   │
                      delivery.py  publish_delivery()
                                   ▼
             outputs/<账号>/deliveries/<receipt-sha256>/ + current.json（原子切换）
```

1. **采集（capture.py）**：对每个类别×状态从第一页完整翻页。每个请求间隔默认 3 秒；每个原始网页以 URL 哈希名保存到 `pages/`，便于以后复核或重新解析。被拒绝/受限的响应记录为 issue，不重试同一拒绝。补充列表页可见的日期、标签、原始标题和条目信息；长评尝试抓取全文并标记 `text_complete`。翻页跨域或中断会把列表标记为不完整。
2. **规范化（normalize）**：只接受纯数字豆瓣 ID；评分必须为 1–5 或空；标签统一为数组；标记日期只保留 `YYYY-MM-DD`；封面路径改为相对项目根目录。
3. **合并规则（merge_snapshots）**
   - 唯一标识 `douban:<账号>:<类别>:<豆瓣ID>`；状态变化（想看→看过）仍是同一行；不同类别的同号条目互不覆盖；长评按长评自身 ID 分别保留。
   - 快照按 `generated_at` 排序合并，重复导入同一快照不增加记录，旧快照不会覆盖新快照。主动清空的评分/短评会更新为空。
   - **翻页不完整的列表不参与更新**；未再次出现的旧记录保留——“公开不可见、取消标记、下架”都不能当作删除。
   - 同一快照内一个条目出现在两个状态时，记录冲突，以较新的标记日期为准。
   - 无有效 ID 的条目进入报告 `rejected`，避免按同名作品错误合并。
   - 已抓到完整长评正文时，后续只拿到摘要不会覆盖全文。
4. **导出**：CSV 对可能被表格软件识别为公式的文本（以 `= + - @` 开头）加前缀保护；Excel 由 `tools/export_table.py`（openpyxl）生成。
5. **固定交付（delivery.py）**：主表与报告按内容寻址写入不可变目录，回执记录每个来源列表的状态（complete / complete_empty / complete_with_gap / partial / failed / unseen）、摘要与字节数；`current.json` 原子指向最新包，消费方用 `load_delivery(directory, expected_receipt_sha256=...)` 校验。详见 [DATA_CONTRACT.md](DATA_CONTRACT.md)。

### 快速开始

需要 Python 3.10+ 与 Git。

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.lock.txt        # Windows: .venv\Scripts\pip
# 获取上游解析器（固定提交，放在被忽略的 vendor/ 下）
git clone https://github.com/zx2592/douban_backup.git vendor/douban_backup
git -C vendor/douban_backup checkout 0d74957a773a9073a3bbcd8ef3746339e0fedfa9

export DOUBAN_USER_ID=your_douban_id                  # 或写入 .local/config.json: {"user_id": "..."}
python run_backup.py              # 完整提取 + 下载封面 + 合并 + 导出
python run_backup.py --merge-only # 只从已有快照重新生成主表，不访问豆瓣
python publish_existing.py        # 离线发布固定交付包
```

Windows 可双击：`再次提取.cmd`、`仅整理已有数据.cmd`、`导入登录信息.cmd`（需先建好 `.venv`）。

**登录后补充（可选）**：公开页面看不到设为私密的记录。运行 `python import_local_cookies.py`，按提示从浏览器开发者工具复制**你自己**账号的 Cookie 粘贴（输入不回显）。程序会先验证登录账号与 `DOUBAN_USER_ID` 一致，然后才保存到 `.local/cookies.json`（Windows 用 icacls、其他系统用 0700/0600 权限限制访问）。之后 `run_backup.py` 自动使用登录读取；`--public` 可强制只读公开页面。

### 测试

```bash
python -m unittest test_consolidate test_delivery test_publish_existing
```

全部测试只使用合成数据（账号 `example_user`、ID `123`），不联网。

### 隐私

- 本仓库**不包含**任何真实书影音记录、评分、短评、豆瓣账号、Cookie 或封面。
- `data/`、`outputs/`、`.local/`（含 Cookie 与账号配置）、`vendor/` 及所有 CSV/XLSX/JSONL/HTML/图片均被 `.gitignore` 排除。请不要把 `.local/` 或输出目录提交、分享或导入公共知识库；不要把 Cookie 发到任何聊天或工单里。
- `examples/knowledge-base-v1` 是显式合成样例。

### 免责声明

本项目与豆瓣无任何关联。仅用于备份**你本人**账号的数据；请遵守豆瓣用户协议与 robots 规则，保持低频访问（默认每请求间隔 3 秒），不要用于抓取他人数据或商业用途。页面结构变化可能导致解析失败，作者不对数据完整性或账号风险负责。

### 许可证

MIT（见 [LICENSE](LICENSE)）。上游 `zx2592/douban_backup` 同为 MIT，未随本仓库分发，需按上文自行获取。

---

## English

A small toolkit to back up **your own** Douban movie/book/music marks and long reviews: it takes manual full snapshots of your list pages, keeps the raw HTML for auditing, merges all snapshots into one deduplicated master table (JSON/JSONL/CSV/Excel), and publishes a checksummed, immutable delivery bundle for knowledge-base import.

**How it works**

- `capture.py` paginates every category × status from page 1 (3 s delay per request), stores each raw page, and records per-list coverage (pagination complete? declared vs. observed count). Denied responses are logged, not retried. Parsing/pagination reuse [zx2592/douban_backup](https://github.com/zx2592/douban_backup) (MIT).
- `consolidate.py` normalizes rows (numeric IDs only, rating 1–5 or null, tag arrays, ISO dates) and merges snapshots in timestamp order with a stable key `douban:<account>:<kind>:<id>`. Incomplete lists never update rows; records that disappear are kept (absence ≠ deletion); explicitly cleared ratings/comments are applied; ID-less rows are quarantined in `rejected`; a full review body is never replaced by a summary.
- CSV/Excel exports guard against formula injection. `delivery.py` writes content-addressed bundles with per-list receipts and atomically switches `current.json`. See [DATA_CONTRACT.md](DATA_CONTRACT.md).

**Quick start**: install `requirements.lock.txt`, clone the upstream parser into `vendor/douban_backup` at commit `0d74957a…`, set `DOUBAN_USER_ID`, then run `python run_backup.py` (or `--merge-only`). Optional login: `python import_local_cookies.py` (your own account only; stored locally in `.local/`, verified against `DOUBAN_USER_ID`).

**Tests**: `python -m unittest test_consolidate test_delivery test_publish_existing` (synthetic data, offline).

**Privacy**: no real records, ratings, comments, account IDs, cookies or covers are included. Personal data directories (`data/`, `outputs/`, `.local/`) and exports are git-ignored. Never share `.local/` or your cookies.

**Disclaimer**: not affiliated with Douban. For backing up your own account only; respect Douban's terms and keep request rates low. No warranty.

**License**: MIT.

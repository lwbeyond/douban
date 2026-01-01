# 豆瓣对外交付契约 / Delivery contract

`master.schema.json` 约束 schema_version=1 主表；`list-receipt.schema.json` 约束逐列表 `douban-list-receipt/1`。权威定义位于 `delivery.py` 的 `schema()` / `list_receipt_schema()`，修改定义后重新生成 JSON 并运行合成测试。来源记录键使用 `douban:<明确账号>:<类别>:<ID>`，同作品不同账号或不同长评不合并。

新采集带 `run_id`、`collector_version`，逐列表另有开始/完成时间。`generated_at` 为整次开始时间，不能冒充每个列表的完成时刻。旧快照没有这些字段时，使用明确标记的 `legacy-sha256:` 派生引用，旧 `collector_version`/逐列表时间为 `unknown`/`null`，不用文件 mtime 补造。`capture-receipt.json` 的摘要绑定本次 `snapshot.json`；采集或封面整理中快照变化后同步刷新回执。

逐列表状态分别为 `complete`、`complete_empty`、`complete_with_gap`、`partial`、`failed`、`unseen`。每项保存 run_id/版本、账号、范围、原始快照 SHA-256、列表内容摘要和观察条数/页面声明条数。完整翻页但页面数不符保留 `complete_with_gap`，只代表拿到实际可见记录。`partial`/`failed`/`unseen` 不发布行覆盖；成功的空列表也不推断旧记录已删除。明确清空的评分/评论来自实际再次出现的完整条目，与“没出现”不同。

完整机器交付位于 `outputs/<账号>/deliveries/<receipt-sha256>/`，含 `douban_master.json`、`import_report.json`、`receipt.json`。`current.json` 在三者完整写入并校验后原子指向交付。每份回执带全部来源逐列表说明、文件字节数和摘要；成功发布后自动清理过期包，保留当前包及替换后一小时内的读取缓冲。长期分析需自行保存所用输入。主表是历次完整列表的观察合并，不代表某一瞬间的平台全量状态。兼容 JSON/CSV/JSONL/Excel 各自更新，消费方不能拼这些独立文件推断同批。

消费方保存固定 `directory` 与 `receipt_sha256`，通过 `delivery.load_delivery(directory, expected_receipt_sha256=...)` 校验。`examples/knowledge-base-v1` 是**显式合成**的提供侧交付（账号 `example_user`，`"synthetic": true`），仅用于消费方验收。

离线固定发布入口为 `python publish_existing.py`：复用 `consolidate.merge_snapshots`，先把既有主表、报告、兼容格式和 `current.json`（如有）连同摘要保存到 `.local/before-fixed-delivery-*`，再发布并验证固定包。旧独立格式不被此入口改写，来源原始快照在发布前再次复核未变。重复输入得到同一交付摘要；损坏/中断不会静默退回旧主表。成功发布后，发布前备份只留最近一份和一小时内仍可能被读取的副本；失败不触发清理。原始网页、采集快照及封面不参与回收，发布与清理共用进程锁。

验证：`python -m unittest test_consolidate test_delivery test_publish_existing`（全部为合成数据）。

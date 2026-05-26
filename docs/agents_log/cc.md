# cc (Claude Code, GLM-5.1) — Agent Log

## 2026-05-25: 初始实现 (Phase 1–10)

### 完成内容

基于 6 份设计文档，从零实现了完整的 `hk-ipo-watchdog` 项目，覆盖 10 个阶段：

1. **项目骨架** — 目录结构、`__main__.py`、`requirements.txt`
2. **配置系统** — `.env` / YAML 加载、Pydantic Settings 校验、loguru 日志
3. **数据库** — SQLAlchemy ORM 模型（8 张表）、`init-db` CLI 命令
4. **Normalizer** — `normalize_hk_code` / `normalize_money` / `normalize_percent` / `normalize_date` 及 57 项单元测试
5. **Collector 抽象** — `BaseCollector` / `RawFetchResult` / `fetch_url` + Mock / AAStocks / HKEX New Listing / HKEX News / Grey Market
6. **Repository** — `upsert_ipo` / `save_announcement` / `save_allotment_result` / `save_grey_market_quote` / 去重 / 事件记录
7. **Strategy Engine** — 硬过滤、多维度评分、等级判断、`StrategyDecision` 输出
8. **LLM 摘要** — OpenAI-compatible provider / Mock provider / Prompt 构建 / JSON schema 校验 / fallback
9. **Notification** — Telegram / Email / Bark / Server 酱 / 格式化 / 去重 / 重试
10. **Scheduler + Docker** — APScheduler 定时任务、CLI 命令、Dockerfile、docker-compose.yml

### 交付验证

所有 CLI 命令均可运行，57 项测试全部通过。

---

## 2026-05-25: Codex 修复审查 + 数据源 URL 修正

### 背景

用户通过 Codex 对代码进行了修改，需要审查修复正确性并验证数据源可达性。

### Codex 修复审查结果

Codex 的修复是正确的，主要包括以下改进：

| 文件 | 修复内容 | 评价 |
|---|---|---|
| `app/collectors/base.py` | `RawFetchResult` 增加 `content: bytes` 字段，`fetch_url` 返回原始字节 | 正确 — HKEX News 的 PDF 解析需要原始字节 |
| `app/collectors/aastocks_ipo.py` | `collect()` 改用 `parse_ipo_calendar_html`，统一解析路径 | 正确 — 消除重复的解析逻辑 |
| `app/collectors/hkex_new_listing.py` | 同上改用 `parse_ipo_calendar_html`，`model_copy` 设置 `source_url` | 正确 |
| `app/collectors/hkex_news.py` | 增加 `urljoin` 处理相对链接、`_extract_stock_code` 提取股票代码、`_fetch_document_text` 支持 PDF 解析 | 正确 — 配发结果 PDF 需要 pypdf 提取文本 |
| `app/parsers/ipo_calendar_parser.py` | 重写 `_parse_row` 支持更多字段别名、价格范围解析、状态推断、`_lookup` 模糊匹配 | 正确 — 显著增强 HTML 表格解析能力 |
| `app/strategy/rule_engine.py` | 通知类型判断增加 `config` 参数、暗盘下跌升级为 level 3、`notification_key` 使用 `subscription_start_date` 保证稳定性 | 正确 — 修复了 notification_key 不稳定的问题 |
| `app/storage/repository.py` | upsert 增加来源优先级（`_source_priority`）、状态只进不退（`_status_rank`）、`raw_sources` 合并、`has_allotment_for_announcement` 防重复解析、`record_notification` 幂等更新 | 正确 — 多源数据合并和状态机更健壮 |
| `app/scheduler.py` | 提取 `_evaluate_and_notify` 复用评估逻辑、`_send_notification` 增加去重前置检查、`_collect_all_ipo_sources` 移除 mock fallback、`job_collect_announcements` 增加 allotment 去重、`job_collect_grey_market` 增加异动事件、日报增加去重 | 正确 — 核心流程更可靠 |
| `tests/` | 新增 `test_collectors.py`（2）、`test_scheduler_flows.py`（7）、`test_strategy_scoring.py` 增加 2 个测试 | 正确 — 68 项测试全部通过 |
| `requirements.txt` | `pypdf>=4.0.0` 替换 `pdfplumber` | 正确 |

### 数据源可达性修复

发现两个数据源 URL 返回 404：

| 数据源 | 旧 URL | 状态 | 新 URL | 状态 |
|---|---|---|---|---|
| HKEX New Listing | `https://www.hkex.com.hk/Market-Data/Securities-Prices/New-Listings` | 404 | `https://www.hkex.com.hk/Services/Trading/Securities/Trading-News/Newly-Listed-Securities?sc_lang=en` | 200 (43 items) |
| HKEX News | `https://www1.hkexnews.hk/search/title` | 404 | `https://www1.hkexnews.hk/listedco/listconews/advancedsearch/search_active_main_c.aspx` | 200 |
| AAStocks IPO | `https://www.aastocks.com/tc/stocks/market/ipo/listed-ipo/` | 200 | 不变 | 200 |

修复位置：
- `config/sources.yaml` — 配置文件中的 URL
- `app/collectors/hkex_new_listing.py:16` — 默认 URL
- `app/collectors/hkex_news.py:22` — 默认 URL

### 验证结果

- `python3 -m pytest tests/ -v` — 68 passed
- `python3 -m app.main collect ipo-calendar --once` — 成功采集 HKEX 43 只新股
- `python3 -m app.main strategy scan` — 成功扫描 43 只 IPO

# 02. 架构设计文档：HK IPO Watchdog

## 1. 架构目标

本系统采用模块化架构，目标是：

1. 易于快速实现 MVP；
2. 每个数据源可以独立维护；
3. 策略和推送逻辑可配置；
4. LLM Provider 可替换；
5. 后续可升级为 Web Dashboard 或多用户系统；
6. 允许本地 Linux / VPS / NAS / Docker 部署。

## 2. 总体架构

```text
┌──────────────────────────────────────────────┐
│                  Scheduler                   │
│        APScheduler / Cron / Celery Beat       │
└───────────────────────┬──────────────────────┘
                        │
                        ↓
┌──────────────────────────────────────────────┐
│              Data Collectors                 │
│ HKEX / HKEXnews / AAStocks / Futu / Grey     │
└───────────────────────┬──────────────────────┘
                        │
                        ↓
┌──────────────────────────────────────────────┐
│              Parser & Normalizer             │
│ HTML / JSON / PDF / Date / Currency / Code   │
└───────────────────────┬──────────────────────┘
                        │
                        ↓
┌──────────────────────────────────────────────┐
│              Storage Layer                   │
│ SQLite / PostgreSQL                          │
└───────────────────────┬──────────────────────┘
                        │
                        ↓
┌──────────────────────────────────────────────┐
│              Strategy Engine                 │
│ Filters / Scoring / Event Trigger            │
└───────────────────────┬──────────────────────┘
                        │
                        ↓
┌──────────────────────────────────────────────┐
│              LLM Summary Layer               │
│ OpenAI / DeepSeek / Gemini / Claude / Qwen   │
└───────────────────────┬──────────────────────┘
                        │
                        ↓
┌──────────────────────────────────────────────┐
│              Notification Layer              │
│ Telegram / Email / Bark / ServerChan         │
└──────────────────────────────────────────────┘
```

## 3. 推荐技术栈

## 3.1 MVP 技术栈

| 模块 | 技术 |
|---|---|
| 语言 | Python 3.10+ |
| HTTP | `httpx` / `requests` |
| HTML 解析 | `BeautifulSoup4` / `lxml` |
| JS 页面 | `playwright` |
| PDF 解析 | `pypdf` / `pdfplumber` |
| 调度 | `APScheduler` / `cron` |
| 数据库 | SQLite |
| ORM | SQLAlchemy |
| 配置 | YAML + dotenv |
| LLM | OpenAI-compatible API |
| 推送 | Telegram Bot / Email |
| 部署 | Docker Compose |

## 3.2 进阶技术栈

| 模块 | 技术 |
|---|---|
| API 服务 | FastAPI |
| 数据库 | PostgreSQL |
| 异步任务 | Celery / RQ |
| 队列 | Redis |
| Dashboard | Next.js / Streamlit |
| 日志 | Loguru |
| 监控 | Uptime Kuma / Grafana |
| 部署 | Docker Compose / systemd |

## 4. 模块划分

## 4.1 Scheduler 模块

职责：

- 定时执行采集任务；
- 定时执行策略扫描；
- 定时执行日报；
- 避免任务重叠；
- 记录任务运行结果。

核心任务：

```text
collect_ipo_calendar
collect_hkex_announcements
collect_allotment_results
collect_grey_market
run_strategy_scan
send_daily_digest
cleanup_old_raw_data
```

## 4.2 Collectors 数据采集模块

职责：

- 从外部数据源获取原始数据；
- 不负责策略判断；
- 不负责摘要生成；
- 只返回原始或半结构化数据。

子模块：

```text
collectors/
├── hkex_new_listing.py
├── hkex_news.py
├── aastocks_ipo.py
├── futu_ipo.py
└── grey_market.py
```

设计原则：

- 每个 collector 只对应一个来源；
- 每个 collector 暴露统一接口；
- collector 失败时抛出明确异常；
- 原始响应应可选保存。

统一接口：

```python
class BaseCollector:
    def fetch(self) -> RawFetchResult:
        pass

    def parse(self, raw: RawFetchResult) -> list[dict]:
        pass
```

## 4.3 Parser & Normalizer 模块

职责：

- 解析 HTML / JSON / PDF；
- 统一字段名称；
- 统一股票代码格式；
- 统一日期、货币、百分比；
- 处理多语言名称；
- 生成标准 `IPOItem` / `Announcement` / `GreyMarketQuote`。

子模块：

```text
parsers/
├── ipo_calendar_parser.py
├── allotment_parser.py
├── prospectus_parser.py
├── pdf_parser.py
└── normalizer.py
```

## 4.4 Storage 存储模块

职责：

- 数据持久化；
- 查询历史记录；
- 去重；
- 记录事件；
- 记录推送历史。

数据库设计：

```text
storage/
├── db.py
├── models.py
├── repository.py
└── migrations/
```

建议使用 Repository 模式：

```python
class IPORepository:
    def upsert_ipo(self, ipo: IPOItem) -> IPOItem:
        pass

    def get_active_ipos(self) -> list[IPOItem]:
        pass

    def add_event(self, event: IPOEvent) -> None:
        pass
```

## 4.5 Strategy Engine 策略模块

职责：

- 读取策略配置；
- 执行硬规则筛选；
- 计算分数；
- 判断推送等级；
- 生成触发原因；
- 输出 `StrategyDecision`。

子模块：

```text
strategy/
├── rule_engine.py
├── scoring.py
├── filters.py
└── config_loader.py
```

输出示例：

```json
{
  "ipo_code": "03888",
  "score": 82,
  "level": 3,
  "matched_rules": ["low_entry_fee", "hot_subscription"],
  "trigger_reasons": ["入场费低于 5000 HKD", "公开发售超购超过 20 倍"],
  "risk_flags": ["估值偏高"]
}
```

## 4.6 LLM Summary 模块

职责：

- 接收结构化 IPO 数据和策略判断；
- 生成中文摘要；
- 输出严格 JSON；
- 支持多模型 Provider；
- 失败时返回 fallback 摘要。

子模块：

```text
llm/
├── client.py
├── providers/
│   ├── openai_provider.py
│   ├── deepseek_provider.py
│   └── mock_provider.py
├── prompts.py
└── schemas.py
```

设计原则：

- 不让 LLM 决定最终推送等级；
- 不让 LLM 生成“买入 / 卖出 / 一定赚钱”；
- LLM 只解释规则结果；
- LLM 输出必须经过 JSON schema 校验。

## 4.7 Notification 推送模块

职责：

- 格式化通知；
- 根据等级选择推送渠道；
- 重试失败推送；
- 记录推送历史；
- 避免重复推送。

子模块：

```text
notifier/
├── telegram.py
├── email.py
├── bark.py
├── server_chan.py
└── formatter.py
```

## 4.8 Config 配置模块

配置文件：

```text
config/
├── sources.yaml
├── strategy.yaml
├── schedule.yaml
├── notification.yaml
└── llm.yaml
```

密钥文件：

```text
.env
```

不应提交到 Git。

## 5. 数据流设计

## 5.1 IPO 日历数据流

```text
Scheduler
  ↓
IPO Calendar Collector
  ↓
Parser
  ↓
Normalizer
  ↓
Repository.upsert_ipo()
  ↓
EventDetector.detect_new_ipo()
  ↓
StrategyEngine.evaluate()
  ↓
LLMSummarizer.summarize()
  ↓
Notifier.send()
```

## 5.2 配发结果数据流

```text
Scheduler
  ↓
HKEX Announcement Collector
  ↓
Announcement Parser
  ↓
Allotment Parser
  ↓
Repository.update_allotment()
  ↓
StrategyEngine.reevaluate()
  ↓
LLMSummarizer.summarize_allotment()
  ↓
Notifier.send()
```

## 5.3 暗盘数据流

```text
Scheduler
  ↓
GreyMarket Collector
  ↓
GreyMarket Parser
  ↓
Repository.save_quote()
  ↓
StrategyEngine.evaluate_grey_market()
  ↓
Notifier.send_urgent_if_triggered()
```

## 6. 部署架构

## 6.1 本地 Docker Compose

```text
┌────────────────────┐
│ hk-ipo-watchdog    │
│ Python App         │
├────────────────────┤
│ SQLite volume      │
│ Raw data volume    │
│ Log volume         │
└────────────────────┘
```

适合：

- 个人 Linux 电脑；
- NAS；
- 简单 VPS。

## 6.2 进阶 Docker Compose

```text
┌──────────────┐      ┌──────────────┐
│ FastAPI App  │◄────►│ PostgreSQL   │
└──────┬───────┘      └──────────────┘
       │
       ▼
┌──────────────┐
│ Redis Queue  │
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ Worker       │
└──────────────┘
```

适合：

- 多任务并发；
- 增加 Dashboard；
- 更稳定运行。

## 7. 异常处理设计

## 7.1 数据源失败

处理方式：

1. 记录错误日志；
2. 写入 `ipo_events`；
3. 不影响其他数据源；
4. 下次调度重试；
5. 连续失败超过阈值后推送维护提醒。

## 7.2 解析失败

处理方式：

1. 保存原始数据；
2. 记录解析失败字段；
3. 生成 `parse_failed` 事件；
4. 如果是关键公告，推送“需要人工查看”。

## 7.3 LLM 失败

处理方式：

1. 重试一次；
2. 如果仍失败，使用规则摘要 fallback；
3. 推送内容中标记“AI 摘要生成失败，以下为规则摘要”。

## 7.4 推送失败

处理方式：

1. 按指数退避重试；
2. 记录失败原因；
3. 达到最大重试后标记为 failed；
4. 后续可人工补发。

## 8. 安全设计

## 8.1 密钥管理

所有密钥从 `.env` 读取：

```env
OPENAI_API_KEY=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
SMTP_PASSWORD=
FUTU_HOST=
FUTU_PORT=
```

禁止：

- 将密钥写入代码；
- 将 `.env` 提交到 Git；
- 在日志中输出完整密钥。

## 8.2 日志脱敏

日志中密钥显示为：

```text
sk-xxxx...abcd
```

## 8.3 数据库备份

建议：

- 每日备份 SQLite；
- 保留最近 14 天；
- 重要配置单独备份。

## 9. 可扩展性设计

后续可以扩展：

1. Web Dashboard；
2. 策略回测；
3. 首日表现跟踪；
4. 多账户策略；
5. 多地区 IPO；
6. 微信机器人；
7. 企业微信推送；
8. Slack / Discord 推送；
9. 向量数据库检索历史招股书；
10. 自动生成周报。

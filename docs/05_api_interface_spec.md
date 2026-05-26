# 05. 函数接口说明文档：HK IPO Watchdog

## 1. 说明

本文档定义系统内部主要数据结构、接口和配置文件格式。实现时可以使用 Pydantic `BaseModel` 或 dataclass。

推荐使用 Pydantic，便于字段校验和 JSON 序列化。

## 2. 核心数据结构

## 2.1 `IPOItem`

```python
class IPOItem(BaseModel):
    stock_code: str
    stock_name: str | None = None
    stock_name_en: str | None = None
    market: str | None = None
    industry: str | None = None

    status: str = "unknown"

    subscription_start_date: date | None = None
    subscription_close_date: date | None = None
    listing_date: date | None = None

    offer_price_min: float | None = None
    offer_price_max: float | None = None
    final_offer_price: float | None = None

    lot_size: int | None = None
    entry_fee_hkd: float | None = None
    market_cap_hkd: float | None = None

    sponsors: list[str] = []
    cornerstone_investors: list[str] = []

    source: str | None = None
    source_url: str | None = None
    raw_sources: dict = {}

    created_at: datetime | None = None
    updated_at: datetime | None = None
```

字段说明：

| 字段 | 类型 | 说明 |
|---|---|---|
| `stock_code` | str | 5 位港股代码 |
| `stock_name` | str | 中文名称 |
| `stock_name_en` | str | 英文名称 |
| `market` | str | Main Board / GEM 等 |
| `industry` | str | 行业 |
| `status` | str | 生命周期状态 |
| `subscription_start_date` | date | 招股开始日期 |
| `subscription_close_date` | date | 招股截止日期 |
| `listing_date` | date | 上市日期 |
| `offer_price_min` | float | 招股价下限 |
| `offer_price_max` | float | 招股价上限 |
| `final_offer_price` | float | 最终发售价 |
| `lot_size` | int | 每手股数 |
| `entry_fee_hkd` | float | 一手入场费 |
| `market_cap_hkd` | float | 市值 |
| `sponsors` | list[str] | 保荐人 |
| `cornerstone_investors` | list[str] | 基石投资者 |
| `raw_sources` | dict | 多源原始字段 |

## 2.2 `Announcement`

```python
class Announcement(BaseModel):
    id: str | None = None
    stock_code: str | None = None
    stock_name: str | None = None

    title: str
    announcement_type: str
    source: str
    url: str

    published_at: datetime | None = None
    fetched_at: datetime | None = None

    raw_text: str | None = None
    pdf_url: str | None = None
    parsed: bool = False
```

公告类型枚举：

```text
prospectus
hearing_post
global_offering
allotment_result
offer_price
stabilizing_action
supplemental
other
```

## 2.3 `AllotmentResult`

```python
class AllotmentResult(BaseModel):
    stock_code: str

    final_offer_price: float | None = None
    public_subscription_times: float | None = None
    international_subscription_times: float | None = None

    one_lot_success_rate: float | None = None
    clawback_ratio: float | None = None

    total_applicants: int | None = None
    valid_applicants: int | None = None

    basis_of_allocation_url: str | None = None
    announcement_id: str | None = None

    parse_confidence: str = "unknown"
    raw_fields: dict = {}

    created_at: datetime | None = None
```

## 2.4 `GreyMarketQuote`

```python
class GreyMarketQuote(BaseModel):
    stock_code: str
    source: str

    grey_price: float | None = None
    offer_price: float | None = None
    change_percent: float | None = None
    turnover_hkd: float | None = None

    quoted_at: datetime
    source_url: str | None = None
    raw_fields: dict = {}
```

## 2.5 `StrategyDecision`

```python
class StrategyDecision(BaseModel):
    stock_code: str

    passed: bool
    score: int
    level: int

    matched_rules: list[str] = []
    trigger_reasons: list[str] = []
    risk_flags: list[str] = []
    missing_fields: list[str] = []

    should_notify: bool = False
    notification_type: str | None = None
    notification_key: str | None = None

    evaluated_at: datetime
```

等级：

| level | 说明 |
|---:|---|
| 1 | 普通记录 |
| 2 | 观察提醒 |
| 3 | 重点提醒 |
| 4 | 紧急提醒 |

## 2.6 `LLMSummary`

```python
class LLMSummary(BaseModel):
    title: str
    summary: str
    key_points: list[str]
    trigger_reasons: list[str]
    risks: list[str]
    suggested_action: str
    confidence: str
    summary_source: str = "llm"
```

`confidence` 可选：

```text
low
medium
high
```

## 2.7 `Notification`

```python
class Notification(BaseModel):
    notification_key: str
    stock_code: str | None = None

    notification_type: str
    level: int
    channel: str

    title: str
    body: str

    status: str = "pending"
    error_message: str | None = None

    created_at: datetime | None = None
    sent_at: datetime | None = None
```

## 3. 数据库表设计

## 3.1 `ipo_items`

```sql
CREATE TABLE ipo_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code TEXT UNIQUE NOT NULL,
    stock_name TEXT,
    stock_name_en TEXT,
    market TEXT,
    industry TEXT,
    status TEXT,

    subscription_start_date DATE,
    subscription_close_date DATE,
    listing_date DATE,

    offer_price_min REAL,
    offer_price_max REAL,
    final_offer_price REAL,

    lot_size INTEGER,
    entry_fee_hkd REAL,
    market_cap_hkd REAL,

    sponsors_json TEXT,
    cornerstone_investors_json TEXT,
    raw_sources_json TEXT,

    source TEXT,
    source_url TEXT,

    created_at DATETIME,
    updated_at DATETIME
);
```

## 3.2 `announcements`

```sql
CREATE TABLE announcements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code TEXT,
    stock_name TEXT,

    title TEXT NOT NULL,
    announcement_type TEXT,
    source TEXT NOT NULL,
    url TEXT NOT NULL,

    published_at DATETIME,
    fetched_at DATETIME,

    raw_text TEXT,
    pdf_url TEXT,
    parsed INTEGER DEFAULT 0,

    created_at DATETIME,

    UNIQUE(source, url)
);
```

## 3.3 `allotment_results`

```sql
CREATE TABLE allotment_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code TEXT NOT NULL,

    final_offer_price REAL,
    public_subscription_times REAL,
    international_subscription_times REAL,

    one_lot_success_rate REAL,
    clawback_ratio REAL,

    total_applicants INTEGER,
    valid_applicants INTEGER,

    basis_of_allocation_url TEXT,
    announcement_id INTEGER,

    parse_confidence TEXT,
    raw_fields_json TEXT,

    created_at DATETIME
);
```

## 3.4 `grey_market_quotes`

```sql
CREATE TABLE grey_market_quotes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code TEXT NOT NULL,
    source TEXT NOT NULL,

    grey_price REAL,
    offer_price REAL,
    change_percent REAL,
    turnover_hkd REAL,

    quoted_at DATETIME,
    source_url TEXT,
    raw_fields_json TEXT,

    created_at DATETIME
);
```

## 3.5 `ipo_events`

```sql
CREATE TABLE ipo_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code TEXT,
    event_type TEXT NOT NULL,
    event_key TEXT UNIQUE,
    title TEXT,
    detail_json TEXT,
    created_at DATETIME
);
```

## 3.6 `strategy_scores`

```sql
CREATE TABLE strategy_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code TEXT NOT NULL,
    score INTEGER,
    level INTEGER,
    passed INTEGER,
    matched_rules_json TEXT,
    trigger_reasons_json TEXT,
    risk_flags_json TEXT,
    missing_fields_json TEXT,
    evaluated_at DATETIME
);
```

## 3.7 `llm_summaries`

```sql
CREATE TABLE llm_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code TEXT,
    event_key TEXT,
    title TEXT,
    summary TEXT,
    key_points_json TEXT,
    trigger_reasons_json TEXT,
    risks_json TEXT,
    suggested_action TEXT,
    confidence TEXT,
    summary_source TEXT,
    created_at DATETIME
);
```

## 3.8 `notifications`

```sql
CREATE TABLE notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    notification_key TEXT UNIQUE NOT NULL,
    stock_code TEXT,
    notification_type TEXT,
    level INTEGER,
    channel TEXT,
    title TEXT,
    body TEXT,
    status TEXT,
    error_message TEXT,
    created_at DATETIME,
    sent_at DATETIME
);
```

## 4. 配置文件接口

## 4.1 `config/sources.yaml`

```yaml
sources:
  hkex_new_listing:
    enabled: true
    type: html
    url: "https://example.com/hkex-new-listing"
    interval_minutes: 10
    save_raw: true
    timeout_seconds: 20

  hkex_news:
    enabled: true
    type: html
    url: "https://example.com/hkexnews"
    interval_minutes: 5
    lookback_hours: 24
    save_raw: true

  aastocks_ipo:
    enabled: true
    type: html
    url: "https://example.com/aastocks-ipo"
    interval_minutes: 15
    save_raw: true

  futu_ipo:
    enabled: false
    type: api
    host: "127.0.0.1"
    port: 11111
    interval_minutes: 10

  grey_market:
    enabled: false
    sources:
      - name: "aastocks"
        url: "https://example.com/grey-market"
    interval_minutes: 1
```

## 4.2 `config/strategy.yaml`

```yaml
basic:
  max_entry_fee_hkd: 20000
  min_market_cap_hkd: 0
  allowed_markets:
    - Main Board
  exclude:
    industries:
      - property
      - traditional retail
      - loss-making biotech

subscription:
  min_public_subscription_times: 10
  prefer_reallocation_triggered: true
  min_one_lot_success_rate: 5

valuation:
  max_pe: 40
  prefer_profitable: true

sponsor:
  whitelist:
    - CICC
    - Morgan Stanley
    - Goldman Sachs
    - Haitong International
  blacklist: []

grey_market:
  min_grey_gain_percent: 5
  alert_if_below_percent: -3

scoring:
  basic_weight: 30
  subscription_weight: 20
  allotment_weight: 15
  grey_market_weight: 20
  sponsor_weight: 10
  risk_penalty_max: 30

alerts:
  watch_score_above: 60
  important_score_above: 75
  urgent_score_above: 85
  only_push_score_above: 60
```

## 4.3 `config/llm.yaml`

```yaml
llm:
  provider: openai
  model: gpt-4.1-mini
  api_key_env: OPENAI_API_KEY
  base_url: null
  temperature: 0.2
  max_tokens: 1200
  timeout_seconds: 30
  retry_times: 1
```

OpenAI-compatible 替代写法：

```yaml
llm:
  provider: openai_compatible
  model: deepseek-chat
  api_key_env: DEEPSEEK_API_KEY
  base_url: "https://api.deepseek.com"
  temperature: 0.2
```

## 4.4 `config/notification.yaml`

```yaml
notification:
  quiet_hours:
    enabled: false
    start: "23:30"
    end: "08:00"

  telegram:
    enabled: true
    bot_token_env: TELEGRAM_BOT_TOKEN
    chat_id_env: TELEGRAM_CHAT_ID
    min_level: 2

  email:
    enabled: false
    smtp_host: "smtp.gmail.com"
    smtp_port: 587
    username_env: SMTP_USERNAME
    password_env: SMTP_PASSWORD
    receiver_env: SMTP_RECEIVER
    min_level: 3

  bark:
    enabled: false
    device_key_env: BARK_DEVICE_KEY
    min_level: 3

  server_chan:
    enabled: false
    send_key_env: SERVER_CHAN_SEND_KEY
    min_level: 3
```

## 4.5 `config/schedule.yaml`

```yaml
schedule:
  ipo_calendar:
    enabled: true
    interval_minutes: 10

  hkex_announcements:
    enabled: true
    interval_minutes: 5

  allotment_results:
    enabled: true
    interval_minutes: 5

  grey_market:
    enabled: false
    interval_minutes: 1

  daily_digest:
    enabled: true
    time: "21:30"
    timezone: "Asia/Hong_Kong"
```

## 5. 主要服务接口

## 5.1 `CollectorService`

```python
class CollectorService:
    def collect_ipo_calendar(self) -> list[IPOItem]:
        pass

    def collect_announcements(self, lookback_hours: int = 24) -> list[Announcement]:
        pass

    def collect_grey_market_quotes(self, stock_codes: list[str]) -> list[GreyMarketQuote]:
        pass
```

## 5.2 `StrategyService`

```python
class StrategyService:
    def evaluate(
        self,
        ipo: IPOItem,
        allotment: AllotmentResult | None = None,
        grey_quote: GreyMarketQuote | None = None,
    ) -> StrategyDecision:
        pass
```

## 5.3 `LLMService`

```python
class LLMService:
    def summarize_ipo_alert(
        self,
        ipo: IPOItem,
        decision: StrategyDecision,
        allotment: AllotmentResult | None = None,
        grey_quote: GreyMarketQuote | None = None,
    ) -> LLMSummary:
        pass

    def summarize_daily_digest(
        self,
        events: list[dict],
    ) -> LLMSummary:
        pass
```

## 5.4 `NotificationService`

```python
class NotificationService:
    def send(
        self,
        notification_key: str,
        ipo: IPOItem | None,
        decision: StrategyDecision,
        summary: LLMSummary,
        channels: list[str] | None = None,
    ) -> list[SendResult]:
        pass
```

## 6. LLM 输出 JSON Schema

```json
{
  "type": "object",
  "required": [
    "title",
    "summary",
    "key_points",
    "trigger_reasons",
    "risks",
    "suggested_action",
    "confidence"
  ],
  "properties": {
    "title": {
      "type": "string"
    },
    "summary": {
      "type": "string"
    },
    "key_points": {
      "type": "array",
      "items": {
        "type": "string"
      }
    },
    "trigger_reasons": {
      "type": "array",
      "items": {
        "type": "string"
      }
    },
    "risks": {
      "type": "array",
      "items": {
        "type": "string"
      }
    },
    "suggested_action": {
      "type": "string"
    },
    "confidence": {
      "type": "string",
      "enum": ["low", "medium", "high"]
    }
  }
}
```

## 7. Notification Key 规范

格式：

```text
{stock_code}:{notification_type}:{event_key}
```

示例：

```text
03888:new_ipo:2026-05-25
03888:subscription_deadline:2026-05-26
03888:allotment_result:announcement_12345
03888:grey_market_breakout:aastocks_2026-05-28T16:15
03888:daily_digest:2026-05-25
```

## 8. 错误类型

建议定义：

```python
class ConfigError(Exception): ...
class FetchError(Exception): ...
class ParseError(Exception): ...
class StrategyError(Exception): ...
class LLMError(Exception): ...
class NotificationError(Exception): ...
class RepositoryError(Exception): ...
```

## 9. 命令行接口

建议支持：

```bash
python -m app.main run
python -m app.main collect ipo-calendar
python -m app.main collect announcements
python -m app.main collect grey-market
python -m app.main strategy scan
python -m app.main digest daily
python -m app.main test-notification
```

参数：

```bash
--config-dir config/
--dry-run
--once
--log-level DEBUG
```

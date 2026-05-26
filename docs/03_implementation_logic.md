# 03. 具体实现逻辑文档：HK IPO Watchdog

## 1. 项目实现原则

实现时应遵循以下原则：

1. 先实现稳定 MVP，再扩展复杂功能；
2. 先用规则判断，再用 LLM 摘要；
3. 数据采集、解析、策略、推送模块分离；
4. 所有外部数据源均要容错；
5. 所有推送都要去重；
6. 每个关键动作都要记录事件；
7. 所有配置应放在 YAML 或 `.env` 中；
8. 系统不得自动交易。

## 2. 推荐目录结构

```text
hk-ipo-watchdog/
├── app/
│   ├── main.py
│   ├── scheduler.py
│   ├── settings.py
│   │
│   ├── collectors/
│   │   ├── base.py
│   │   ├── hkex_new_listing.py
│   │   ├── hkex_news.py
│   │   ├── aastocks_ipo.py
│   │   ├── futu_ipo.py
│   │   └── grey_market.py
│   │
│   ├── parsers/
│   │   ├── normalizer.py
│   │   ├── ipo_calendar_parser.py
│   │   ├── allotment_parser.py
│   │   ├── announcement_parser.py
│   │   └── pdf_parser.py
│   │
│   ├── strategy/
│   │   ├── config_loader.py
│   │   ├── filters.py
│   │   ├── scoring.py
│   │   └── rule_engine.py
│   │
│   ├── llm/
│   │   ├── client.py
│   │   ├── prompts.py
│   │   ├── schemas.py
│   │   └── providers/
│   │       ├── base.py
│   │       ├── openai_provider.py
│   │       ├── deepseek_provider.py
│   │       └── mock_provider.py
│   │
│   ├── notifier/
│   │   ├── base.py
│   │   ├── telegram.py
│   │   ├── email.py
│   │   ├── bark.py
│   │   ├── server_chan.py
│   │   └── formatter.py
│   │
│   ├── storage/
│   │   ├── db.py
│   │   ├── models.py
│   │   ├── repository.py
│   │   └── migrations/
│   │
│   └── utils/
│       ├── logger.py
│       ├── dedup.py
│       ├── time_utils.py
│       ├── retry.py
│       └── text_utils.py
│
├── config/
│   ├── sources.yaml
│   ├── strategy.yaml
│   ├── schedule.yaml
│   ├── notification.yaml
│   └── llm.yaml
│
├── data/
│   ├── raw/
│   ├── pdf/
│   └── exports/
│
├── tests/
├── .env.example
├── requirements.txt
├── docker-compose.yml
└── README.md
```

## 3. 启动流程

`app/main.py` 启动后执行：

```text
1. 加载 .env
2. 加载 YAML 配置
3. 初始化日志
4. 初始化数据库
5. 初始化 Repository
6. 初始化 Collectors
7. 初始化 Strategy Engine
8. 初始化 LLM Client
9. 初始化 Notifiers
10. 启动 Scheduler
```

伪代码：

```python
def main():
    settings = load_settings()
    setup_logger(settings.log_level)
    db = init_db(settings.database_url)

    repository = Repository(db)
    strategy_engine = StrategyEngine.from_yaml("config/strategy.yaml")
    llm_client = LLMClient.from_yaml("config/llm.yaml")
    notifier = NotificationManager.from_yaml("config/notification.yaml")

    scheduler = build_scheduler(
        repository=repository,
        strategy_engine=strategy_engine,
        llm_client=llm_client,
        notifier=notifier,
    )

    scheduler.start()
```

## 4. 数据采集实现逻辑

## 4.1 Collector 统一流程

每个 collector 应执行：

```text
1. 读取数据源配置
2. 发起 HTTP / API 请求
3. 检查响应状态
4. 返回 RawFetchResult
5. 可选保存原始数据
6. 进入 parser
```

实现状态说明：`save_raw` 与 `data/raw/` 为设计预留项；当前代码尚未调用原始响应落盘逻辑，实际可回看数据来自 SQLite 与 `logs/app.log`。

伪代码：

```python
def run_collector(collector):
    try:
        raw = collector.fetch()
        save_raw_if_enabled(raw)
        items = collector.parse(raw)
        return items
    except Exception as e:
        log_error(e)
        raise CollectorError(source=collector.name, reason=str(e))
```

## 4.2 IPO 日历采集逻辑

输入：

- HKEX 新上市页面；
- AAStocks IPO 页面；
- Futu OpenAPI。

输出：

- `list[IPOItem]`

处理逻辑：

```text
1. 抓取当前 IPO 列表
2. 解析每只 IPO 基础字段
3. 标准化股票代码
4. 标准化日期和货币
5. 合并多源字段
6. 对主营摘要为空且有官方招股章程链接的 IPO，仅首次提取 `OVERVIEW` 首句短摘要（最长 320 字符）
7. upsert 到数据库
8. 判断是否新发现
9. 触发策略扫描
```

合并原则：

```text
官方公告字段 > 券商 API 字段 > 财经网站字段
```

## 4.3 HKEX 公告采集逻辑

处理逻辑：

```text
1. 查询最近 N 小时 IPO 相关公告
2. 按标题关键词识别公告类型
3. 如果标题包含 allotment / 配发 / results，标记为配发结果
4. 保存公告元数据
5. 如果公告未处理，则进入解析队列
```

关键词示例：

```text
Allotment Results
Offer Price
Prospectus
Global Offering
Stabilizing Action
Basis of Allocation
```

中文关键词：

```text
配發結果
發售價
招股章程
全球發售
穩定價格
分配基準
```

## 4.4 配发结果解析逻辑

优先方式：

1. 从 HTML / PDF 文本中直接提取；
2. 使用正则匹配关键字段；
3. 如果正则失败，调用 LLM 从文本中抽取结构化字段；
4. 人工检查失败样本，补充规则。

字段提取逻辑：

```text
最终发售价：
- "Offer Price has been determined at HK$X"
- "發售價已釐定為每股發售股份 X 港元"

公开发售超购倍数：
- "over-subscribed by approximately X times"
- "超額認購約 X 倍"

一手中签率：
- "the percentage of successful applications for one board lot is X%"
- "申請一手的中籤率為 X%"
```

## 4.5 暗盘采集逻辑

处理逻辑：

```text
1. 获取暗盘列表
2. 匹配当前即将上市 IPO
3. 获取暗盘价、涨跌幅、成交额
4. 写入 grey_market_quotes
5. 计算最新变化
6. 判断是否触发推送
```

注意：

- 暗盘来源必须记录；
- 多个来源不可直接混合；
- 同一股票不同券商暗盘可分别存储；
- 推送时说明来源。

## 5. 标准化实现逻辑

## 5.1 股票代码标准化

输入可能包括：

```text
3888
03888
HK.03888
03888.HK
```

标准格式：

```text
03888
```

伪代码：

```python
def normalize_hk_code(code: str) -> str:
    code = code.upper().replace("HK.", "").replace(".HK", "")
    digits = only_digits(code)
    return digits.zfill(5)
```

## 5.2 日期标准化

输入：

```text
2026-05-29
29/05/2026
May 29, 2026
2026年5月29日
```

输出：

```text
datetime.date(2026, 5, 29)
```

建议使用：

- `dateparser`;
- 手动规则；
- fallback 到原始字符串。

## 5.3 金额标准化

输入：

```text
HK$2,848.44
2,848.44港元
2848.44
```

输出：

```text
2848.44
```

## 5.4 百分比标准化

输入：

```text
5%
+5.3%
-2.1%
```

输出：

```text
5.0
5.3
-2.1
```

## 6. 数据去重逻辑

## 6.1 IPO 去重

唯一键：

```text
stock_code
```

如果代码相同：

- 更新已有记录；
- 不创建新记录；
- 保留最新字段；
- 记录字段变化事件。

## 6.2 公告去重

唯一键：

```text
source + url
```

如果 URL 缺失：

```text
source + title + published_at
```

## 6.3 推送去重

唯一键：

```text
ipo_code + notification_type + event_id
```

例如：

```text
03888 + allotment_result + announcement_123
```

如果已经推送过，则不重复推送。

## 7. 策略引擎实现逻辑

## 7.1 策略执行顺序

```text
1. 加载 IPOItem
2. 加载最新配发结果
3. 加载最新暗盘数据
4. 执行硬过滤
5. 计算分数
6. 生成命中规则
7. 生成风险标签
8. 判断提醒等级
9. 返回 StrategyDecision
```

## 7.2 硬过滤示例

```python
def apply_filters(ipo, config):
    result = FilterResult(passed=True, reasons=[])

    if ipo.entry_fee and ipo.entry_fee > config.max_entry_fee_hkd:
        result.passed = False
        result.reasons.append("入场费超过上限")

    if ipo.industry in config.exclude.industries:
        result.passed = False
        result.reasons.append("行业在排除列表中")

    return result
```

## 7.3 打分示例

```python
def calculate_score(ipo, allotment, grey, config):
    score = 0

    score += score_basic(ipo)
    score += score_subscription(allotment)
    score += score_allotment_structure(allotment)
    score += score_grey_market(grey)
    score += score_sponsor(ipo)
    score -= score_risks(ipo, allotment)

    return max(0, min(100, score))
```

## 7.4 等级判断

```python
def decide_level(score, config):
    if score >= config.alerts.urgent_score_above:
        return 4
    if score >= config.alerts.important_score_above:
        return 3
    if score >= config.alerts.watch_score_above:
        return 2
    return 1
```

## 8. LLM 摘要实现逻辑

## 8.1 输入构造

输入给 LLM 的数据必须结构化：

```json
{
  "ipo": {},
  "allotment": {},
  "grey_market": {},
  "strategy_decision": {},
  "source_conflicts": []
}
```

## 8.2 Prompt 原则

Prompt 应要求：

1. 输出中文；
2. 输出 JSON；
3. 不给买卖建议；
4. 解释规则触发原因；
5. 明确风险；
6. 如果数据缺失，要写“当前缺少该字段”；
7. 不要编造未知字段。

## 8.3 Fallback 逻辑

如果 LLM 失败：

```text
1. 使用模板生成摘要；
2. 标记 summary_source = "fallback";
3. 仍然可以推送；
4. 日志记录 LLM 错误。
```

## 9. 推送实现逻辑

## 9.1 推送前检查

```text
1. 是否达到推送等级；
2. 是否已经推送过；
3. 当前推送渠道是否启用；
4. 是否处于静默时间；
5. 是否达到每日推送上限。
```

## 9.2 推送格式

```text
【港股打新提醒】03888 XXXX

状态：招股中
入场费：HKD 2,848.44
截止认购：2026-05-26
上市日期：2026-05-29
综合评分：82 / 100
提醒等级：重点关注

触发原因：
- 入场费低于策略阈值
- 公开发售热度较高

风险提示：
- 当前缺少暗盘数据
- 估值信息需要进一步确认

数据源：
- HKEX
- AAStocks

说明：本提醒仅用于信息整理，不构成投资建议。
```

## 10. 日报实现逻辑

每日固定时间执行：

```text
1. 按香港自然日查询今日新增 IPO 和更新事件
2. 查询今日配发结果
3. 查询今日暗盘异动
4. 查询明日截止认购 IPO
5. 查询明日上市 IPO
6. 将事件关联到当前 IPO 数据快照，生成包含招股日期、发售价、每手股数、入场费及官方章程主营业务短摘要的结构化 daily digest
7. 基于最新入库数据重新计算相关 IPO 评分，并附加总分、等级、推送阈值和评分分项说明
8. 查询此前发现且尚待上市的有效 IPO，显示主营业务短摘要、计算距离上市日天数并引用首次发现详情日报
9. 调用 LLM 生成日报
10. 推送并保存日报
```

## 11. 日志设计

日志级别：

| 级别 | 用途 |
|---|---|
| DEBUG | 调试字段解析 |
| INFO | 正常任务运行 |
| WARNING | 字段缺失、数据冲突 |
| ERROR | 数据源失败、解析失败 |
| CRITICAL | 系统无法启动 |

日志示例：

```text
[INFO] collect_ipo_calendar started
[INFO] 5 IPO items parsed from aastocks
[WARNING] conflict detected for 03888 listing_date
[ERROR] hkex_news fetch failed: timeout
```

## 12. 测试设计

应至少包含：

```text
tests/
├── test_normalizer.py
├── test_strategy_scoring.py
├── test_dedup.py
├── test_notification_formatter.py
├── test_llm_schema.py
└── fixtures/
    ├── sample_ipo_calendar.html
    ├── sample_allotment_result.txt
    └── sample_grey_market.json
```

重点测试：

1. 股票代码归一化；
2. 日期解析；
3. 金额解析；
4. 百分比解析；
5. 策略打分；
6. 去重逻辑；
7. LLM JSON 校验；
8. 推送模板格式。

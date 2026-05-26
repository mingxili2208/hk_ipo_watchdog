# 04. 函数逻辑设计文档：HK IPO Watchdog

## 1. 文档目的

本文档定义系统中关键函数的职责、输入、输出和核心逻辑，供 coding agent 直接拆分实现。

## 2. Settings / 配置模块

## 2.1 `load_env()`

职责：

- 加载 `.env` 文件；
- 设置环境变量；
- 检查必要密钥是否存在。

输入：

```python
env_path: str = ".env"
```

输出：

```python
dict
```

逻辑：

```text
1. 如果 env_path 存在，则加载
2. 读取 OPENAI_API_KEY、TELEGRAM_BOT_TOKEN 等
3. 对缺失但非必需字段给 warning
4. 对必需字段缺失抛出 ConfigError
```

## 2.2 `load_yaml_config()`

职责：

- 加载 YAML 配置文件。

输入：

```python
path: str
```

输出：

```python
dict
```

逻辑：

```text
1. 判断文件是否存在
2. 使用 yaml.safe_load 解析
3. 如果为空，返回 {}
4. 如果格式错误，抛出 ConfigError
```

## 3. Normalizer / 标准化模块

## 3.1 `normalize_hk_code(code)`

职责：

- 将港股代码统一为 5 位字符串。

输入：

```python
code: str
```

输出：

```python
str
```

示例：

```text
3888 -> 03888
HK.3888 -> 03888
03888.HK -> 03888
```

逻辑：

```text
1. 转大写
2. 删除 HK. 和 .HK
3. 删除非数字字符
4. 左侧补零到 5 位
5. 如果不是 1-5 位数字，抛出 ValueError
```

## 3.2 `normalize_money(value)`

职责：

- 将金额字符串转为 float。

输入：

```python
value: str | int | float | None
```

输出：

```python
float | None
```

逻辑：

```text
1. 如果是 None，返回 None
2. 如果是数字，转 float
3. 删除 HK$、港元、逗号、空格
4. 识别 million / billion / 百万 / 十亿
5. 转 float
6. 失败返回 None 或抛出 ParseError
```

## 3.3 `normalize_percent(value)`

职责：

- 将百分比字符串转为 float。

输入：

```python
value: str | float | int | None
```

输出：

```python
float | None
```

示例：

```text
"5%" -> 5.0
"+5.3%" -> 5.3
"-2.1%" -> -2.1
```

## 3.4 `normalize_date(value, timezone="Asia/Hong_Kong")`

职责：

- 将不同格式日期统一为 date。

输入：

```python
value: str | datetime | date | None
timezone: str
```

输出：

```python
date | None
```

逻辑：

```text
1. 如果已经是 date，直接返回
2. 尝试 ISO 格式
3. 尝试 dateparser
4. 尝试中英文手动规则
5. 失败返回 None
```

## 4. Collector 模块

## 4.1 `fetch_url(url, headers=None, timeout=20)`

职责：

- 通用 HTTP GET 请求。

输入：

```python
url: str
headers: dict | None
timeout: int
```

输出：

```python
RawFetchResult
```

逻辑：

```text
1. 使用 httpx.get 请求
2. 设置 User-Agent
3. 检查状态码
4. 返回响应文本、状态码、headers、url、fetched_at
5. 超时或错误时抛出 FetchError
```

## 4.2 `collect_ipo_calendar()`

职责：

- 采集当前 IPO 日历。

输入：

```python
source_name: str
```

输出：

```python
list[IPOItem]
```

逻辑：

```text
1. 根据 source_name 找 collector
2. fetch 原始数据
3. parse 为半结构化 items
4. normalize 为 IPOItem
5. 返回 list
```

## 4.3 `collect_announcements()`

职责：

- 采集 IPO 相关公告。

输入：

```python
lookback_hours: int = 24
```

输出：

```python
list[Announcement]
```

逻辑：

```text
1. 请求公告来源
2. 解析公告列表
3. 按关键词过滤 IPO 相关公告
4. 标准化公告类型
5. 返回 Announcement 列表
```

## 4.4 `collect_grey_market_quotes()`

职责：

- 采集暗盘报价。

输入：

```python
active_ipo_codes: list[str]
```

输出：

```python
list[GreyMarketQuote]
```

逻辑：

```text
1. 查询暗盘来源
2. 解析报价列表
3. 只保留 active_ipo_codes 中的股票
4. 标准化价格和涨跌幅
5. 返回报价
```

## 5. Parser 模块

## 5.1 `parse_ipo_calendar_html(html)`

职责：

- 从 IPO 日历 HTML 中解析新股信息。

输入：

```python
html: str
```

输出：

```python
list[dict]
```

逻辑：

```text
1. BeautifulSoup 解析 HTML
2. 查找 IPO 表格或卡片
3. 提取股票代码、名称、日期、入场费等字段
4. 返回原始 dict 列表
```

## 5.2 `parse_announcement_list(html)`

职责：

- 解析公告列表。

输出字段：

```text
title
url
published_at
stock_code
stock_name
source
raw_type
```

## 5.3 `detect_announcement_type(title, body=None)`

职责：

- 判断公告类型。

输入：

```python
title: str
body: str | None
```

输出：

```python
AnnouncementType
```

逻辑：

```text
1. 标题转小写
2. 匹配 allotment / basis of allocation / 配發結果
3. 匹配 prospectus / 招股章程
4. 匹配 offer price / 發售價
5. 匹配 stabilizing action / 穩定價格
6. 无匹配则返回 other
```

## 5.4 `parse_allotment_result_text(text)`

职责：

- 从配发结果文本中提取字段。

输入：

```python
text: str
```

输出：

```python
AllotmentResult
```

逻辑：

```text
1. 正则提取最终发售价
2. 正则提取公开发售超购倍数
3. 正则提取国际配售认购倍数
4. 正则提取一手中签率
5. 正则提取回拨比例
6. 如果关键字段缺失，标记 parse_confidence = low
7. 返回 AllotmentResult
```

## 6. Repository / 数据访问模块

## 6.1 `upsert_ipo(ipo)`

职责：

- 插入或更新 IPO 基础信息。

输入：

```python
ipo: IPOItem
```

输出：

```python
UpsertResult
```

逻辑：

```text
1. 根据 stock_code 查询数据库
2. 如果不存在，插入并返回 created=True
3. 如果存在，比对字段变化
4. 更新非空字段
5. 记录 changed_fields
6. 返回结果
```

## 6.2 `save_announcement(announcement)`

职责：

- 保存公告并去重。

逻辑：

```text
1. 根据 source + url 查询
2. 如果存在，返回 created=False
3. 如果不存在，插入
4. 返回 announcement_id
```

## 6.3 `save_allotment_result(result)`

职责：

- 保存配发结果。

逻辑：

```text
1. 根据 ipo_code 查询 IPO
2. 更新 IPO 状态为 allotment_result_published
3. 插入 allotment result
4. 添加事件
```

## 6.4 `save_grey_market_quote(quote)`

职责：

- 保存暗盘报价。

逻辑：

```text
1. 插入报价
2. 查询上一条报价
3. 计算变化
4. 返回 quote_id 和变化结果
```

## 6.5 `has_notification_been_sent(key)`

职责：

- 判断某类通知是否已经发送。

输入：

```python
key: str
```

输出：

```python
bool
```

唯一键示例：

```text
03888:allotment_result:announcement_123
```

## 6.6 `record_notification(notification)`

职责：

- 记录推送结果。

字段：

```text
notification_key
ipo_code
type
level
channel
status
sent_at
error_message
```

## 7. Strategy 模块

## 7.1 `load_strategy_config(path)`

职责：

- 加载策略 YAML 并转换为结构化对象。

输出：

```python
StrategyConfig
```

## 7.2 `evaluate_ipo(ipo, allotment=None, grey=None)`

职责：

- 对单只 IPO 进行完整策略评估。

输入：

```python
ipo: IPOItem
allotment: AllotmentResult | None
grey: GreyMarketQuote | None
```

输出：

```python
StrategyDecision
```

逻辑：

```text
1. apply_hard_filters
2. calculate_score
3. collect_matched_rules
4. collect_risk_flags
5. decide_alert_level
6. 返回 StrategyDecision
```

## 7.3 `apply_hard_filters(ipo, config)`

职责：

- 执行硬性过滤。

输出：

```python
FilterResult
```

逻辑：

```text
1. 判断入场费
2. 判断市场板块
3. 判断行业排除
4. 判断保荐人黑名单
5. 判断是否缺少必要字段
```

## 7.4 `calculate_score(ipo, allotment, grey, config)`

职责：

- 计算综合得分。

输出：

```python
int
```

建议分数限制：

```python
score = max(0, min(100, score))
```

## 7.5 `decide_alert_level(score, matched_rules, risk_flags, config)`

职责：

- 根据分数和规则决定提醒等级。

输出：

```python
int
```

## 8. LLM 模块

## 8.1 `build_summary_prompt(payload)`

职责：

- 构造摘要 prompt。

输入：

```python
payload: SummaryPayload
```

输出：

```python
list[dict]
```

即 OpenAI-compatible messages。

逻辑：

```text
1. system prompt 说明角色和限制
2. user prompt 提供结构化数据
3. 要求输出 JSON
4. 明确禁止编造字段和投资承诺
```

## 8.2 `generate_summary(payload)`

职责：

- 调用 LLM 生成摘要。

输入：

```python
payload: SummaryPayload
```

输出：

```python
LLMSummary
```

逻辑：

```text
1. build_summary_prompt
2. 调用 provider
3. 解析 JSON
4. 校验 schema
5. 如果失败，重试一次
6. 仍失败则 fallback_summary
```

## 8.3 `fallback_summary(payload)`

职责：

- LLM 失败时生成模板摘要。

输出：

```python
LLMSummary
```

## 9. Notifier 模块

## 9.1 `format_notification(summary, decision, ipo)`

职责：

- 格式化推送内容。

输出：

```python
str
```

## 9.2 `send_telegram(message)`

职责：

- 发送 Telegram 消息。

输入：

```python
message: str
```

输出：

```python
SendResult
```

逻辑：

```text
1. 从配置读取 bot token 和 chat id
2. 调用 Telegram Bot API
3. 判断响应
4. 返回成功或失败
```

## 9.3 `send_email(subject, body)`

职责：

- 发送邮件。
- 在 Email 正文末尾追加发送当日（香港时间）的 LLM token 累计值。

## 9.4 `send_notification(notification)`

职责：

- 根据配置发送到多个渠道。

逻辑：

```text
1. 检查 notification level
2. 检查是否重复推送
3. 格式化内容
4. 对 Email 渠道追加当日 LLM token 汇总
5. 逐渠道发送
6. 保存发送结果
```

## 10. Scheduler 模块

## 10.1 `job_collect_ipo_calendar()`

职责：

- 定时采集 IPO 日历并触发策略。

逻辑：

```text
1. 遍历启用的数据源
2. collect_ipo_calendar
3. upsert_ipo
4. 如果 created 或 changed，添加事件
5. evaluate_ipo
6. 如果需要推送，send_notification
```

## 10.2 `job_collect_announcements()`

职责：

- 定时采集公告。

逻辑：

```text
1. collect_announcements
2. save_announcement
3. 如果是配发结果，下载正文或 PDF
4. parse_allotment_result_text
5. save_allotment_result
6. evaluate_ipo
7. send_notification
```

## 10.3 `job_collect_grey_market()`

职责：

- 定时采集暗盘。

逻辑：

```text
1. 查询即将上市 IPO
2. collect_grey_market_quotes
3. 保存报价
4. 判断暗盘阈值
5. 推送异动
```

## 10.4 `job_send_daily_digest()`

职责：

- 每日汇总推送。

逻辑：

```text
1. 查询今日事件
2. 查询明日重要事项
3. 构造 digest payload
4. LLM 生成日报
5. 推送
6. 保存日报记录
```

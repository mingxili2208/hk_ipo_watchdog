# codex — Agent Log

## 2026-05-25: 代码审查与修复

### 完成内容

对 cc 的初始实现进行了代码审查和修复，主要改进：

### 1. Collector 重构

**`app/collectors/base.py`**
- `RawFetchResult` 增加 `content: bytes | None` 字段，支持 PDF 等二进制内容的原始保存

**`app/collectors/aastocks_ipo.py` / `app/collectors/hkex_new_listing.py`**
- 统一使用 `parse_ipo_calendar_html` 进行解析，消除各 collector 中的重复解析逻辑
- `collect()` 返回时使用 `model_copy(update={"source_url": ...})` 保留实际请求 URL

**`app/collectors/hkex_news.py`**
- 使用 `urljoin` 处理相对链接，避免 URL 拼接错误
- 新增 `_extract_stock_code()` 从公告上下文中提取股票代码
- 新增 `_fetch_document_text()` 支持 HTML 和 PDF（pypdf）正文提取
- 配发结果公告自动抓取正文用于后续解析

### 2. IPO 日历解析器增强

**`app/parsers/ipo_calendar_parser.py`**
- 重写 `_parse_row`：支持更多中英文字段别名
- 新增 `_lookup()` 支持模糊键名匹配（如 "股份代码" 匹配 "股份代號"）
- 新增 `_parse_price_range()` 解析 "2.50-3.00" 格式价格区间
- 新增 `_parse_int()` 解析含千位分隔符的整数
- 新增 `_infer_status()` 根据日期自动推断 IPO 生命周期状态
- 解析后的 `raw_sources` 保存原始行数据

### 3. Repository 改进

**`app/storage/repository.py`**
- upsert 增加来源优先级机制（`_source_priority`）：HKEX > Futu > AAStocks > mock
- 状态更新只进不退（`_status_rank`），防止低优先级来源回退状态
- `raw_sources` JSON 合并策略，保留多源数据
- `save_announcement` 增量更新已有记录的空字段
- `record_notification` 幂等更新，支持重试场景
- 新增 `has_allotment_for_announcement()` 防止同一公告重复解析配发结果
- `get_active_ipos` 过滤已上市和归档的 IPO

### 4. Strategy Engine 修复

**`app/strategy/rule_engine.py`**
- `_decide_notification_type` 接收 `config` 参数，暗盘阈值从配置读取
- 暗盘下跌超过阈值时自动升级到 level 3（重点提醒）
- `notification_key` 使用 `subscription_start_date` 保证跨扫描稳定性
- 新增 `subscription_deadline` 通知类型，截止认购前一天触发
- 配发结果通知类型不要求 `final_offer_price` 非空

### 5. Scheduler 改进

**`app/scheduler.py`**
- 提取 `_evaluate_and_notify` 方法，消除 `job_collect_ipo_calendar` 中的重复评估逻辑
- `_send_notification` 增加去重前置检查（`has_notification_been_sent`）
- `_collect_all_ipo_sources` 移除 mock fallback，无数据时仅 warning
- `job_collect_announcements` 增加 `has_allotment_for_announcement` 防重复解析
- `job_collect_grey_market` 增加暗盘异动事件记录和通知
- `job_send_daily_digest` 增加去重，同一天只发送一次
- `record_notification` 失败时 `session.rollback()` 防止 session 状态污染

### 6. 测试新增

新增测试文件和用例：
- `tests/test_collectors.py` — collector 解析逻辑测试
- `tests/test_scheduler_flows.py` — 7 个端到端流程测试（去重、多渠道、暗盘异动等）
- `tests/test_strategy_scoring.py` — 新增 `subscription_deadline` 和 `notification_key` 稳定性测试

依赖更新：`requirements.txt` 新增 `pypdf>=4.0.0`

---

## 2026-05-25: 对 CC 数据源修复声明的复核

### Q

用户问题：CC 声称修复后系统各方面均已正常，并将修改记录写入 `docs/agents_log/cc.md`；请对当前实现进行检查，并将包含 Q 和 A 的检查日志记录到本文件。

### A

结论：**CC 的“各方面均正常”结论不成立。** 现有离线测试全部通过，但真实数据源验证显示核心 IPO 日历与公告采集仍不可用，并且已将错误对象写入本地数据库。

### Findings

#### 1. 严重：HKEX 新 URL 不是可申购 IPO 日历，却被作为 `new_ipo` 入库

- 位置：`config/sources.yaml:2-8`、`app/collectors/hkex_new_listing.py:15-43`、`app/scheduler.py:155-193`
- CC 将数据源换成 `Newly-Listed-Securities` 页面。该页面返回的是新上市或发生公司行动的证券列表，并非文档 `FR-001` 要求的招股日历。
- 只读联网验证中，collector 返回 `43` 行；其中 `02958 VISION VALUES` 的原始字段明确为 `corresponding corporate action = Share Consolidation`，仍被转换为 `IPOItem`。
- 现存数据库 `data/hk_ipo_watchdog.db` 已写入 `43` 条 `ipo_items` 和 `43` 条 `new_ipo` 事件；其中包含 `HCG N2905`、`HKGB FRN 2705`、`A HSCEICC` 等票据/债券/ETF 类条目。
- 这会污染历史事件、策略扫描与日报数据，不能视为成功采集 IPO。

#### 2. 严重：HKEX News 新 URL 仅返回搜索页面导航，配发结果链路仍不可达

- 位置：`config/sources.yaml:10-17`、`app/collectors/hkex_news.py:21-134`、`app/scheduler.py:195-228`
- 新地址是高级搜索页面。当前实现只对页面执行 GET 并扫描 `<a>`，没有提交搜索条件，也没有使用 `lookback_hours`。
- 只读联网验证返回 `2` 条对象，标题均为 `上市公司公告`，类型均为 `other`，且 `stock_code=None`、`raw_text=None`；它们是导航链接，不是公告结果。
- 因此 `job_collect_announcements()` 要求的 `allotment_result + stock_code + raw_text` 条件不会由真实 HKEX News 来源触发，配发解析、重评分和推送均无法工作。

#### 3. 高：共享解析器把 `board lot` 误识别为市场板块

- 位置：`app/parsers/ipo_calendar_parser.py:86-110`
- `_lookup(..., ["market", "board", ...])` 使用包含匹配，导致表头 `board lot` 命中 `"board"`。
- 只读联网返回的真实条目出现 `market="100"` / `market="500"`；最小复现中 `Board Lot=500` 也生成 `market="500"`。
- 默认策略仅允许 `Main Board`，因此这些记录会被硬过滤错误拒绝。日志中 CC 扫描的 43 条记录均为 `score=0, passed=False`。

#### 4. 高：当前没有可工作的招股日历来源

- 位置：`app/collectors/aastocks_ipo.py:15-43`、`app/collectors/hkex_new_listing.py:15-43`
- 只读联网验证中 `AAStocksIPOCollector.collect()` 返回 `0` 条；HKEX 来源虽返回 43 条，却均缺少招股开始日、截止日、价格区间和入场费。
- 数据库验证结果为：`status='unknown'` 共 `43` 条，具备 `subscription_close_date` 或 `entry_fee_hkd` 的条目数为 `0`。
- 因此文档要求的招股提醒、截止提醒及基于入场费的策略筛选没有真实输入。

#### 5. 中：部分渠道失败时不会被重试

- 位置：`app/scheduler.py:73-123`、`app/storage/repository.py:200-243`
- 多渠道发送后，只要任一渠道成功，单条通知记录即写为 `status="sent"`；后续调用会因逻辑键已发送而跳过全部渠道。
- 最小复现：Telegram 成功、Email 失败后再次发送，同两个渠道调用次数仍为 `1, 1`，数据库记录为 `('sent', 'telegram,email', 'email: fail')`。
- 这不满足文档中“重试失败推送”的要求。

#### 6. 中：已配置的静默时间未被执行

- 位置：`app/settings.py:55-66`、`app/scheduler.py:73-123`
- `quiet_hours` 可以配置，但 `_send_notification()` 中没有任何静默时间判断。
- 最小复现：设置 `quiet_hours.enabled=true` 且覆盖全天，通知仍发送 `1` 次。
- 这不符合 `docs/03_implementation_logic.md` 中的推送前检查约束。

### Verification

- `python3 -m pytest -q`：`68 passed`。结论是回归测试没有覆盖上述真实数据源语义与通知边界，不代表生产链路正常。
- 只读联网调用 `HKEXNewListingCollector`：返回 `43` 条，包含 `Share Consolidation` 等非 IPO 记录。
- 只读联网调用 `HKEXNewsCollector`：返回 `2` 条导航链接，无可处理公告。
- 只读联网调用 `AAStocksIPOCollector`：返回 `0` 条。
- 查询现存 SQLite 数据：`ipo_items` 为 `43` 条且全部 `status='unknown'`；有效招股字段条目为 `0`；`new_ipo` 事件为 `43` 条。

### Scope

本次工作为复核与记录，未修改业务实现，也未删除已经由此前采集写入的数据库数据。

---

## 2026-05-25: 数据源可读性确认与修复实施

### Q

用户问题：应当如何修复？当前数据源是否正确、是否可读取？

### A

结论：**AAStocks 存在可读取且可提供当前招股核心字段的页面，原配置 URL 错误；CC 换入的两个 HKEX URL 虽可访问，但当前实现不能将它们作为有效的招股日历或公告结果源。** 本轮已修改实现，使系统仅从经过验证的招股入口写入 IPO 数据，并修复已确认的通知闭环问题。

### 数据源核验

| 来源 | 地址 | 可访问 | 是否适合当前实现直接采集 | 处理 |
|---|---|---:|---:|---|
| AAStocks 正在招股 | `https://www.aastocks.com/tc/stocks/market/ipo/mainpage.aspx` | 是 | 是；含代码、名称、招股价、每手、入场费、招股截止日、上市日 | 启用并改为只解析正在招股表 |
| AAStocks 暗盘 | `https://www.aastocks.com/tc/stocks/market/ipo/greymarket.aspx` | 是 | 是；当前无暗盘报价时应返回空列表 | 修正 URL 与按表头解析逻辑 |
| HKEX Newly Listed Securities | `https://www.hkex.com.hk/Services/Trading/Securities/Trading-News/Newly-Listed-Securities?sc_lang=en` | 是 | 否；是新交易/公司行动清单，包含合股、债券和 ETF，并非招股日历 | 禁用 |
| HKEXnews Advanced Search | `https://www1.hkexnews.hk/listedco/listconews/advancedsearch/search_active_main_c.aspx` | 是 | 否；GET 得到查询页导航，不是公告结果列表 | 禁用 |
| HKEX New Listing Information | `https://www2.hkexnews.hk/New-Listings/New-Listing-Information/Main-Board?sc_lang=en` | 是 | 语义正确，但 HTML 页面壳不直接返回公告行，需要另行实现查询流程 | 作为后续官方配发来源候选，未伪启用 |

### 已实施修复

- `config/sources.yaml` 与 `app/settings.py`：默认禁用错误语义的 `hkex_new_listing`、尚未实现结果查询的 `hkex_news`；将 AAStocks IPO/暗盘 URL 改为实际可读取入口。
- `app/collectors/aastocks_ipo.py`：仅解析包含 `招股截止日` 与 `入場費` 的正在招股表，不再把历史上市记录当作新 IPO；该表产生的有效记录标记为 `subscription_open`。
- `app/parsers/ipo_calendar_parser.py`：补充 `招股截止日` 字段别名；清理 AAStocks 名称中拼接的代码与提示文本；阻止 `Board Lot` 被误识别为 `market`。
- `app/collectors/grey_market.py`：按 `暗盤價`/升跌表头解析真实报价并保留发售价、成交额、原始字段；页面显示无当日暗盘或只有日历表时返回空列表；补齐未导入的 `FetchError`。
- `app/scheduler.py` 与 `app/storage/repository.py`：执行静默时段检查；多渠道通知记录已成功渠道，重试时仅补发失败渠道。
- `tests/test_collectors.py` 与 `tests/test_scheduler_flows.py`：新增真实页面结构、市场误判、暗盘表选择、静默时间与部分渠道重试测试。

### Verification

- `python3 -m pytest -q`：`73 passed`。
- 修复后只读实时采集 AAStocks IPO：返回 `1` 条正在招股记录：`03388 創想三維`，状态 `subscription_open`，截止日 `2026-05-26`，入场费 `2848.44`，不再产生错误 `market` 值。
- 修复后只读实时采集 AAStocks 暗盘：在页面显示当日无新股暗盘时返回 `0` 条，不再将暗盘日期表误读为报价。
- 使用独立临时 SQLite 数据库执行一次真实 `job_collect_ipo_calendar()`：仅写入 `03388` 一条 IPO 和对应的一条 `new_ipo` 事件。

### Remaining Boundary

- 官方配发结果采集仍未实现：HKEX New Listing Information 是正确类别的候选来源，但必须实现其查询/结果获取流程后才能重新启用 `hkex_news`。
- 此前错误采集已写入正式数据库的 43 条 HKEX 对象及其事件仍存在。本轮未自动删除既有数据；在继续使用正式库前，应先备份并清理这些由错误来源产生的记录。

---

## 2026-05-25: `new_ipo` 官方来源接入与结论更正

### Q

用户问题：`new` 应该如何获取才合适？是否数据源问题才是当前最大的核心问题？

### A

是。对于 `new_ipo`，最大问题不是策略计算，而是此前将“已新交易/公司行动证券清单”误当成“当前可申购 IPO 发现源”。进一步核验后，应采用以下分工：

1. **权威发现源：HKEXnews New Listing Information - Main Board**
   页面表格公开提供股票代码、名称、`NEW LISTING ANNOUNCEMENTS`、`PROSPECTUSES`、`ALLOTMENT RESULTS` 五列。系统从官方招股公告 PDF 抽取开始日、截止日、上市日、发售价、每手股数和最低入场金额，仅将仍在招股中的记录生成 `new_ipo`。
2. **补充来源：AAStocks IPO 首页**
   可用于补充行业、中文名称等便利字段，并作为交叉校验；它不应覆盖官方字段，也不应单独决定官方事件真实性。
3. **配发结果源：同一 HKEXnews 官方表的 `ALLOTMENT RESULTS` 列**
   系统读取官方配发 PDF，但只为此前已跟踪到的 IPO 建立配发事件，避免首次部署时把历史结果灌入事件流。

### 对上一节结论的更正

上一节曾记载 HKEX New Listing Information “HTML 页面壳不直接返回公告行，需要另行实现查询流程”。进一步以项目 HTTP 客户端读取页面 DOM 后确认该表格和 PDF 链接可直接获取，该判断不准确；本节实现与实时验收已取代该临时结论。

### 已实施修复

- `app/collectors/hkex_new_listing.py`：改为读取官方 New Listing Information 表格的招股公告列，并解析官方 PDF；输出尚未上市的跟踪记录，其中仅 `subscription_open` 触发 `new_ipo`。
- `app/collectors/hkex_news.py`：改为读取同一官方表格的配发结果列并拉取官方 PDF 文本。
- `config/sources.yaml` 与 `app/settings.py`：重新启用 `hkex_new_listing` 和 `hkex_news`，两者 URL 均指向经验证可读的官方页面。
- `app/scheduler.py`：同轮官方记录与 AAStocks 字段补充只生成一条 `new_ipo` 事件；静默建立已截止但尚未上市的记录以承接后续配发；忽略未跟踪且已上市的历史 IPO 配发事件。
- `tests/test_collectors.py`、`tests/test_scheduler_flows.py`：新增官方五列表格、官方招股公告字段、历史配发忽略及同轮多源合并事件测试。

### Verification

- `python3 -m pytest -q`：`78 passed`。
- 只读实时调用官方 `HKEXNewListingCollector`：返回当前开放申购的 `03388 Shenzhen Creality 3D Technology Co., Ltd.`，开始日 `2026-05-20`、截止日 `2026-05-26`、上市日 `2026-05-29`、发售价 `18.8`、每手 `150`、入场费 `2848.44`。
- 只读实时调用官方 `HKEXNewsCollector`：识别到 `06872` 的官方配发结果 PDF。
- 在独立临时 SQLite 数据库执行日历与公告任务：创建 `03388 subscription_open` 与 `03310 subscription_closed` 两条上市前跟踪记录，但仅创建 `03388` 的一条 `new_ipo` 事件；页面已有但不在跟踪集合中的 `06872` 历史配发未写入事件或配发记录。

### Remaining Boundary

- 正式数据库中此前错误 HKEX `Newly Listed Securities` 来源写入的 43 条对象及事件仍需在备份后清理。
- 官方 PDF 每次扫描仍会被重新读取；后续可按公告 URL 增加缓存或已处理文档跳过机制，降低轮询成本。

---

## 2026-05-26: README 更新与 LLM / 推送配置说明

### Q

用户问题：更新 log 和 README；系统是否需要单独配置 LLM 公司的 API key，信息将如何推送给用户？

### A

结论如下：

1. **数据采集和策略评分不要求 LLM API key。** 系统抓取 HKEXnews / AAStocks、写入 SQLite 并运行规则评分不依赖 LLM。
2. **要获得可用于实际提醒的 AI 摘要，需要配置所选 LLM 供应商的 API key。** 当前 `config/llm.yaml` 默认为 `provider: mock`；该模式不需要 key，但返回开发用模拟摘要，不适合作为真实投资信息提醒。
3. **当前默认推送渠道是 Telegram。** `config/notification.yaml` 中 Telegram 已启用，但只有在 `.env` 中提供 `TELEGRAM_BOT_TOKEN` 与 `TELEGRAM_CHAT_ID` 后才会实际发送。
4. **还支持 Email、Bark 与 Server 酱。** 用户可在 `config/notification.yaml` 启用对应渠道，并在 `.env` 配置该渠道所需凭据。
5. **并非发现任意 IPO 就必然推送。** 实时提醒需通过策略阈值（默认 `only_push_score_above: 60`），配发/暗盘事件按规则触发；日报按调度配置发送。静默时段不推送，部分渠道发送失败时只重试失败渠道。

### Documentation Changes

- 更新 `README.md` 的数据来源说明：HKEXnews 官方页面为 `new_ipo` 和配发结果主源，AAStocks 用于字段补充和暗盘行情。
- 新增 `README.md` 的 LLM 配置说明：区分无需 key 的 `mock` 开发模式和需要 key 的真实 AI 摘要模式，并给出 OpenAI / DeepSeek 兼容配置示例。
- 新增 `README.md` 的推送配置说明：列出 Telegram、Email、Bark、Server 酱的环境变量、测试命令、推送内容与策略/静默/重试行为。

### Current Operational Recommendation

- 实际长期运行前，应将 `provider: mock` 切换为已配置 API key 的 OpenAI 兼容模型，否则通知摘要内容仍是模拟数据。
- 若用户希望在不购买或配置 LLM API 的情况下获得真实可用通知，后续应将默认摘要模式改为基于已采集字段和评分结果的规则摘要，而不是 `mock`。

---

## 2026-05-26: GLM-5.1 AI 模式与 Email 推送配置

### Q

用户问题：如何打开 AI 模式，计划配置 GLM-5.1 的 API key；另外如何使用邮件模式推送？

### A

1. **GLM-5.1 可接入现有 LLM provider。** 智谱官方文档列出的模型名为 `glm-5.1`，调用端点为 `https://open.bigmodel.cn/api/paas/v4/chat/completions`，且模型/平台支持 JSON 结构化输出。项目现有 `OpenAICompatibleProvider` 使用 `chat.completions.create()` 与 `response_format={"type": "json_object"}`，因此可通过 `base_url` 指向智谱端点来接入；这是基于官方接口形状与现有实现的兼容性判断，尚需用户提供真实 key 后执行一次在线调用验证。
2. **启用方法。** 将 `config/llm.yaml` 的 `provider` 从 `mock` 改为 `openai`，`model` 改为 `glm-5.1`，`api_key_env` 改为 `ZHIPU_API_KEY`，`base_url` 设置为 `https://open.bigmodel.cn/api/paas/v4/`；并在 `.env` 中填写 `ZHIPU_API_KEY`。
3. **Email 推送已由实现支持。** 在 `config/notification.yaml` 将 `email.enabled` 设为 `true`，配置 SMTP 主机和端口，并在 `.env` 设置 `SMTP_USERNAME`、`SMTP_PASSWORD`、`SMTP_RECEIVER`。默认 Gmail 配置使用 `smtp.gmail.com:587` 与 STARTTLS。
4. **邮件级别。** 默认 `email.min_level: 3`，只推送重点与紧急提醒；将其改为 `2` 可接收观察级提醒。
5. **验证方式。** 配置完成后运行 `python -m app.main test-notification` 测试邮件。填入智谱 key 后，应再触发一次需要摘要的任务验证在线模型请求。

### Documentation Changes

- `README.md` 新增智谱 GLM-5.1 的配置样例与 OpenAI 兼容 provider 含义说明。
- `README.md` 新增邮件推送启用步骤、SMTP 环境变量、提醒级别与测试命令。
- `.env.example` 新增 `ZHIPU_API_KEY` 占位符。

### Sources

- 智谱官方 GLM-5.1 文档：<https://docs.bigmodel.cn/cn/guide/models/text/glm-5.1>
- 智谱官方结构化输出文档：<https://docs.bigmodel.cn/cn/guide/capabilities/struct-output>

---

## 2026-05-26: Email 收件人配置拆分与多地址支持

### Q

用户指出：SMTP 用户名和密码可作为指定的专用发件凭据，但接收方不应固定在环境变量中；应使用单独文档配置 receiver，并支持多个邮箱。

### A

该判断合理，已按“密钥与业务名单分离”的方式实现：

1. `.env` 仅保留 `SMTP_USERNAME` 与 `SMTP_PASSWORD`，用于程序登录专用发件邮箱。
2. 新增 `config/recipients.yaml`，以 `recipients.email` 列表配置一个或多个收件邮箱。
3. `config/notification.yaml` 继续负责 SMTP 主机、端口、启用开关和提醒等级，不再引用 `SMTP_RECEIVER`。
4. `EmailNotifier` 现在接收邮箱列表，并通过同一次 SMTP 发送把邮件交付给列表中的全部地址；可见邮件头不暴露其他接收地址。
5. `test-notification` 和常驻调度发送路径均读取 `config/recipients.yaml`。

### Configuration

```yaml
# config/recipients.yaml
recipients:
  email:
    - "first@example.com"
    - "second@example.com"
```

```bash
# .env
SMTP_USERNAME=dedicated_sender@example.com
SMTP_PASSWORD=your_smtp_app_password
```

### Changes

- 新增 `config/recipients.yaml`。
- 更新 `app/settings.py`，新增 `RecipientsSettings` 并加载收件人文件。
- 更新 `app/notifier/email.py`、`app/scheduler.py`、`app/main.py`，支持多邮箱发送及测试推送。
- 移除 `.env.example` 与 `config/notification.yaml` 中的 `SMTP_RECEIVER` 配置路径。
- 更新 `README.md` 与 `docs/06_user_manual.md` 的 Email 使用说明。
- 新增多收件人邮件发送与调度器配置读取测试。

---

## 2026-05-26: 开源发布的密钥与收件地址保护

### Q

用户希望通过 Git 开源项目，但不希望公开 API key，同时希望他人了解正确配置格式。

### A

采用“公开模板 + 本地私密配置”的结构：

1. `.env` 保存 `ZHIPU_API_KEY`、SMTP 密码等真实凭据，并由 `.gitignore` 排除；`.env.example` 保留空字段格式并可提交。
2. `config/recipients.yaml` 保存实际收件邮箱列表，也由 `.gitignore` 排除；新增 `config/recipients.example.yaml` 作为可公开模板。
3. `config/llm.yaml` 与 `config/notification.yaml` 可提交，但其中只能出现环境变量名称和非敏感端点配置，不应出现实际 key 或密码。
4. 数据库与日志继续不提交，因为它们可能包含个人监控数据或推送正文。
5. 若任何真实密钥已经进入 Git 历史，应立即撤销/轮换密钥；仅添加忽略规则不能消除已经泄露的凭据。

### Changes

- 更新 `.gitignore`，忽略 `.env.*`（保留 `.env.example`）与 `config/recipients.yaml`（保留示例文件）。
- 新增 `config/recipients.example.yaml`。
- 更新 `README.md`，加入模板复制步骤、可提交/不可提交文件说明与发布前检查命令。

---

## 2026-05-26: 当前 `.env` 缺项检查与配置总览补充

### Q

用户问题：当前 `.env` 是否缺少配置？请给出包含 API 和 Email 等内容的配置说明，并更新 README。

### A

本次检查仅判断变量是否存在/为空，没有记录或回显任何密钥值。检查结论：

| 功能 | 当前配置状态 | 当前 `.env` 是否满足 |
|---|---|---|
| LLM | `config/llm.yaml` 当前为 `provider: mock` | 满足开发运行；无需 API key，但不是实际 AI 摘要 |
| GLM-5.1 | 尚未切换为 GLM 配置 | `ZHIPU_API_KEY` 未配置；启用 GLM 前必须填写 |
| Telegram | `config/notification.yaml` 当前为启用 | `TELEGRAM_BOT_TOKEN` 与 `TELEGRAM_CHAT_ID` 均未配置，当前不能实际推送 |
| Email | 当前未启用 | `SMTP_USERNAME` 与 `SMTP_PASSWORD` 未配置；启用前必须填写，且需在 `config/recipients.yaml` 配收件人 |
| Bark / Server 酱 | 当前未启用 | 相应 key 未配置不影响当前运行 |

此外，实际 `.env` 中存在旧键 `SMTP_RECEIVER`。该键已被多收件人设计取代，程序不再读取；真实收件地址应写入本地 `config/recipients.yaml`。

### Documentation Changes

- `README.md` 新增配置总览表，列出 GLM/OpenAI/DeepSeek 与四种通知渠道各自需要的配置位置和环境变量。
- `README.md` 新增推荐 `.env` 格式、废弃 `SMTP_RECEIVER` 说明以及当前默认配置的运行含义。
- 修正 Email `min_level` 说明以匹配当前 `config/notification.yaml`：当前为 `2`，如只需重点/紧急邮件可改为 `3`。

---

## 2026-05-26: SMTP 连接参数与加密方式配置补全

### Q

用户问题：SMTP 配置是否正确，为什么 `.env.example` 不包含 host、port、加密方式等参数？

### A

配置分层本身是正确的：`.env` / `.env.example` 用于敏感凭据格式，SMTP 服务器和端口是非敏感的运行配置，应位于可公开的 `config/notification.yaml`。核查发现 `smtp_host` 与 `smtp_port` 已在该 YAML 文件中，但加密方式此前仅在发送器中隐式固定为 STARTTLS，无法配置，属于实现缺口。

本轮已补齐：

1. `EmailSettings` 新增 `encryption` 配置，支持 `starttls`、`ssl`、`none`。
2. `EmailNotifier` 根据该配置分别使用 SMTP + STARTTLS、`SMTP_SSL` 或不升级 TLS 的 SMTP 连接。
3. `config/notification.yaml` 默认声明 `encryption: "starttls"`，与 Gmail `smtp.gmail.com:587` 组合一致。
4. README 与用户手册明确说明敏感凭据与非敏感连接参数的配置边界，并给出常见端口和连接方式示例。
5. 新增隐式 SSL 与无 TLS 路径的回归测试，并验证调度器传递加密模式。

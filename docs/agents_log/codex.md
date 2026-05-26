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
5. **验证方式。** 配置完成后运行 `python3 -m app.main test-notification` 测试邮件。填入智谱 key 后，应再触发一次需要摘要的任务验证在线模型请求。

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

---

## 2026-05-26: 自动化运行方式与重复调度修复

### Q

用户问题：当前 repository 应如何自动化运行？

### A

系统已有常驻自动运行入口：

- `python3 -m app.main run`：前台启动 APScheduler，适合本地验证或由外部服务管理器托管。
- `docker compose up -d`：后台启动容器；当前 Compose 配置通过 `restart: unless-stopped` 自动恢复服务，并挂载 `config/`、`data/`、`logs/` 与读取 `.env`，适合长期运行。

核查时发现 `config/schedule.yaml` 的 `hkex_announcements` 与 `allotment_results` 原本均启用，而两者在当前实现中都调用 `job_collect_announcements()`，会每 5 分钟重复抓取同一官方页面和 PDF。本轮已关闭独立 `allotment_results` 调度，因为配发结果已由 HKEX 公告任务涵盖。

### Recommended Startup Flow

1. 准备 `.env`、`config/llm.yaml`、`config/notification.yaml` 和本地 `config/recipients.yaml`。
2. 运行 `python3 -m app.main run --dry-run` 验证数据源和入库，不实际发送通知。
3. 启用通知渠道后运行 `python3 -m app.main test-notification`。
4. 使用 `docker compose up -d --build` 启动长期后台服务，并以 `docker compose logs -f` 查看运行日志。

### Changes

- `config/schedule.yaml` 与 `app/settings.py`：将重复的 `allotment_results` 独立任务默认禁用。
- `README.md` 与 `docs/06_user_manual.md`：新增调度周期、上线前验证步骤、Docker 后台托管与当前配置注意事项。
- 新增 `.dockerignore`：排除 `.env`、真实 `config/recipients.yaml`、数据库、日志与缓存，避免 `Dockerfile` 的 `COPY . .` 将本地敏感数据打入镜像。

---

## 2026-05-26: 本地运行误用 Python 2.7 的修复

### Q

用户问题：执行 `python -m app.main test-notification` 时为何报 `SyntaxError`，错误栈显示 `/usr/lib/python2.7/`？

### A

该错误发生在邮件发送之前，与 SMTP 或收件人配置无关。当前宿主机的 `python` 指向 `Python 2.7.18`，而本项目使用函数类型标注等 Python 3 语法，并明确要求 `Python 3.10+`；本机的 `python3` 为 `Python 3.10.12`。

本轮修复：

1. README、用户手册和 CLI 接口示例中的本地命令改为 `python3 -m app.main ...`。
2. 文档新增 Ubuntu 上 `python` 可能仍指向 Python 2.7 的提示。
3. CLI 帮助文本显示的启动命令改为 `python3 -m app.main`。
4. Docker 运行方式保持不变，因为 Dockerfile 使用 `python:3.12-slim` 基础镜像，其中入口命令的 `python` 即为 Python 3。

正确的本地测试邮件命令为：

```bash
python3 -m app.main test-notification
```

该命令会真实向已配置的收件人发送测试邮件。

---

## 2026-05-26: 启用 GLM 与 Email 当前配置

### Q

用户问题：AI 和 Email 模式是否已代为打开；`.env` 中已经添加 key，是否还需要修改？

### A

核查时确认 `.env` 已可读取 `ZHIPU_API_KEY` 与 SMTP 凭据，`config/recipients.yaml` 也已有一个可读取的收件地址，因此无需更改私密环境文件。本轮仅修改非敏感配置：

1. `config/llm.yaml` 从 `mock` 切换到 GLM-5.1，使用 `ZHIPU_API_KEY` 与智谱 OpenAI 兼容端点。
2. `config/notification.yaml` 将 Email 设置为启用。
3. 因当前未配置 Telegram token/chat ID，将 Telegram 设置为关闭，避免无效渠道警告。
4. README 与用户手册同步为当前启用状态说明。

`test-notification` 仅验证推送渠道，不调用 LLM；执行以下命令会实际发送测试邮件：

```bash
python3 -m app.main test-notification
```

---

## 2026-05-26: LLM 多 Profile 选择配置

### Q

用户问题：为什么 `llm.yaml` 不是提供多种配置进行选择，而只有一个 `mock`？

### A

原实现的 `load_settings()` 仅将 `llm:` 下的一组字段加载为单个 `LLMSettings`，因此只能保存当前生效的模型；早期使用 `mock` 是为了在没有 API key 时仍可开发和测试，但不适合作为实际提醒的 AI 摘要。

本轮已将配置改为可选择 profile 的形式：

1. `config/llm.yaml` 现在同时提供 `mock`、`glm`、`openai` 和 `deepseek` 预设，通过 `active_profile: glm` 选择当前模型。
2. `app/settings.py` 新增 profile 解析逻辑；运行时仍只实例化一个所选模型，避免同时调用多家服务。
3. 旧的单一平铺 `llm:` 格式继续兼容读取，已有部署不需要强制迁移。
4. 新增配置加载测试，覆盖 profile 选择、旧格式兼容和不存在的 profile 报错。

当前 `active_profile` 为 `glm`，继续读取用户已经配置的 `ZHIPU_API_KEY`。

---

## 2026-05-26: 邮件垃圾箱判定后的分阶段测试

### Q

用户问题：测试邮件被识别到垃圾邮件后，后续该如何继续测试？

### A

日志已确认 `2026-05-26 15:24:34` 的测试邮件发送结果为 `Email: OK` 与 `Test notification: 1/1 channels succeeded`。这表示 SMTP 登录、发送和收件地址配置均已通过；邮件进入垃圾箱是接收邮箱的分类结果。

本轮补强：

1. 单一收件人发送时，邮件 `To` 头改为实际收件地址；多个收件人时改用 `undisclosed-recipients:;`，继续保护地址列表且避免将发件人错误显示为收件人。
2. 新增 `python3 -m app.main test-llm`，用虚拟数据验证当前 GLM profile 的 API 请求及 JSON 摘要格式，不触发邮件发送。
3. README 与用户手册新增邮件落入垃圾箱时的处理方法和分阶段测试命令。

推荐测试顺序：

1. 在收件邮箱中将已收到的测试邮件标记为非垃圾邮件，并将发件账号加入联系人或允许列表。
2. 运行 `python3 -m app.main test-llm` 单独验证 GLM；该步骤会产生少量 API 用量，但不发送推送。
3. 运行 `python3 -m app.main test-notification` 再次检查邮件分类改善情况。
4. 最后运行 `python3 -m app.main run --dry-run` 验证采集与入库，不发送实际提醒。

---

## 2026-05-26: 真实采集到 Email 的端到端测试

### Q

用户问题：`test-llm` 已经测试过，现在如何测试包含拉取真实数据在内的流程？

### A

现有单项命令无法同时覆盖真实数据拉取、策略评分、LLM 摘要和邮件发送。若直接运行常驻调度，则测试是否发信还取决于实时 IPO 是否达到策略阈值，并可能产生正式通知记录和去重状态。

本轮新增 `python3 -m app.main test-e2e`：

1. 从 `config/sources.yaml` 当前启用的真实 IPO 日历来源拉取数据。
2. 使用临时内存数据库执行与正式 repository 相同的跨来源合并，并对选出的真实 IPO 进行规则评分。
3. 调用当前选定的 LLM profile 生成摘要；若发生 fallback，则测试失败且不发邮件。
4. 以 `[端到端测试]` 标题通过当前 Email 配置实际发送，并在正文注明按当前策略正式运行时是否应推送。
5. 不写入正式业务数据库、通知历史或去重状态，因此不会影响后续常驻自动运行。

该命令需要访问真实数据源、调用一次 LLM API，并发送一封实际测试邮件。

### Initial Run And Fix

首次真实运行成功从 HKEX 拉取 `3` 条可跟踪 IPO，并从 AAStocks 拉取 `1` 条补充数据；命令选择真实 IPO `02553` 进行评分，得到 `score=12`、`would_notify=False`。随后 GLM 返回未满足摘要 JSON schema，命令按设计中止且未发送邮件。

根据智谱官方文档，GLM-5.1 默认开启 Thinking；本次短结构化摘要使用 `max_tokens: 1200` 时，实际观察到一次响应无法解析为 JSON、一次只包含部分所需字段。基于该现象与官方参数说明，本轮作出以下修复：

1. `LLMSettings` 新增可选 `thinking` 配置。
2. `glm` profile 设置 `thinking: disabled`，以适配短 JSON 摘要任务。
3. `OpenAICompatibleProvider` 通过请求体透传智谱 `thinking` 参数，且不会向普通 OpenAI profile 发送该厂商特定参数。
4. schema 失败日志现在只报告字段/类型问题，不输出摘要文本或凭据。

参考文档：

- 智谱 GLM-5.1：<https://docs.bigmodel.cn/cn/guide/models/text/glm-5.1>
- 智谱思考模式：<https://docs.bigmodel.cn/cn/guide/capabilities/thinking-mode>
- 智谱结构化输出：<https://docs.bigmodel.cn/cn/guide/capabilities/struct-output>

### Final Verification

修复后于 `2026-05-26 15:51:26` 重新执行 `python3 -m app.main test-e2e`，结果通过：

- HKEX 官方来源拉取到 `3` 条可跟踪 IPO，AAStocks 拉取到 `1` 条补充记录。
- 临时内存数据库合并后得到 `3` 条 IPO。
- 被选择用于邮件测试的真实记录为 `02553 Beijing Shougang Lanzatech Technology Co., Ltd.`，策略评分为 `12`，按正式阈值不应推送。
- GLM-5.1 在 `thinking: disabled` 下成功返回合规摘要。
- Email 成功发送到配置中的 `1` 个收件地址。

本次测试邮件有 `[端到端测试]` 标记，并未写入正式数据库或通知去重状态。

---

## 2026-05-26: Docker 上线前验收流程

### Q

用户问题：本地真实端到端测试通过后，下一步需要做什么；是否能在 Docker 中进行测试？

### A

可以。核查确认 Dockerfile 使用 Python 3.12，`docker-compose.yml` 在运行时挂载 `./config:/app/config` 并通过 `env_file: .env` 注入凭据；`.dockerignore` 排除 `.env` 和真实 `config/recipients.yaml` 是为防止秘密被写进镜像，不会影响 Compose 运行时读取这些本地配置。

新增的 Docker 验收命令为：

```bash
docker compose run --rm --build hk-ipo-watchdog test-e2e
```

它会使用一次性容器完成真实来源采集、GLM 摘要和 Email 测试发送，完成后删除该测试容器，不启动常驻调度。容器测试通过后，再以 `docker compose up -d --build` 启动长期自动运行。

### Verification

于 `2026-05-26 16:20:26` 执行 Docker 端到端测试，结果成功：

- Docker 镜像基于 Python 3.12 构建完成；构建上下文约 `586 KB`，本地密钥、数据库和日志未复制到镜像。
- 一次性容器成功拉取 HKEX `3` 条可跟踪 IPO 与 AAStocks `1` 条补充记录，合并为 `3` 条 IPO。
- 容器使用 GLM-5.1 为真实记录 `02553` 生成合规摘要。
- 于 `2026-05-26 16:21:15` 成功发送 `[端到端测试]` Email 至 `1` 个配置收件人。

容器运行中同时发现一个非功能性提示问题：由于 `.env` 被刻意排除在镜像外，`load_env()` 曾记录 `.env file not found` 警告，即使 Compose 已通过 `env_file` 注入所需变量。本轮已将该场景调整为信息日志 `No .env file mounted; using injected environment variables`。

修复日志提示后重新构建一次性容器，仅加载配置而不发起网络业务请求；容器确认读取到 `glm-5.1`、已启用的 Email 与 `1` 个收件地址，并以正常信息日志报告环境变量由 Compose 注入。

---

## 2026-05-26: Docker 常驻调度与 GLM Token 用量统计

### Q

用户问题：当前按分钟抓取和每日汇总的行为在 Docker 持续运行时是否一致；GLM token 用量能否统计？

### A

一致。Docker Compose 将宿主机 `config/` 挂载到容器，容器入口仍运行同一套 `python -m app.main run` 调度逻辑。因此当前容器常驻运行时仍是每 10 分钟采集 IPO 日历、每 5 分钟采集 HKEX 公告、每天香港时间 `21:30` 生成日报。需要注意，采集轮询本身不调用 GLM；只有达到提醒条件需要生成摘要，或生成日报时，才会发生 LLM 调用和 token 消耗。

根据智谱对话补全 API 文档，其响应的 `usage` 字段会返回 `prompt_tokens`、`completion_tokens`、`total_tokens` 与缓存 token 明细。因此本轮实现了本地精确统计：

1. `OpenAICompatibleProvider` 读取每次实际响应的 `usage`，包括响应最终未通过摘要 schema 校验但已实际完成的调用。
2. 新增数据库表 `llm_usage`，记录模型、用途、输入/输出/缓存/总 token 数。
3. 常驻正式提醒摘要、日报、`test-llm` 与 `test-e2e` 均会记录用量；`test-e2e` 仍不写入正式 IPO 或通知去重数据，只保存实际产生的 token 成本。
4. 新增查询命令：

```bash
python3 -m app.main usage llm
```

5. Docker 下数据库位于挂载的 `./data` 中，容器重启后统计仍然保留；该功能上线以前已经发生的 API 调用不能回溯补记。
6. 同时修复 `init-db` 首次执行时未主动加载 ORM 元数据的问题，确保包括 `llm_usage` 在内的数据库表可被初始化命令创建。

参考文档：

- 智谱对话补全 API：<https://docs.bigmodel.cn/api-reference/%E6%A8%A1%E5%9E%8B-api/%E5%AF%B9%E8%AF%9D%E8%A1%A5%E5%85%A8>

### Verification

- 执行 `python3 -m pytest -q`：通过，`95 passed`。
- 执行 `python3 -m app.main usage llm`：命令可正常读取正式 SQLite 数据库；新增统计功能启用前无历史用量记录，因此当前显示 `No LLM token usage recorded`。

---

## 2026-05-26: Email 显示今日 GLM Token 用量

### Q

用户问题：能否在 Email 中也打上今日的 token 用量？

### A

已实现。Email 正文末尾现在会追加按香港自然日汇总的 LLM token 段落，显示调用次数、输入 token、输出 token、缓存命中 token 与总 token。实现要点如下：

1. 新增 `Repository.get_llm_usage_for_hk_day()`，按 `Asia/Hong_Kong` 日期边界统计 `llm_usage`，避免 UTC 跨日导致“今日”统计偏差。
2. `SchedulerApp._send_notification()` 仅对 Email 渠道追加汇总，不改变 Telegram、Bark 或 Server 酱的正文长度。
3. `test-notification` 与 `test-e2e` 邮件使用相同 footer；其中 `test-e2e` 会先记录本次摘要的 token，再组装邮件正文，因此邮件内数字包含本次调用。
4. 正式提醒与日报同样在摘要调用已记录后发送，因此邮件显示的是发送瞬间截至当前的今日累计用量。

### Verification

- 执行受影响的 formatter、scheduler 与 command 测试：`24 passed`。
- 执行完整测试集：`98 passed`。

---

## 2026-05-26: Docker 收件人配置重载与发布整理

### Q

用户问题：新增接收邮箱后是否需要重启 Docker；将操作补充到 README、优化文档结构，并提交推送当前修复。

### A

核查确认 `docker-compose.yml` 会将宿主机 `config/` 挂载到容器，因此容器可看到 `config/recipients.yaml` 文件的更新；但程序只在启动阶段通过 `load_settings()` 读取收件人，并且 `SchedulerApp._get_notifiers()` 会缓存已经创建的 `EmailNotifier`。因此常驻容器不会自动使用新增邮箱，修改收件人后必须重启进程。

README 已重新组织为以下使用路径：

1. 安装与配置：解释本地敏感凭据、模型 profile、SMTP 与多收件人文件。
2. 运行与验证：集中列出数据库初始化、推送/LLM/真实端到端测试及 token 查询。
3. 自动运行：集中说明调度周期、前台服务、Docker 托管、容器重建和变更收件人的操作。

README 新增的实际操作区分如下：

```bash
# 仅修改 config/recipients.yaml，容器程序已经是最新版本
docker compose restart hk-ipo-watchdog

# 同时需要应用本地代码更新或新功能，例如本轮 Email token footer
docker compose up -d --build

# 重载后向全部配置收件人发送验证邮件
docker compose exec -T hk-ipo-watchdog python -m app.main test-notification
```

当前核查时，运行中的容器仍是本轮 token 用量统计与 Email footer 加入之前构建的旧镜像：其 `python -m app.main --help` 不包含 `usage` 命令。因此用户若要使用本轮功能，应采用带 `--build` 的命令替换常驻容器。

### Verification

- `config/recipients.yaml` 与 `.env` 均由 `.gitignore` 排除，未进入 Git 跟踪列表。
- 执行 `git diff --check`：无空白格式问题。
- 执行 `python3 -m pytest -q`：通过，`98 passed`。

---

## 2026-05-26: AAStocks 暗盘受控启用与提醒降噪

### Q

用户问题：暗盘行情若启用会带来哪些风险；请按建议优化后再使用。

### A

核查发现，原暗盘配置若直接启用会全天每 1 分钟请求一次 AAStocks 页面；同时旧的 `grey_market_breakout` 通知 key 包含分钟时间戳，行情持续越过阈值时可能每轮生成新的 Email 与 GLM 摘要。这会造成请求强度过高、重复提醒和 token 消耗增加。

AAStocks 暗盘页面当前明确显示交易时段为当日香港时间 `16:15-18:30`。本轮将暗盘调整为受控启用：

1. `config/sources.yaml` 与 `config/schedule.yaml` 启用 AAStocks 暗盘，但自动采集只在香港时间工作日 `16:15-18:30` 进入请求逻辑，间隔由每 1 分钟降低为每 5 分钟。
2. 暗盘窗口外直接跳过；即便处于窗口内，数据库没有已跟踪活跃 IPO 时也不请求来源。存在候选且完整运行一个窗口时，单一 AAStocks 暗盘来源最多约请求 28 次。
3. `config/strategy.yaml` 新增 `re_alert_step_percent: 5`。第一次达到上涨 `+5%` 或下跌 `-3%` 阈值时允许提醒；同一股票同一日维持在同一方向/同一阶梯内不重复发信；继续同方向变化至少 5 个百分点后才允许发送新一档提醒。
4. 手动 `collect grey-market` 命令绕过自动时间窗口，便于已有活跃 IPO 时排查页面读取和解析，但不会绕过“无活跃 IPO 不请求”的保护。
5. 暗盘报价时间改为香港时区记录，使跨日期提醒阶梯与本地交易日一致。

AAStocks 页面与其页面内披露说明均表明暗盘数据仅供参考，且未经授权不得复制、出售或转载。本系统仅将其作为个人监控线索，推送内容不构成交易建议，也不应作为公开分发行情的数据源。

参考：

- AAStocks 新股暗盘页面：<https://www.aastocks.com/tc/stocks/market/ipo/greymarket.aspx>
- AAStocks 条款及免责声明：<https://www.aastocks.com/aastocks/quote/quote.asp?lang=chi&live=1&symbol=>

### Verification

- 新增窗口外不请求、无活跃 IPO 不请求、同阶梯不重复提醒及显著恶化后重发的回归测试。
- 执行 `python3 -m pytest -q`：通过，`102 passed`。

---

## 2026-05-26: 暗盘运行核查后关闭，动态读取待独立分支处理

### Q

用户问题：容器真实运行日志是否存在错误；先关闭暗盘并记录该问题，后续通过新 branch 处理；同时确认日报邮件与数据留存状态。

### A

真实日志核查发现暗盘能力尚不可用：

1. `2026-05-26 18:23:40` 出现一次 AAStocks 暗盘页请求超时，系统已捕获错误且容器未崩溃。
2. 更关键的是 `logs/app.log` 在暗盘窗口内持续记录 `Grey market: failed to parse row: stock code must be str, got <class 'NoneType'>`。浏览页面 HTML 后确认，AAStocks 暗盘页包含诸如 `00901.PH` / `00901.FU` 的品种占位区域，但 `last`、`pctchange` 等实时报价值由 JavaScript 动态行情通道填充；当前静态 HTML 表格解析器无法获得真实报价。因此日志中的 `0 quotes` 是读取失败表现，不能解释为没有行情。
3. 已将 `config/sources.yaml` 与 `config/schedule.yaml` 的 `grey_market.enabled` 设为 `false`，并在 README、用户手册和逻辑/接口文档中注明该限制。现有交易窗口限制与提醒去重代码保留，供后续动态行情适配分支复用。

后续分支的完成条件应至少包括：选定可合法稳定读取的动态行情方式、以真实暗盘窗口响应验证字段解析、保留请求频率限制和阶梯去重，并在部署前确认不会重复触发 Email/LLM。

日报邮件核查结果：

1. 重启容器加载关闭配置后，运行时调度任务仅含 `collect_ipo_calendar`、`collect_announcements` 与 `daily_digest`，不再含 `collect_grey_market`。
2. `daily_digest` 运行时触发器为 `cron[hour='21', minute='30']`，时区配置为 `Asia/Hong_Kong`。
3. 容器运行时读取到 Email 已启用、SMTP 用户名与密码均已注入、6 个收件人已加载、静默时段关闭；GLM-5.1 所需 key 同样已注入。由此，今晚 21:30 已具备尝试生成并发送日报的配置条件。未为了核查提前发送额外测试邮件。

数据留存核查结果：

1. Docker 将 `data/` 与 `logs/` 映射到宿主机；当前 `data/hk_ipo_watchdog.db` 已存在，包含 IPO、事件、策略评分等结构化记录，`logs/app.log` 含运行及 DEBUG 解析轨迹。
2. `config/sources.yaml` 虽包含 `save_raw` 字段，但当前采集器没有实现原始 HTTP 响应写入；核查时 `data/raw/` 为空。因此历史页面不能从 raw 文件回放，只能查看已入库的结构化数据和日志。

---

## 2026-05-26: 日报补充已入库 IPO 详情

### Q

用户问题：日报已经识别到 `02553`、`03388` 与 `03310`，为什么最终邮件提供的 IPO 信息很少？

### A

根因不是数据库没有数据，而是日报载荷过于精简。核查数据库发现：

1. `02553` 已保存招股期 `2026-05-26` 至 `2026-05-29`、上市日 `2026-06-03`、发售价 `HKD 17.10`、每手 `200` 股及入场费 `HKD 3,454.49`。
2. `03388` 已保存招股期、上市日、发售价 `HKD 18.80`、每手 `150` 股、入场费 `HKD 2,848.44` 和行业。
3. `03310` 已保存招股期、发售价 `HKD 20.81`、每手 `200` 股和入场费 `HKD 4,203.98`；其上市日与行业当前确实未入库。

原实现的 `get_today_events()` 只向日报传入事件标题和 `changed_fields`，`format_daily_digest()` 也只打印事件标题，导致 GLM 看不到数据库已经保存的招股字段，甚至把 `new_ipo` 描述成“递交 IPO 申请”。

本轮修复：

1. `Repository.get_today_events()` 现在按香港自然日边界查询事件，并为对应事件附带当前 IPO 快照；配发与暗盘事件也会附带可用的最新结构化数据。
2. 日报提示词明确要求使用已提供字段，覆盖招股日期、上市日期、发售价、每手股数、入场费和行业，并禁止把 `new_ipo` 改写成递交申请。
3. Email 日报事件区固定打印上述已入库字段，因此即使 LLM 生成的概述较短，关键招股信息也不会消失。

当天原日报已于 `2026-05-26 21:30:14` 成功发送并按日去重，修复后的格式从下一次日报发送起生效。

---

## 2026-05-26: 日报展示策略评分与评分依据

### Q

用户问题：日报中没有出现每只股票的评分和评分依据，希望邮件也展示这些内容。

### A

核查确认策略评分一直有写入数据库，但此前没有进入日报载荷或 Email 格式化输出。2026-05-26 最新已存评分示例为：`02553=12`、`03388=21`、`03310=12`。这些分数偏低并非执行失败，而是当前只有低入场费、以及 `03388` 的行业字段可产生基础分；尚无配发结果，并且暗盘来源已关闭，因此认购热度、配发结构和暗盘表现部分均为 `0` 分。

本轮修复：

1. 新增可读的 `score_breakdown`，与计算使用的各评分组件对应，能够显示基础信息、认购热度、配发结构、暗盘表现、保荐人和风险扣分的贡献或缺失原因。
2. 日报生成前按当时最新入库数据重新计算事件涉及股票的评分并保存，但不触发额外的单股提醒；这样日报显示的不是旧缓存分数。
3. 日报 Email 为每只事件股票固定展示 `评分 / 等级 / 普通推送线`、`评分依据` 与风险标记；日报 prompt 同样携带这些规则输出，要求 GLM 不得自行改写分数。

当天日报已经按日去重成功发送，本次增强从下一次日报起显示。

---

## 2026-05-26: 日报增加跨日上市倒计时跟踪

### Q

用户问题：如果在 D 日发现 IPO 股票 `ABC`，则在 D+1 日报中应说明距离该股票 IPO/上市还剩多少天，并提示详细信息位于哪一天的日报。

### A

已将该需求实现为后续日报的“持续跟踪”段：

1. 系统以首次 `new_ipo` 事件为发现依据；从次日起，只要该股票已有有效 `listing_date` 且尚未 `listed` / `archived`，就继续列入日报跟踪。
2. 距离天数以香港自然日计算至上市日。例如在 `2026-05-27` 日报中，上市日为 `2026-06-03` 的 `02553` 会显示“距离上市还有 7 天”。
3. 若首次发现日的日报通知已有成功投递记录，跟踪行会显示“详细招股信息见 YYYY-MM-DD 日报”；若未确认成功投递，则仅标注首次发现日，不错误声称详情日报已经送达。
4. 缺少上市日期的早期无效/不完整条目不会进入持续跟踪，从而避免历史数据污染日报。

### Verification

- 新增次日倒计时及详情日报引用测试。
- 新增缺少上市日期时不进入跟踪段的测试。

---

## 2026-05-26: 日报补充主营业务短摘要

### Q

用户问题：日报预览仍缺少 IPO 公司的主要营运内容；业务描述只需摘要级别，不应过于复杂。

### A

核查确认 `NEW LISTING ANNOUNCEMENTS` 发售公告主要提供发售安排，不能稳定得到主营业务描述；同一 HKEXnews 官方新上市页面的 `PROSPECTUSES` 招股章程 PDF 含有 `OVERVIEW` 业务概览。本轮因此没有让 GLM 根据公司名称猜测业务，而是新增官方章程来源链路：

1. 官方新上市采集器同时保存 `prospectus_url`，并从章程 `OVERVIEW` 抽取主营业务摘要。
2. 数据模型及 SQLite `ipo_items` 新增 `business_overview` 字段；既有 SQLite 库会在启动时非破坏性补列。
3. 为控制邮件长度及来源请求强度，摘要只保留 `OVERVIEW` 首句、最长 320 字符；仅在该 IPO 尚无摘要时下载章程一次，已经存储的摘要后续轮询直接复用。
4. 单股邮件、日报今日事件与跨日“持续跟踪”段均显示 `主营业务 (官方章程摘要)`；日报 GLM 可将提供的官方英文短摘简明归纳为中文，但禁止新增原文没有的业务判断。
5. 补摘要、补章程链接属于数据完善，不生成误导性的“核心招股信息更新”事件。

实际补录结果：

1. `02553` 已识别为 CCUS / 低碳产品及解决方案相关业务。
2. `03388` 已识别为面向消费者的 3D 打印产品和服务提供商。
3. `03310` 已识别为智能手机 AMOLED DDIC 供应商。

### Verification

- HKEX 官方章程已用于真实补录，`02553`、`03388` 与 `03310` 的 `business_overview` 均写入 `data/hk_ipo_watchdog.db`。
- 将最初的两句摘要规则收窄为首句后，容器采集日志仅出现三条本地 `IPO business overview shortened`，没有重新下载章程进行补录。
- 次日日报预览已显示 `02553` 与 `03388` 的主营业务短摘要、上市倒计时及首次详情日报引用。
- `python3 -m pytest -q`：`110 passed`；`git diff --check` 通过。

---

## 2026-05-26: 支持当日日报显式补发

### Q

用户问题：今天的日报已在主营业务摘要完善之前发送，如何对今天的邮件进行一次补发？

### A

原有 `python3 -m app.main digest daily` 使用 `digest:daily_digest:YYYY-MM-DD` 按日去重；由于 `2026-05-26` 日报已在 `21:30:14` 成功投递，重复执行会直接跳过。本轮增加显式补发入口：

```bash
python3 -m app.main digest daily --resend
```

补发行为如下：

1. 不删除、不覆盖原始日报成功投递记录，保留原日报作为首次详情日报引用依据。
2. 重新读取当日事件及数据库最新 IPO 快照，因此可带上刚补录的主营业务摘要和评分依据。
3. 标题增加 `[补发]`，正文注明这是该日的更新补发版本。
4. 补发使用独立的通知键 `digest:daily_digest:YYYY-MM-DD:resend:<时间戳>` 保存，便于审计；每次显式执行都会实际再发一封邮件。

### Verification

- 新增测试覆盖：普通日报仍每日只发一次，`--resend` 可新增一次投递且不替换原记录。
- `python3 -m pytest -q`：`111 passed`；`git diff --check` 通过。

# 06. 使用手册：HK IPO Watchdog

## 1. 系统简介

HK IPO Watchdog 是一个个人使用的港股打新监控系统。

它可以：

1. 自动抓取港股 IPO 信息；
2. 自动跟踪招股、截止、配发结果、暗盘、上市等节点；
3. 根据你配置的策略筛选新股；
4. 使用 AI 生成摘要；
5. 通过 Telegram / 邮件等渠道推送；
6. 保存历史数据用于回看和复盘。

系统不会自动交易，也不提供确定性投资建议。

## 2. 环境要求

推荐环境：

```text
Ubuntu 22.04+
Python 3.10+
Docker / Docker Compose
```

如果本地运行：

```bash
python3 --version
# Python 3.10 or above
```

本手册中的本地运行命令均使用 `python3`；若系统中的 `python` 指向 Python 2.7，则不能用于启动本项目。

## 3. 安装方式

## 3.1 克隆项目

```bash
git clone <your-repo-url>
cd hk-ipo-watchdog
```

## 3.2 创建 Python 环境

```bash
python3 -m venv .venv
source .venv/bin/activate
```

## 3.3 安装依赖

```bash
pip install -r requirements.txt
```

建议依赖：

```text
httpx
beautifulsoup4
lxml
pydantic
pyyaml
python-dotenv
sqlalchemy
apscheduler
loguru
dateparser
pypdf
pdfplumber
openai
```

如果使用 Playwright：

```bash
pip install playwright
playwright install
```

## 4. 配置文件

## 4.1 创建 `.env`

复制模板：

```bash
cp .env.example .env
```

编辑：

```env
OPENAI_API_KEY=your_openai_api_key
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_chat_id

SMTP_USERNAME=
SMTP_PASSWORD=

DEEPSEEK_API_KEY=
BARK_DEVICE_KEY=
SERVER_CHAN_SEND_KEY=
```

如果只用 Telegram，只需要配置：

```env
OPENAI_API_KEY=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

## 4.2 配置数据源

文件：

```bash
config/sources.yaml
```

示例：

```yaml
sources:
  hkex_new_listing:
    enabled: true
    interval_minutes: 10
    save_raw: true

  hkex_news:
    enabled: true
    interval_minutes: 5
    lookback_hours: 24

  aastocks_ipo:
    enabled: true
    interval_minutes: 15

  grey_market:
    enabled: false
    interval_minutes: 1
```

MVP 阶段建议：

```yaml
hkex_new_listing: enabled
hkex_news: enabled
aastocks_ipo: enabled
grey_market: disabled
```

## 4.3 配置策略

文件：

```bash
config/strategy.yaml
```

示例：

```yaml
basic:
  max_entry_fee_hkd: 20000
  allowed_markets:
    - Main Board
  exclude:
    industries:
      - property
      - traditional retail

subscription:
  min_public_subscription_times: 10
  min_one_lot_success_rate: 5

grey_market:
  min_grey_gain_percent: 5
  alert_if_below_percent: -3

alerts:
  watch_score_above: 60
  important_score_above: 75
  urgent_score_above: 85
  only_push_score_above: 60
```

含义：

| 配置 | 说明 |
|---|---|
| `max_entry_fee_hkd` | 最大一手入场费 |
| `min_public_subscription_times` | 最低公开发售超购倍数 |
| `min_one_lot_success_rate` | 最低一手中签率 |
| `min_grey_gain_percent` | 暗盘上涨提醒阈值 |
| `alert_if_below_percent` | 暗盘下跌风险提醒 |
| `only_push_score_above` | 低于该分数不推送 |

## 4.4 配置 LLM

文件：

```bash
config/llm.yaml
```

该文件提供可选 profile；每次运行仅使用 `active_profile` 指定的一项。当前选择 `glm`，通过智谱 OpenAI 兼容端点调用 GLM-5.1：

```yaml
llm:
  active_profile: glm
  temperature: 0.2
  max_tokens: 1200
  timeout_seconds: 30
  retry_times: 1
  profiles:
    mock:
      provider: mock
    glm:
      provider: openai
      model: glm-5.1
      api_key_env: ZHIPU_API_KEY
      base_url: "https://open.bigmodel.cn/api/paas/v4/"
      thinking: disabled
    openai:
      provider: openai
      model: gpt-4.1-mini
      api_key_env: OPENAI_API_KEY
      base_url: null
    deepseek:
      provider: openai
      model: deepseek-chat
      api_key_env: DEEPSEEK_API_KEY
      base_url: "https://api.deepseek.com"
```

将 `active_profile` 改为 `mock`、`glm`、`openai` 或 `deepseek` 即可切换；除 `mock` 外，需在本地 `.env` 提供所选服务的 API key。GLM-5.1 默认开启 Thinking；本系统的提醒摘要要求严格短 JSON，因此 `glm` profile 使用 `thinking: disabled` 以避免生成结果被推理内容挤占或截断。旧的单一模型配置格式仍可继续读取。

## 4.5 配置推送

文件：

```bash
config/notification.yaml
```

Telegram 示例：

```yaml
notification:
  telegram:
    enabled: true
    bot_token_env: TELEGRAM_BOT_TOKEN
    chat_id_env: TELEGRAM_CHAT_ID
    min_level: 2

  email:
    enabled: false

  bark:
    enabled: false

  server_chan:
    enabled: false
```

Email 发件账号的 `SMTP_USERNAME` 与 `SMTP_PASSWORD` 属于凭据，配置在 `.env`。
Email 收件人另行配置在 `config/recipients.yaml`，可维护多个地址：

```yaml
recipients:
  email:
    - "first@example.com"
    - "second@example.com"
```

SMTP 服务器、端口与加密方式配置在 `config/notification.yaml`，而不是 `.env`：

```yaml
notification:
  email:
    enabled: true
    smtp_host: "smtp.gmail.com"
    smtp_port: 587
    encryption: "starttls"  # 可选: starttls / ssl / none
    username_env: SMTP_USERNAME
    password_env: SMTP_PASSWORD
    min_level: 2
```

`starttls` 通常配合端口 `587`，`ssl` 通常配合端口 `465`；`none` 仅适用于明确可信的内部 SMTP 服务。

当前仓库已启用 Email，并关闭没有配置凭据的 Telegram。执行 `python3 -m app.main test-notification` 会实际向 `config/recipients.yaml` 中的邮箱发送测试邮件。

若测试日志显示 `Email: OK` 但邮件被识别为垃圾邮件，代表 SMTP 已完成发送，而不是配置失败。请在收件邮箱中标记该邮件为非垃圾邮件，并将发件账号加入联系人或允许列表。单收件人发送时程序会显示实际收件地址作为邮件 `To` 头；多收件人发送仍隐藏地址列表。

## 5. 运行方式

## 5.1 初始化数据库

```bash
python3 -m app.main init-db
```

## 5.2 测试数据源

```bash
python3 -m app.main collect ipo-calendar --once
```

## 5.3 测试推送

```bash
python3 -m app.main test-notification
```

成功后，当前已启用的 Email 收件地址应收到测试邮件；如另行启用 Telegram，则对应会收到测试消息。Email 正文末尾包含截至发送时的香港当日 LLM token 累计用量。

## 5.4 测试 LLM

```bash
python3 -m app.main test-llm
```

该命令使用虚拟数据调用当前选择的 LLM profile，并校验返回的摘要 JSON 格式。它不会发送邮件或其他通知，但真实 LLM 会产生少量 API 用量，并将供应商响应返回的 token 用量记录到数据库。

## 5.5 真实端到端测试

```bash
python3 -m app.main test-e2e
```

该命令从已启用的真实 IPO 日历来源拉取当前数据，在临时内存数据库中执行同样的来源合并和策略评分，然后使用当前 LLM 生成摘要并发送一封标题带 `[端到端测试]` 的邮件。该测试会产生一次 API 用量和一次邮件发送；只将 token 用量写入正式数据库的 `llm_usage` 表，不写入正式 IPO 或通知去重记录。若选择的 IPO 按规则不应正式推送，正文也会明确显示这一点。

## 5.6 查看 LLM Token 用量

```bash
python3 -m app.main usage llm
```

该命令汇总此功能启用后由 GLM/其他 OpenAI 兼容 profile 返回的实际 `prompt_tokens`、`completion_tokens`、`cached_tokens` 和 `total_tokens`。被统计的场景包括 LLM 测试、真实端到端测试、正式提醒摘要和日报；普通轮询未触发摘要时不会产生 LLM token。Email 的正式提醒、日报及测试邮件也会在正文末尾附上发送当日（香港时间）的汇总；邮件摘要本身产生的 token 会先记录、再随同邮件显示。历史调用无法追溯补记。

## 5.7 启动常驻服务

```bash
python3 -m app.main run
```

该命令在前台启动定时调度。`config/schedule.yaml` 默认每 10 分钟采集 IPO 日历、每 5 分钟采集 HKEX 公告（其中已包含配发结果），每天香港时间 21:30 生成日报。`allotment_results` 独立任务默认关闭，避免与公告采集重复请求同一来源。

## 5.8 Docker 运行

在启动常驻容器前，建议先以一次性容器验证与宿主机相同的端到端链路：

```bash
docker compose run --rm --build hk-ipo-watchdog test-e2e
```

Compose 会将本机 `config/` 与 `data/` 挂载到容器并读取 `.env` 作为环境变量；`.dockerignore` 排除密钥与真实收件人文件只影响镜像构建内容，不影响运行时挂载。该命令结束后删除测试容器，不会启动长期调度，但会调用一次 LLM、发送一封测试邮件，并将 token 用量保留在挂载的数据文件中。

端到端测试通过后，启动长期服务：

```bash
docker compose up -d
```

Docker Compose 使用 `restart: unless-stopped` 持续托管服务，并挂载 `config/`、`data/`、`logs/`，同时从 `.env` 注入本地凭据。项目的 `.dockerignore` 会排除 `.env`、实际收件人配置、数据库和日志，防止这些本地内容被复制进 Docker 镜像。需要在后台长期运行时，优先使用该方式。

查看日志：

```bash
docker compose logs -f
```

停止：

```bash
docker compose down
```

## 6. 常用命令

## 6.1 手动采集 IPO 日历

```bash
python3 -m app.main collect ipo-calendar
```

## 6.2 手动采集公告

```bash
python3 -m app.main collect announcements
```

## 6.3 手动采集暗盘

```bash
python3 -m app.main collect grey-market
```

## 6.4 手动跑策略扫描

```bash
python3 -m app.main strategy scan
```

## 6.5 手动发送日报

```bash
python3 -m app.main digest daily
```

## 6.6 Dry Run

只运行，不发送推送：

```bash
python3 -m app.main run --dry-run
```

## 6.7 测试 LLM

```bash
python3 -m app.main test-llm
```

## 6.8 真实数据端到端测试

```bash
python3 -m app.main test-e2e
```

## 6.9 Docker 端到端测试

```bash
docker compose run --rm --build hk-ipo-watchdog test-e2e
```

## 6.10 LLM Token 用量汇总

```bash
python3 -m app.main usage llm
```

## 7. 推送内容说明

典型推送格式：

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
- 暗盘数据尚未公布
- 估值信息需要进一步确认

说明：本提醒仅用于信息整理，不构成投资建议。
```

## 8. 如何调整策略

## 8.1 更激进

适合希望多收到提醒：

```yaml
alerts:
  only_push_score_above: 50
  watch_score_above: 50
  important_score_above: 70
  urgent_score_above: 80
```

## 8.2 更保守

适合只关注高热度新股：

```yaml
alerts:
  only_push_score_above: 75
  watch_score_above: 70
  important_score_above: 82
  urgent_score_above: 90

subscription:
  min_public_subscription_times: 30
```

## 8.3 低入场费优先

```yaml
basic:
  max_entry_fee_hkd: 5000

scoring:
  basic_weight: 40
  subscription_weight: 20
  grey_market_weight: 20
```

## 8.4 暗盘优先

```yaml
grey_market:
  min_grey_gain_percent: 5
  alert_if_below_percent: -3

alerts:
  urgent_score_above: 80
```

## 9. 日志和排错

## 9.1 查看日志

本地：

```bash
tail -f logs/app.log
```

Docker：

```bash
docker compose logs -f
```

## 9.2 常见问题

### 问题 1：没有收到 Telegram 推送

检查：

1. `TELEGRAM_BOT_TOKEN` 是否正确；
2. `TELEGRAM_CHAT_ID` 是否正确；
3. 是否已经给 bot 发送过消息；
4. `notification.yaml` 中 Telegram 是否启用；
5. 当前提醒等级是否低于 `min_level`。

### 问题 2：LLM 摘要失败

检查：

1. API Key 是否正确；
2. `llm.yaml` 中模型名是否正确；
3. base_url 是否正确；
4. 网络是否可访问；
5. 是否触发 API 限额。

系统应自动 fallback 为模板摘要。

### 问题 3：采集失败

可能原因：

1. 数据源页面结构变更；
2. 请求被限流；
3. 网络超时；
4. URL 配置错误；
5. 需要 Playwright 渲染。

处理方式：

```bash
python3 -m app.main collect ipo-calendar --log-level DEBUG
```

查看 raw data：

```bash
ls data/raw/
```

### 问题 4：重复推送

检查：

1. `notifications` 表是否存在重复 key；
2. `notification_key` 是否构造正确；
3. 是否不同数据源生成了不同 event_key；
4. 是否数据库被清空。

## 10. 数据备份

SQLite 默认路径：

```text
data/hk_ipo_watchdog.db
```

建议每日备份：

```bash
cp data/hk_ipo_watchdog.db backups/hk_ipo_watchdog_$(date +%F).db
```

Docker 可以将 `data/` 挂载为 volume。

## 11. 升级建议

MVP 完成后建议按顺序扩展：

1. 增加暗盘数据源；
2. 增加配发结果 PDF 精准解析；
3. 增加 Web Dashboard；
4. 增加策略回测；
5. SQLite 升级 PostgreSQL；
6. 增加多模型 fallback；
7. 增加每日 / 每周收益复盘。

## 12. 使用注意

1. 本系统不构成投资建议；
2. 打新存在破发风险；
3. 暗盘数据来源不同，价格可能不同；
4. 公告解析可能失败，应保留官方链接；
5. 策略规则需要定期根据市场情况调整；
6. 不建议使用系统进行自动下单。

# HK IPO Watchdog

港股打新监控系统 - 自动抓取、策略筛选、摘要生成、多渠道推送。

## 功能

- 从 HKEXnews 官方新上市信息页发现 IPO，并解析官方招股公告 / 配发结果 PDF
- 通过 AAStocks 补充 IPO 字段并采集暗盘数据
- 根据用户配置的策略自动筛选和打分
- 可调用 OpenAI 兼容 LLM 生成中文摘要（例如 OpenAI / DeepSeek）
- 通过 Telegram / Email / Bark / Server 酱推送
- SQLite 存储历史数据，支持回看和复盘
- Docker Compose 一键部署

## 环境要求

- Python 3.10+
- Docker / Docker Compose（可选）

## 快速开始

### 1. 安装依赖

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. 配置

```bash
cp .env.example .env
cp config/recipients.example.yaml config/recipients.yaml
# 编辑 .env，至少填入所选择推送渠道需要的凭据
```

主要配置文件在 `config/` 目录下：

- `sources.yaml` — 数据源配置
- `strategy.yaml` — 策略规则配置
- `llm.yaml` — LLM 模型配置
- `notification.yaml` — 推送渠道配置
- `recipients.example.yaml` — 可公开的邮件收件人示例；复制为本地 `recipients.yaml` 后填写真实地址
- `schedule.yaml` — 定时任务配置

## 配置总览

`.env` 仅保存敏感凭据；是否启用功能、模型地址、SMTP 服务器、端口、加密方式、推送等级和收件人列表由 `config/` 中的 YAML 文件控制。

| 功能 | 启用位置 | `.env` 必填项 | 其他配置 |
|---|---|---|---|
| GLM-5.1 AI 摘要 | `config/llm.yaml` 中设置 `provider: openai` 与 `model: glm-5.1` | `ZHIPU_API_KEY` | 设置智谱 `base_url` |
| OpenAI AI 摘要 | `config/llm.yaml` 中设置对应模型 | `OPENAI_API_KEY` | `base_url: null` |
| DeepSeek AI 摘要 | `config/llm.yaml` 中设置对应模型 | `DEEPSEEK_API_KEY` | 设置 DeepSeek `base_url` |
| Telegram 推送 | `config/notification.yaml` 中 `telegram.enabled: true` | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | 设置 `min_level` |
| Email 推送 | `config/notification.yaml` 中 `email.enabled: true` | `SMTP_USERNAME`, `SMTP_PASSWORD` | 收件地址写入 `config/recipients.yaml` |
| Bark 推送 | `config/notification.yaml` 中 `bark.enabled: true` | `BARK_DEVICE_KEY` | 设置 `min_level` |
| Server 酱推送 | `config/notification.yaml` 中 `server_chan.enabled: true` | `SERVER_CHAN_SEND_KEY` | 设置 `min_level` |

推荐的本地 `.env` 格式：

```bash
# 只填写你实际启用的 LLM 服务商 key
OPENAI_API_KEY=
DEEPSEEK_API_KEY=
ZHIPU_API_KEY=

# 只填写你实际启用的推送渠道凭据
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
SMTP_USERNAME=
SMTP_PASSWORD=
BARK_DEVICE_KEY=
SERVER_CHAN_SEND_KEY=
```

`SMTP_RECEIVER` 已废弃，不再由程序读取；邮件收件人应配置在 `config/recipients.yaml`。

### 当前默认配置的含义

- `config/llm.yaml` 默认 `provider: mock`：不要求任何 LLM key，但摘要是开发用模拟内容。
- `config/notification.yaml` 当前启用 Telegram：如未设置 `TELEGRAM_BOT_TOKEN` 与 `TELEGRAM_CHAT_ID`，不会产生实际 Telegram 推送。
- Email、Bark、Server 酱默认未启用：未启用时对应 `.env` 变量可以为空。
- 若准备使用 GLM-5.1，需要同时修改 `config/llm.yaml` 并填写 `ZHIPU_API_KEY`，仅填写 key 不会自动切换模型。

## 数据来源

当前实现使用以下数据源分工：

| 用途 | 来源 | 说明 |
|---|---|---|
| 新 IPO 发现及基础字段 | HKEXnews New Listing Information - Main Board | 官方主源；解析 `NEW LISTING ANNOUNCEMENTS` PDF，仅当前招股中的 IPO 生成 `new_ipo` 事件 |
| 配发结果 | HKEXnews New Listing Information - Main Board | 官方主源；解析 `ALLOTMENT RESULTS` PDF，仅处理已跟踪 IPO |
| IPO 信息补充 | AAStocks IPO 首页 | 补充行业等字段，不覆盖官方字段 |
| 暗盘行情 | AAStocks 暗盘页 | `config/sources.yaml` 默认关闭，按需要启用 |

官方来源地址：

- <https://www2.hkexnews.hk/New-Listings/New-Listing-Information/Main-Board?sc_lang=en>
- <https://www.aastocks.com/tc/stocks/market/ipo/mainpage.aspx>
- <https://www.aastocks.com/tc/stocks/market/ipo/greymarket.aspx>

## LLM 配置

采集、存储和策略评分本身不依赖 LLM API key。

当前 `config/llm.yaml` 默认配置为：

```yaml
llm:
  provider: mock
```

`mock` 只适用于开发和测试：不需要 API key，但生成的是模拟摘要，不应作为真实提醒内容使用。

实际运行若需要 AI 生成的中文摘要，请切换到 OpenAI 兼容接口，并在 `.env` 中配置相应 key，例如：

```yaml
# config/llm.yaml: OpenAI 示例
llm:
  provider: openai
  model: gpt-4.1-mini
  api_key_env: OPENAI_API_KEY
  base_url: null
```

```bash
# .env
OPENAI_API_KEY=your_api_key
```

DeepSeek 等 OpenAI 兼容接口可通过 `base_url`、`model` 和 `api_key_env` 配置：

```yaml
llm:
  provider: openai
  model: deepseek-chat
  api_key_env: DEEPSEEK_API_KEY
  base_url: "https://api.deepseek.com"
```

### 使用智谱 GLM-5.1

智谱官方文档中的模型标识是 `glm-5.1`，Chat Completions 接口为
`https://open.bigmodel.cn/api/paas/v4/chat/completions`。本项目使用 OpenAI 兼容客户端，因此配置 `base_url` 到 `/v4/` 即可由客户端拼接 `chat/completions`：

```yaml
# config/llm.yaml
llm:
  provider: openai
  model: glm-5.1
  api_key_env: ZHIPU_API_KEY
  base_url: "https://open.bigmodel.cn/api/paas/v4/"
  temperature: 0.2
  max_tokens: 1200
  timeout_seconds: 30
  retry_times: 1
```

```bash
# .env
ZHIPU_API_KEY=your_zhipu_api_key
```

其中 `provider: openai` 表示使用项目现有的 OpenAI 兼容调用器，并不表示请求发往 OpenAI；实际请求将按 `base_url` 发往智谱 API。未提供真实 key 时无法完成在线调用验证。

若已选择真实 LLM provider 但未设置对应环境变量，程序启动该功能时会报缺少 API key。

## 推送配置

系统在策略评分达到推送阈值，或产生符合规则的配发/暗盘事件时发送提醒；每日汇总按 `config/schedule.yaml` 的时间发送。默认策略低于 `only_push_score_above: 60` 不会发送实时提醒。

当前 `config/notification.yaml` 默认启用 Telegram，需在 `.env` 配置：

```bash
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

收到的消息包含股票代码和名称、当前状态、入场费、截止认购日期、上市日期、评分、触发原因、风险提示和摘要。

可选推送渠道及所需环境变量：

| 渠道 | 配置开关 | 所需环境变量 |
|---|---|---|
| Telegram | `notification.telegram.enabled` | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |
| Email | `notification.email.enabled` | `SMTP_USERNAME`, `SMTP_PASSWORD`；收件人配置在 `config/recipients.yaml` |
| Bark | `notification.bark.enabled` | `BARK_DEVICE_KEY` |
| Server 酱 | `notification.server_chan.enabled` | `SERVER_CHAN_SEND_KEY` |

配置好渠道后执行：

```bash
python -m app.main test-notification
```

启用 `quiet_hours` 时静默时间内不发送；多渠道中的失败渠道会在后续触发时单独重试，不重复发送已成功渠道。

### 使用邮件推送

邮件配置被拆成两类：

- `.env`：保存发件邮箱账号与 SMTP 密码，它们属于专用凭据。
- `config/recipients.yaml`：保存收件人列表，它属于可变的业务配置，可配置多个邮箱。

`.env.example` 不包含 `smtp_host`、`smtp_port` 或加密方式，是因为 `.env` 只用于发件账号和密码等秘密信息；这些非敏感连接参数应提交在 `config/notification.yaml` 中，方便其他使用者查看和修改。

默认邮件发送器使用 Gmail SMTP 和 STARTTLS。如使用 Gmail，先在 `config/notification.yaml` 启用邮件：

```yaml
notification:
  email:
    enabled: true
    smtp_host: "smtp.gmail.com"
    smtp_port: 587
    encryption: "starttls"
    username_env: SMTP_USERNAME
    password_env: SMTP_PASSWORD
    min_level: 3
```

填写发件账号凭据：

```bash
# .env
SMTP_USERNAME=your_sender@gmail.com
SMTP_PASSWORD=your_smtp_app_password
```

`SMTP_PASSWORD` 应填写邮箱供应商允许 SMTP 登录使用的密码或应用专用密码，而不是在不允许基础认证时强行使用网页登录密码。使用其他邮箱供应商时，将 `smtp_host`、`smtp_port` 和凭据改为该供应商提供的 SMTP 参数。

支持的加密模式：

| `encryption` | 连接方式 | 常见端口 | 适用场景 |
|---|---|---:|---|
| `starttls` | 先建立 SMTP 连接，再升级为 TLS | `587` | Gmail 等常见默认方式 |
| `ssl` | 建连即使用 TLS（SMTPS） | `465` | 提供隐式 TLS 的邮箱服务商 |
| `none` | 不启用 TLS | `25` | 仅限可信内部邮件服务器，不建议用于公网 |

例如，若你的邮箱供应商要求 SMTPS：

```yaml
notification:
  email:
    enabled: true
    smtp_host: "smtp.example.com"
    smtp_port: 465
    encryption: "ssl"
```

从公开示例生成本地收件人文件，然后配置一个或多个接收邮箱：

```bash
cp config/recipients.example.yaml config/recipients.yaml
```

```yaml
# config/recipients.yaml
recipients:
  email:
    - "your_receiver@example.com"
    - "second_receiver@example.com"
```

修改收件人列表不需要变更发件账号密码；每次发送邮件时，所有列表中的地址都会收到同一条提醒。邮件正文头不会公开其他接收地址。

邮件通过 `min_level` 控制接收等级。当前仓库配置为 `min_level: 2`，会接收观察、重点及紧急提醒；若只希望邮件接收重点及紧急提醒，可调整为：

```yaml
notification:
  email:
    min_level: 3
```

启用后执行 `python -m app.main test-notification`，系统会向 `config/recipients.yaml` 中配置的所有邮箱发送一封测试邮件。常驻运行时，满足级别和策略阈值的提醒及已启用的日报会通过邮件发送。

## 开源发布与密钥保护

可以公开的文件：

- `.env.example`：仅保留变量名称和空值。
- `config/recipients.example.yaml`：仅保留示例邮箱。
- `config/llm.yaml`、`config/notification.yaml`：只应保存模型名、端点和环境变量名称，不写入真实 key 或密码。

只在本机保留、不要提交的文件：

- `.env`：包含 `ZHIPU_API_KEY`、`SMTP_PASSWORD` 等真实凭据。
- `config/recipients.yaml`：包含你的实际收件邮箱列表。
- `data/*.db` 与 `logs/`：可能含运行数据或通知内容。

本仓库的 `.gitignore` 已忽略以上本地文件。首次发布前，仍应确认待提交清单中没有真实密钥或邮箱：

```bash
git status --short
git diff --cached --name-only
git grep -n -E '(API_KEY|TOKEN|PASSWORD|SEND_KEY)=' -- ':!.env.example'
```

应提交的初始化文件为：

```text
.env.example
config/recipients.example.yaml
```

如果真实 key 曾经被提交到 Git 历史或推送到远端，仅删除文件不够；应立即在服务商后台撤销并重新生成 key，然后再清理 Git 历史。

如果在加入忽略规则之前仅误将本地配置加入暂存/跟踪、但还没有泄露到公开历史，可停止跟踪并保留本地文件：

```bash
git rm --cached .env config/recipients.yaml
```

### 3. 初始化数据库

```bash
python -m app.main init-db
```

### 4. 测试推送

```bash
python -m app.main test-notification
```

### 5. 手动采集

```bash
# 采集 IPO 日历
python -m app.main collect ipo-calendar --once

# 采集公告
python -m app.main collect announcements --once
```

### 6. 策略扫描

```bash
python -m app.main strategy scan
```

### 7. 发送日报

```bash
python -m app.main digest daily
```

### 8. 启动常驻服务

```bash
python -m app.main run
```

### 9. Docker 部署

```bash
docker compose up -d
```

查看日志：

```bash
docker compose logs -f
```

停止：

```bash
docker compose down
```

## 命令一览

```bash
python -m app.main init-db          # 初始化数据库
python -m app.main run              # 启动常驻调度服务
python -m app.main run --dry-run    # 只运行不推送
python -m app.main collect ipo-calendar --once   # 采集 IPO 日历
python -m app.main collect announcements --once   # 采集公告
python -m app.main collect grey-market --once     # 采集暗盘
python -m app.main strategy scan    # 策略扫描
python -m app.main digest daily     # 发送日报
python -m app.main test-notification # 测试推送
```

通用参数：

- `--config-dir` — 配置目录路径（默认 `config/`）
- `--log-level` — 日志级别（默认 `INFO`）
- `--dry-run` — 只运行不推送
- `--once` — 只运行一次

## 策略配置

编辑 `config/strategy.yaml` 调整策略：

```yaml
basic:
  max_entry_fee_hkd: 20000    # 最大入场费
  allowed_markets:
    - Main Board
  exclude_industries:
    - property

alerts:
  watch_score_above: 60       # 观察提醒阈值
  important_score_above: 75   # 重点提醒阈值
  urgent_score_above: 85      # 紧急提醒阈值
  only_push_score_above: 60   # 低于此分数不推送
```

## 项目结构

```text
app/
├── main.py              # CLI 入口
├── scheduler.py         # 定时任务
├── settings.py          # 配置加载
├── models.py            # Pydantic 数据模型
├── exceptions.py        # 自定义异常
├── collectors/          # 数据采集器
├── parsers/             # 解析器和标准化
├── strategy/            # 策略引擎
├── llm/                 # LLM 摘要
├── notifier/            # 推送通知
├── storage/             # 数据库和存储
└── utils/               # 工具函数
```

## 运行测试

```bash
pytest
```

## 数据备份

SQLite 数据库位于 `data/hk_ipo_watchdog.db`，建议定期备份：

```bash
cp data/hk_ipo_watchdog.db backups/hk_ipo_watchdog_$(date +%F).db
```

## 注意事项

- 本系统不构成投资建议
- `provider: mock` 为开发模式，实际提醒应配置真实 LLM 或后续改为规则摘要模式
- 打新存在破发风险
- 暗盘数据来源不同，价格可能不同
- 策略规则需要定期根据市场情况调整
- 不建议使用系统进行自动下单

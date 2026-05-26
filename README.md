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

## 安装与配置

### 安装依赖

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

后续本地运行命令统一使用 `python3`。在部分 Ubuntu 环境中，系统命令 `python` 仍可能指向不支持本项目语法的 Python 2.7。

### 创建本地配置

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
| GLM-5.1 AI 摘要 | `config/llm.yaml` 中设置 `active_profile: glm` | `ZHIPU_API_KEY` | 已提供智谱端点预设 |
| OpenAI AI 摘要 | `config/llm.yaml` 中设置 `active_profile: openai` | `OPENAI_API_KEY` | 已提供 OpenAI 预设 |
| DeepSeek AI 摘要 | `config/llm.yaml` 中设置 `active_profile: deepseek` | `DEEPSEEK_API_KEY` | 已提供 DeepSeek 端点预设 |
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

### 当前配置的含义

- `config/llm.yaml` 当前配置为 GLM-5.1，通过智谱兼容接口生成真实摘要；运行时需要 `.env` 中提供 `ZHIPU_API_KEY`。
- `config/notification.yaml` 当前启用 Email，并关闭未配置凭据的 Telegram；Email 运行时需要 SMTP 凭据与本地 `config/recipients.yaml` 中至少一个收件地址。
- Bark、Server 酱当前未启用：未启用时对应 `.env` 变量可以为空。

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

`config/llm.yaml` 保存多个可选预设，但每次运行只启用 `active_profile` 指定的一项。当前已选择 `glm`：

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

切换模型时只需修改 `active_profile` 并在 `.env` 填写所选 profile 对应的 key。`mock` 不需要 API key，但生成的是开发用模拟摘要，不应作为真实提醒内容使用。为兼容旧部署，单一平铺格式的 `llm:` 配置仍可读取。

### 使用智谱 GLM-5.1

智谱官方文档中的模型标识是 `glm-5.1`，Chat Completions 接口为
`https://open.bigmodel.cn/api/paas/v4/chat/completions`。本项目使用 OpenAI 兼容客户端，因此 `glm` profile 中的 `/v4/` 基础地址会由客户端拼接 `chat/completions`：

```yaml
llm:
  active_profile: glm
```

```bash
# .env
ZHIPU_API_KEY=your_zhipu_api_key
```

`glm` profile 内部的 `provider: openai` 表示使用项目现有的 OpenAI 兼容调用器，并不表示请求发往 OpenAI；实际请求将按其 `base_url` 发往智谱 API。GLM-5.1 默认会开启 Thinking，而提醒摘要要求短且严格的 JSON 输出，因此此 profile 显式设置 `thinking: disabled`，减少推理过程占用输出预算导致的结构化结果截断。未提供真实 key 时无法完成在线调用验证。

若已选择真实 LLM provider 但未设置对应环境变量，程序启动该功能时会报缺少 API key。

## 推送配置

系统在策略评分达到推送阈值，或产生符合规则的配发/暗盘事件时发送提醒；每日汇总按 `config/schedule.yaml` 的时间发送。默认策略低于 `only_push_score_above: 60` 不会发送实时提醒。

若希望另行启用 Telegram，需先在 `.env` 配置：

```bash
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

收到的消息包含股票代码和名称、当前状态、入场费、截止认购日期、上市日期、评分、触发原因、风险提示和摘要。Email 正文末尾还会显示发送时截至当前的香港自然日 LLM token 累计用量。

可选推送渠道及所需环境变量：

| 渠道 | 配置开关 | 所需环境变量 |
|---|---|---|
| Telegram | `notification.telegram.enabled` | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |
| Email | `notification.email.enabled` | `SMTP_USERNAME`, `SMTP_PASSWORD`；收件人配置在 `config/recipients.yaml` |
| Bark | `notification.bark.enabled` | `BARK_DEVICE_KEY` |
| Server 酱 | `notification.server_chan.enabled` | `SERVER_CHAN_SEND_KEY` |

配置好渠道后执行：

```bash
python3 -m app.main test-notification
```

若日志显示 `Email: OK` 而邮件进入垃圾箱，说明 SMTP 投递已成功，收件服务进行了分类。请在邮箱中将测试邮件标记为“非垃圾邮件”，并将发件账号加入联系人或白名单；程序无法保证第三方邮箱一定将邮件放入收件箱。

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

单收件人邮件的 `To` 头会显示该收件地址；多收件人邮件使用隐藏收件人头并通过 SMTP 投递列表发送，从而不向各接收方公开邮箱列表。

邮件通过 `min_level` 控制接收等级。当前仓库配置为 `min_level: 2`，会接收观察、重点及紧急提醒；若只希望邮件接收重点及紧急提醒，可调整为：

```yaml
notification:
  email:
    min_level: 3
```

启用后执行 `python3 -m app.main test-notification`，系统会向 `config/recipients.yaml` 中配置的所有邮箱发送一封测试邮件。常驻运行时，满足级别和策略阈值的提醒及已启用的日报会通过邮件发送。

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

## 运行与验证

### 初始化数据库

```bash
python3 -m app.main init-db
```

### 分项测试

```bash
python3 -m app.main test-notification
```

日志为 `Email: OK` 即表示邮件服务发送成功；首次邮件如落入垃圾箱，请先在邮箱端标记为非垃圾邮件，再进行后续通知测试。

测试 GLM API 和返回摘要格式时执行：

```bash
python3 -m app.main test-llm
```

该命令会调用当前选定的 LLM profile，可能产生少量 API 用量，但仅使用虚拟数据且不会发送任何推送。供应商返回的 token 用量会记录在本地数据库中。

### 真实端到端测试

在 LLM 和 Email 分别测试通过后，执行：

```bash
python3 -m app.main test-e2e
```

该命令会从当前启用的真实 IPO 日历来源采集数据，在临时内存数据库中执行合并与规则评分，调用当前 LLM 生成真实数据摘要，并发送一封标题含 `[端到端测试]` 的 Email。它会产生一次 LLM API 用量及一封实际邮件；只将本次 token 用量写入正式数据库的 `llm_usage` 表，不写入正式 IPO、通知记录或去重状态。即使当前真实 IPO 尚未达到正式推送阈值，测试邮件仍会发送，并在正文中注明按规则是否应正式推送。

### 查看 LLM Token 用量

智谱对话补全接口在响应中返回实际 token 使用量。系统会从现在开始记录由 `test-llm`、`test-e2e`、正式提醒摘要及每日汇总产生的调用：

```bash
python3 -m app.main usage llm
```

输出按模型和调用用途汇总 `prompt_tokens`、`completion_tokens`、`cached_tokens` 与 `total_tokens`。Email 通知和测试邮件正文也会附上发送当日（香港时间）的累计值；若该封邮件先调用 LLM 生成摘要，当次用量已包含在正文统计中。该统计不能补记功能启用之前已经发生的调用。

### 手动操作

```bash
# 采集 IPO 日历
python3 -m app.main collect ipo-calendar --once

# 采集公告
python3 -m app.main collect announcements --once
```

```bash
# 扫描数据库中已有的 IPO 并重新评分
python3 -m app.main strategy scan

# 立即生成并发送当日日报
python3 -m app.main digest daily
```

## 自动运行

### 调度频率

默认任务配置见 `config/schedule.yaml`：

| 任务 | 默认频率 | 说明 |
|---|---:|---|
| IPO 日历 | 每 10 分钟 | 读取 HKEX 官方招股公告并用 AAStocks 补字段 |
| HKEX 公告 / 配发结果 | 每 5 分钟 | 同一个任务读取官方配发 PDF；无需另起配发轮询 |
| 暗盘 | 默认关闭 | 启用后默认每 1 分钟采集 |
| 日报 | 每天 `21:30` | 时区为 `Asia/Hong_Kong` |

### 前台运行

```bash
python3 -m app.main run
```

该命令会在当前终端前台持续运行 APScheduler；关闭终端会停止监控。长期使用推荐 Docker Compose，或自行将同一命令托管为系统服务。

### Docker 自动运行（推荐）

上线前先完成本地私密配置：

```bash
cp .env.example .env
cp config/recipients.example.yaml config/recipients.yaml
# 编辑 .env、config/llm.yaml、config/notification.yaml、config/recipients.yaml
```

首次启动前建议依次验证：

```bash
# 不发送通知，只验证真实 IPO 数据采集和数据库写入
python3 -m app.main run --dry-run

# 调用所选 LLM 生成虚拟摘要，不发送通知
python3 -m app.main test-llm

# 若已启用 Telegram / Email 等渠道，发送测试通知
python3 -m app.main test-notification

# 从真实来源采集 IPO，经 LLM 生成摘要，并发送标记为测试的邮件
python3 -m app.main test-e2e
```

在宿主机验证通过后，使用一次性容器复核 Docker 中的完整链路：

```bash
docker compose run --rm --build hk-ipo-watchdog test-e2e
```

该命令构建当前镜像，使用 Compose 的 `.env` 与 `config/` 挂载运行真实端到端测试，完成后自动删除测试容器，不会启动常驻调度服务。它同样会调用一次 LLM 并发送一封 `[端到端测试]` 邮件，token 用量通过挂载的 `./data` 保留在宿主机数据库中。

启动后台服务：

```bash
docker compose up -d
```

`docker-compose.yml` 已配置：

- 容器内默认运行 `python -m app.main run`；其基础镜像为 Python 3.12，因此不受宿主机 `python` 指向 Python 2.7 的影响；
- `restart: unless-stopped`，进程或机器重启后由 Docker 恢复服务；
- 将本机 `./config`、`./data`、`./logs` 挂载到容器；
- 从本机 `.env` 注入 API key 与推送凭据。
- `.dockerignore` 排除本机 `.env`、真实收件人配置、数据库和日志，避免密钥或本地数据在构建时被复制进镜像。
- `llm_usage` 存在挂载的 `./data` 数据库中，容器重启后仍可使用 `python3 -m app.main usage llm` 或对应的一次性容器命令查看。

查看日志：

```bash
docker compose logs -f
```

停止：

```bash
docker compose down
```

更新代码或配置后重建并启动：

```bash
docker compose up -d --build
```

### 新增或修改 Email 收件人

编辑本地文件 `config/recipients.yaml`，在列表中添加一个或多个地址：

```yaml
recipients:
  email:
    - "first_receiver@example.com"
    - "second_receiver@example.com"
```

`config/` 虽然以 volume 方式挂载到容器，但常驻程序在启动时读取收件人列表，并缓存已创建的邮件发送器。因此修改收件人后需要重启服务：

```bash
# 仅修改 recipients.yaml，且容器已是最新程序版本
docker compose restart hk-ipo-watchdog

# 同时需要应用代码更新或新功能
docker compose up -d --build
```

重启后发送一封测试邮件，确认列表中的每个邮箱均能收到邮件：

```bash
docker compose exec -T hk-ipo-watchdog python -m app.main test-notification
```

该测试会真实向所有已配置收件人发送邮件。新增收件地址不会进入 Git：实际 `config/recipients.yaml` 已由 `.gitignore` 排除，仅公开示例文件会提交。

### 上线前检查

当前仓库配置的实际含义：

- LLM 已设置为 GLM-5.1；必须通过本地 `.env` 提供 `ZHIPU_API_KEY` 才能生成真实 AI 摘要。
- Telegram 当前关闭；仅在提供 `TELEGRAM_BOT_TOKEN` 与 `TELEGRAM_CHAT_ID` 后再启用。
- Email 当前启用；必须同时提供 SMTP 凭据和至少一个 `config/recipients.yaml` 收件地址。
- 正式库如仍保留早期错误数据源产生的记录，应在长期运行前备份并清理。

## 命令一览

```bash
python3 -m app.main init-db          # 初始化数据库
python3 -m app.main run              # 启动常驻调度服务
python3 -m app.main run --dry-run    # 只运行不推送
python3 -m app.main collect ipo-calendar --once   # 采集 IPO 日历
python3 -m app.main collect announcements --once   # 采集公告
python3 -m app.main collect grey-market --once     # 采集暗盘
python3 -m app.main strategy scan    # 策略扫描
python3 -m app.main digest daily     # 发送日报
python3 -m app.main test-llm          # 测试 LLM，不发送推送
python3 -m app.main test-notification # 测试推送
python3 -m app.main test-e2e          # 拉取真实数据并发送端到端测试邮件
python3 -m app.main usage llm         # 汇总已记录的 LLM token 用量
docker compose run --rm --build hk-ipo-watchdog test-e2e # 在一次性容器中验证完整链路
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
- 当前配置使用 GLM-5.1；若未提供有效 `ZHIPU_API_KEY`，真实摘要生成将失败
- 打新存在破发风险
- 暗盘数据来源不同，价格可能不同
- 策略规则需要定期根据市场情况调整
- 不建议使用系统进行自动下单

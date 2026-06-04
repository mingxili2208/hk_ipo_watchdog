# 会话工作记录：暗盘功能 & LLM 评估体系

## 1. 暗盘信息功能实现

### 问题
AAStocks 暗盘页面（`greymarket.aspx`）的数据通过 **WebSocket 动态推送**，静态 HTTP GET 请求只能拿到 `N/A` 占位符和"供應商是日沒有新股暗盤"提示。

### 方案
使用 **Playwright 无头浏览器**渲染页面，等 WebSocket 数据到达后提取 DOM 内容。

### 实现内容

| 文件 | 操作 |
|---|---|
| `app/utils/browser.py` | **新建** — Playwright 浏览器单例管理器，独立 context 隔离，finally 块自动关闭 |
| `app/collectors/grey_market.py` | **重写** — 新增 `collect_mode`（html/browser）、`_fetch_with_browser()`、跳过"无数据"提示表 |
| `app/scheduler.py` | 传递 `collect_mode` + 退出时 `close_singleton()` |
| `app/settings.py` | `SourceConfig` 新增 `collect_mode` 字段 |
| `config/sources.yaml` | `grey_market.enabled: true`, `collect_mode: browser` |
| `config/schedule.yaml` | `grey_market.enabled: true` |
| `Dockerfile` | 安装 Chromium 系统依赖 + `playwright install chromium` |
| `requirements.txt` | 新增 `playwright>=1.40.0` |
| `tests/test_browser.py` | **新建** — 7 个 BrowserManager 测试 |
| `tests/test_collectors.py` | 扩展 — 5 个暗盘采集测试 |
| `scripts/monitor_memory.py` | **新建** — 进程/容器内存监控工具 |

### 资源安全保障
- 单例 Chromium 实例，每次 `fetch_page()` 独立 context + finally 自动关闭
- 调度器退出时 `close_singleton()` 释放浏览器
- 所有操作有超时保护
- Docker 镜像增加 `--no-sandbox`、`--single-process`、`--disable-dev-shm-usage`

### 真实测试结果
- Playwright 成功渲染 AAStocks 页面（191KB）
- 当天无暗盘时正确返回空列表
- "供應商是日沒有新股暗盤"提示表被正确跳过
- 浏览器关闭日志正常输出

---

## 2. 评分体系重构

### 问题2026-06-03 日报的更新补发版本。
旧评分 = 各维度直接累加，缺失维度 = 0 分。招股初期满分仅 40，永远无法达到推送阈值 60。而且 55% 的权重（认购热度、中签结构、暗盘）在用户做申购决策时都拿不到数据。

### 讨论过程
1. 提出"可用维度归一化"方案 → 用户认为是"玩数字游戏"
2. 讨论了三个替代方案 → 用户认为更重要的是评价维度和指标的拓展
3. 重新设计为**两阶段架构**：申购推荐评分（招股期间）+ 事后复盘评分（配发后/暗盘期）

### 实现内容

| 文件 | 操作 |
|---|---|
| `app/models.py` | 新增 `LLMEvaluation`、`ProspectusFinancials`、`SponsorStats`、`MarketHeat` 模型 |
| `app/llm/prompts.py` | 新增 `EVALUATION_SYSTEM_PROMPT`、`FINANCIAL_EXTRACTION_PROMPT`、`build_evaluation_prompt`、`build_financial_extraction_prompt`、`build_enriched_evaluation_prompt` |
| `app/llm/schemas.py` | 新增 `evaluation_validation_errors`、`financial_validation_errors` 校验 |
| `app/llm/client.py` | 新增 `evaluate_ipo()`、`extract_financials()`、`evaluate_ipo_enriched()` 方法 |
| `app/llm/providers/mock_provider.py` | 根据 prompt 类型返回对应格式的 mock 数据（评估/财务/摘要） |
| `app/strategy/scoring.py` | 新增 `calculate_llm_score()`、`calculate_composite_score()`，综合分 = 规则分 × 0.4 + LLM 分 × 0.6 |
| `app/strategy/config_loader.py` | `ScoringConfig` 新增 `llm_weight: float = 0.6` |
| `config/strategy.yaml` | 新增 `llm_weight: 0.6` |
| `app/storage/models.py` | 新增 `LLMEvaluationORM` |
| `app/storage/repository.py` | 新增 `save_llm_evaluation()`、`get_latest_llm_evaluation()`、`get_sponsor_stats()`、`get_market_heat()` |
| `app/scheduler.py` | `_evaluate_and_notify()` 集成 LLM 评估流程 |

### 评分链路
```
IPO 发现
  ↓
_evaluate_and_notify()
  ├─ _extract_prospectus_financials()  → LLM 从招股书提取收入/利润/增速
  ├─ _get_sponsor_stats()             → 保荐人历史评分统计
  ├─ _get_market_heat()               → 近 30 天 IPO 市场热度
  ↓
evaluate_ipo_enriched(ipo, financials, sponsor_stats, market_heat)
  → LLM 输出结构化评估（4 维评分 + 事实理由）
  ↓
calculate_llm_score(evaluation) → LLM 分（0-100，置信度收缩）
calculate_composite_score(rule_score, llm_score) → 综合分
  ↓
format_notification(..., llm_eval) → 邮件含评估依据
```

---

## 3. 邮件评估依据优化

### 问题
第一版邮件中的评估依据是模板化定性描述（"商业模式清晰，竞争壁垒高"），没有信息量。

### 改动
LLM 评估输出新增 4 个 `_reason` 字段，prompt 中要求写**具体事实陈述**而非定性概括。

| 文件 | 操作 |
|---|---|
| `app/models.py` | `LLMEvaluation` 新增 `business_quality_reason` 等 4 个字段 |
| `app/llm/prompts.py` | prompt 中明确要求写事实（"公司是国内第二大SaaS供应商，客户续约率92%"） |
| `app/llm/schemas.py` | 校验 `_reason` 字段类型 |
| `app/llm/providers/mock_provider.py` | mock 输出带具体数字的 reason |
| `app/notifier/formatter.py` | 删除旧的 `_score_reason` 模板函数，直接展示 LLM 输出的事实 |
| `app/notifier/formatter.py` | `format_daily_digest` 新增 LLM 评估依据展示 |

### 效果对比

**改前：**
```
商业模式: 8/10 — 商业模式清晰，竞争壁垒高，客户粘性强
```

**改后：**
```
商业模式: 8/10 — 公司是国内第二大企业SaaS供应商，客户续约率92%，拥有12项核心专利
```

---

## 4. 测试修复

### 问题
`test_daily_digest_events_include_stored_ipo_snapshot` 和 `test_daily_digest_attaches_current_strategy_score_without_alert_send` 两个测试持续失败。

### 根因
`add_event` 内部用 ORM 的 `_now()` 设置 `created_at`（真实时间），但 `get_today_events` 查询的是 `today_hk()` 的 mock 日期。事件的 `created_at` 是 6月3日（真实时间），查询条件是 5月26日（mock 日期），查不到。

### 修复
在测试里手动把事件的 `created_at` 改为 mock 日期，并用 `repo.session.get()` 替代已废弃的 `query.get()`。

### 结果
**136 passed, 0 failed**

---

## 5. 已知问题与待办

### 已知问题
1. **LLM 评估只触发一次** — `_evaluate_and_notify` 里只在没有缓存时才调 LLM，评估结果不会随数据更新而刷新
2. **日报只展示今日有事件的 IPO** — 没有事件的活跃 IPO 不会出现在日报中
3. **GLM 内容过滤** — 部分招股书内容触发智谱的内容安全过滤（`error code 1301`），回退到 fallback 评估
4. **LLM 评估跟随事件触发而非独立定时** — 评估不是日报前自动刷新所有活跃 IPO

### 待办
1. 将 LLM 评估改为独立定时任务（日报前自动刷新所有活跃 IPO 的评估）
2. 日报增加"持续跟踪 IPO 的最新评估"板块
3. 处理 GLM 内容过滤问题（可能需要预处理招股书文本或切换 provider）
4. 同行业估值对比的实际数据源对接（当前只靠 LLM 推断）

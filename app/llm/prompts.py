"""LLM Prompt 构造。"""

import json
import re


SYSTEM_PROMPT = """你是一个港股打新信息整理助手。你的任务是：
1. 根据提供的结构化数据生成中文摘要
2. 输出必须为严格的 JSON 格式
3. 不得给出"买入"、"卖出"、"保证赚钱"等投资建议
4. 如实描述风险和不确定性
5. 如果数据缺失，明确标注"当前缺少该字段"
6. 不得编造未知数据

输出 JSON 格式：
{
  "title": "新股提醒标题",
  "summary": "一句话摘要",
  "key_points": ["关键点1", "关键点2"],
  "trigger_reasons": ["触发原因1"],
  "risks": ["风险点1"],
  "suggested_action": "建议关注的时间点或事项",
  "confidence": "low/medium/high"
}"""


def build_summary_prompt(payload: dict) -> list[dict]:
    """构造 IPO 摘要 prompt。"""
    user_content = f"""请根据以下数据生成港股打新提醒摘要：

IPO 数据：
{json.dumps(payload.get('ipo', {}), ensure_ascii=False, indent=2)}

策略判断：
{json.dumps(payload.get('strategy_decision', {}), ensure_ascii=False, indent=2)}
"""

    if payload.get('allotment'):
        user_content += f"\n配发结果：\n{json.dumps(payload['allotment'], ensure_ascii=False, indent=2)}\n"

    if payload.get('grey_market'):
        user_content += f"\n暗盘数据：\n{json.dumps(payload['grey_market'], ensure_ascii=False, indent=2)}\n"

    user_content += "\n请生成 JSON 摘要。"

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def build_daily_digest_prompt(events: list[dict]) -> list[dict]:
    """构造每日汇总 prompt。"""
    digest_system = SYSTEM_PROMPT + """

你现在是生成每日港股打新汇总。
事件中的 ipo、allotment、grey_market 和 strategy_score 字段是日报生成时的当前结构化快照。
对于已提供的字段，必须在要点中准确覆盖招股日期、上市日期、发售价、每手股数、入场费、行业及 business_overview（主营业务官方章程摘要）等关键信息，不得称其缺失。
可将 business_overview 简明翻译或归纳为中文主营业务，但不得添加原文没有的业务或判断。
strategy_score 中的 score 是 AI 评委分，是日报唯一主评分；不得提及旧规则评分体系。
new_ipo 表示系统发现仍处于跟踪阶段的新股，不要擅自表述为递交 IPO 申请。
ipo_follow_up 表示此前已发现且尚待上市的跟踪提醒，必须提及 days_to_listing 和 detail_digest_date（如提供）。
active_ipo_evaluation 表示 AI 关注 Top 10，不代表今日发生新事件；必须优先概括 rank、ai_score、company_overview、recommended_action 和核心入榜理由。
ai_review_status=pending 表示 AI 评审待补充或失败；ai_review_status=not_ranked 表示已评审但不符合 Top 标准。必须说明已知信息、unknown_fields、top_exclusion_reasons 和 ai_review_note。"""

    user_content = f"""请根据今日事件及持续跟踪项目生成每日港股打新汇总：

日报项目：
{json.dumps(events, ensure_ascii=False, indent=2)}

请生成 JSON 格式的每日汇总。"""

    return [
        {"role": "system", "content": digest_system},
        {"role": "user", "content": user_content},
    ]


EVALUATION_SYSTEM_PROMPT = """你是一个专业的港股 IPO 分析师。你的任务是：
1. 根据提供的招股书信息、财务数据和行业背景，对新股进行结构化评估
2. 每个维度打 1-10 分（1=极差, 5=一般, 8=优秀, 10=顶级）
3. 每个维度必须给出 reason：用具体事实陈述（数字、数据、具体事件），不要用"良好""尚可""较强"等定性概括词
4. 输出必须为严格的 JSON 格式
5. 不得给出"保证赚钱"等投资建议
6. 如实描述风险，宁可保守
7. 如果数据缺失，基于已有信息给出评估并降低 confidence
8. 不得编造未知数据

评分标准：
- business_quality (商业模式): 客户粘性、竞争壁垒、可扩展性、行业地位
- financial_health (财务健康): 收入增速、盈利能力、现金流、负债率
- valuation_fairness (定价合理): 与同行业已上市公司的 PE/PB/PS 对比，招股价是否偏贵
- growth_prospect (增长前景): 行业空间、渗透率、政策支持、技术趋势
- risk_level (风险等级): low/medium/high/very_high
- recommended_action: subscribe(建议申购)/skip(建议放弃)/watch(观望)

reason 写法要求：
- 不要写"商业模式清晰，竞争壁垒高"这种定性概括
- 要写"公司是国内第二大SaaS供应商，客户续约率92%，拥有12项核心专利"
- 不要写"财务状况良好，盈利能力尚可"
- 要写"2025年收入50亿港元，同比增长25%，净利润8亿，毛利率45%"

输出 JSON 格式：
{
  "business_quality": 7,
  "business_quality_reason": "公司是XX行业第二大供应商，客户续约率92%，拥有12项核心专利",
  "financial_health": 6,
  "financial_health_reason": "2025年收入50亿港元，同比增长25%，净利润8亿，毛利率45%",
  "valuation_fairness": 5,
  "valuation_fairness_reason": "招股价对应PE 15倍，同行业中位数PE 18倍，估值略低于行业平均",
  "growth_prospect": 8,
  "growth_prospect_reason": "目标市场规模800亿元，年增速20%，国家十四五规划明确支持",
  "risk_level": "medium",
  "risk_factors": ["前五大客户占收入65%", "尚未实现盈利"],
  "comparable_companies": ["公司A (01234.HK)", "公司B (05678.HK)"],
  "recommended_action": "subscribe",
  "confidence": "medium",
  "reasoning": "综合评估..."
}"""


def build_evaluation_prompt(ipo_data: dict) -> list[dict]:
    """构造 IPO 结构化评估 prompt。

    Args:
        ipo_data: IPOItem 的 model_dump 数据，包含 business_overview、
                  行业、招股价、入场费、基石投资者等信息。
    """
    user_content = f"""请对以下港股新股进行结构化评估：

IPO 数据：
{json.dumps(ipo_data, ensure_ascii=False, indent=2)}

请根据招股书信息和行业背景，输出 JSON 格式的结构化评估。"""

    return [
        {"role": "system", "content": EVALUATION_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


FINANCIAL_EXTRACTION_PROMPT = """你是一个港股招股书财务数据提取专家。从以下招股书中提取关键财务数据。

提取规则：
1. 只提取招股书中明确写出的数字，不得编造
2. 金额统一转换为百万港元
3. 如果某项数据在招股书中找不到，设为 null
4. 输出必须为严格的 JSON 格式

输出 JSON 格式：
{
  "revenue_hkd_million": 1234.5,
  "net_profit_hkd_million": 567.8,
  "revenue_growth_yoy": 25.3,
  "net_profit_growth_yoy": 30.1,
  "gross_margin": 45.2,
  "net_margin": 18.5,
  "total_debt_to_equity": 0.6,
  "fiscal_year": "FY2025"
}"""


def build_financial_extraction_prompt(prospectus_text: str) -> list[dict]:
    """构造招股书财务数据提取 prompt。"""
    text = _extract_financial_context(prospectus_text)

    user_content = f"""请从以下招股书中提取关键财务数据：

{text}

请输出 JSON 格式的财务数据。如果某项数据找不到，设为 null。"""

    return [
        {"role": "system", "content": FINANCIAL_EXTRACTION_PROMPT},
        {"role": "user", "content": user_content},
    ]


def _extract_financial_context(prospectus_text: str, limit: int = 8000) -> str:
    """优先抽取招股书中的财务相关段落，避免只截到目录或业务概览。"""
    if len(prospectus_text) <= limit:
        return prospectus_text

    keywords = [
        "financial information",
        "financial highlights",
        "summary financial",
        "selected financial",
        "revenue",
        "gross profit",
        "net profit",
        "loss for the year",
        "year ended",
        "收入",
        "收益",
        "毛利",
        "净利润",
        "淨利潤",
        "亏损",
        "虧損",
        "截至",
    ]
    paragraphs = re.split(r"\n\s*\n+", prospectus_text)
    matches = [
        paragraph.strip()
        for paragraph in paragraphs
        if any(keyword in paragraph.lower() for keyword in keywords)
    ]
    context = "\n\n".join(matches)
    return context[:limit] if context else prospectus_text[:limit]


def build_enriched_evaluation_prompt(
    ipo_data: dict,
    financials: dict | None = None,
    sponsor_stats: dict | None = None,
    market_heat: dict | None = None,
) -> list[dict]:
    """构造带额外上下文的 IPO 评估 prompt。

    在基础评估 prompt 之上追加：
    - 招股书财务数据
    - 保荐人历史表现
    - 近期 IPO 市场热度
    """
    user_content = f"""请对以下港股新股进行结构化评估：

IPO 数据：
{json.dumps(ipo_data, ensure_ascii=False, indent=2)}
"""

    if financials:
        user_content += f"""
招股书财务数据：
{json.dumps(financials, ensure_ascii=False, indent=2)}
"""

    if sponsor_stats:
        user_content += f"""
保荐人历史表现：
{json.dumps(sponsor_stats, ensure_ascii=False, indent=2)}
"""

    if market_heat:
        user_content += f"""
近期 IPO 市场热度：
{json.dumps(market_heat, ensure_ascii=False, indent=2)}
"""

    user_content += "\n请综合以上信息，输出 JSON 格式的结构化评估。"

    return [
        {"role": "system", "content": EVALUATION_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

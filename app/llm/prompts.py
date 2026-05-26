"""LLM Prompt 构造。"""

import json


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
    digest_system = SYSTEM_PROMPT + "\n\n你现在是生成每日港股打新汇总。"

    user_content = f"""请根据今日事件生成每日港股打新汇总：

今日事件：
{json.dumps(events, ensure_ascii=False, indent=2)}

请生成 JSON 格式的每日汇总。"""

    return [
        {"role": "system", "content": digest_system},
        {"role": "user", "content": user_content},
    ]

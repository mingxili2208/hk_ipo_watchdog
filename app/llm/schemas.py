"""LLM 输出 JSON Schema 校验。"""

REQUIRED_FIELDS = ["title", "summary", "key_points", "trigger_reasons", "risks", "suggested_action", "confidence"]
VALID_CONFIDENCE = ["low", "medium", "high"]


def validate_summary_json(data: dict) -> bool:
    """校验 LLM 输出是否符合 JSON schema。"""
    if not isinstance(data, dict):
        return False

    for field in REQUIRED_FIELDS:
        if field not in data:
            return False

    if not isinstance(data.get("title"), str):
        return False

    if not isinstance(data.get("summary"), str):
        return False

    if not isinstance(data.get("key_points"), list):
        return False

    if not isinstance(data.get("trigger_reasons"), list):
        return False

    if not isinstance(data.get("risks"), list):
        return False

    if not isinstance(data.get("suggested_action"), str):
        return False

    if data.get("confidence") not in VALID_CONFIDENCE:
        return False

    return True

"""LLM 输出 JSON Schema 校验。"""

SUMMARY_REQUIRED_FIELDS = [
    "title", "summary", "key_points", "trigger_reasons",
    "risks", "suggested_action", "confidence",
]
VALID_CONFIDENCE = ["low", "medium", "high"]
VALID_RISK_LEVEL = ["low", "medium", "high", "very_high"]
VALID_ACTION = ["subscribe", "skip", "watch"]

EVALUATION_INT_FIELDS = {
    "business_quality": (1, 10),
    "financial_health": (1, 10),
    "valuation_fairness": (1, 10),
    "growth_prospect": (1, 10),
}


def summary_validation_errors(data: dict) -> list[str]:
    """Return schema validation failures without logging generated content."""
    if not isinstance(data, dict):
        return ["response is not an object"]

    errors = []
    for field in SUMMARY_REQUIRED_FIELDS:
        if field not in data:
            errors.append(f"missing field: {field}")

    for field in ("title", "summary", "suggested_action"):
        if field in data and not isinstance(data[field], str):
            errors.append(f"field is not a string: {field}")

    for field in ("key_points", "trigger_reasons", "risks"):
        if field in data and not isinstance(data[field], list):
            errors.append(f"field is not a list: {field}")

    if "confidence" in data and data["confidence"] not in VALID_CONFIDENCE:
        errors.append("confidence must be one of: low, medium, high")

    return errors


def validate_summary_json(data: dict) -> bool:
    """校验 LLM 输出是否符合 JSON schema。"""
    return not summary_validation_errors(data)


def evaluation_validation_errors(data: dict) -> list[str]:
    """校验 LLM 结构化评估输出。"""
    if not isinstance(data, dict):
        return ["response is not an object"]

    errors = []
    for field, (lo, hi) in EVALUATION_INT_FIELDS.items():
        if field not in data:
            errors.append(f"missing field: {field}")
        elif not isinstance(data[field], int) or not (lo <= data[field] <= hi):
            errors.append(f"{field} must be int between {lo} and {hi}")

    if "risk_level" not in data:
        errors.append("missing field: risk_level")
    elif data["risk_level"] not in VALID_RISK_LEVEL:
        errors.append(f"risk_level must be one of: {', '.join(VALID_RISK_LEVEL)}")

    if "recommended_action" not in data:
        errors.append("missing field: recommended_action")
    elif data["recommended_action"] not in VALID_ACTION:
        errors.append(f"recommended_action must be one of: {', '.join(VALID_ACTION)}")

    for field in ("risk_factors", "comparable_companies"):
        if field in data and not isinstance(data[field], list):
            errors.append(f"field is not a list: {field}")

    if "confidence" in data and data["confidence"] not in VALID_CONFIDENCE:
        errors.append("confidence must be one of: low, medium, high")

    if "reasoning" in data and not isinstance(data["reasoning"], str):
        errors.append("reasoning must be a string")

    for field in (
        "business_quality_reason", "financial_health_reason",
        "valuation_fairness_reason", "growth_prospect_reason",
    ):
        if field in data and not isinstance(data[field], str):
            errors.append(f"{field} must be a string")

    return errors


def validate_evaluation_json(data: dict) -> bool:
    """校验 LLM 评估输出是否符合 JSON schema。"""
    return not evaluation_validation_errors(data)


FINANCIAL_OPTIONAL_FLOATS = [
    "revenue_hkd_million", "net_profit_hkd_million",
    "revenue_growth_yoy", "net_profit_growth_yoy",
    "gross_margin", "net_margin", "total_debt_to_equity",
]


def financial_validation_errors(data: dict) -> list[str]:
    """校验 LLM 财务数据提取输出。"""
    if not isinstance(data, dict):
        return ["response is not an object"]

    errors = []
    for field in FINANCIAL_OPTIONAL_FLOATS:
        if field in data and data[field] is not None:
            if not isinstance(data[field], (int, float)):
                errors.append(f"{field} must be number or null")

    if "fiscal_year" in data and data["fiscal_year"] is not None:
        if not isinstance(data["fiscal_year"], str):
            errors.append("fiscal_year must be string or null")

    return errors


def validate_financial_json(data: dict) -> bool:
    """校验 LLM 财务数据提取输出。"""
    return not financial_validation_errors(data)

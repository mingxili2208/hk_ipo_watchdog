"""LLM 输出 JSON Schema 校验。"""

REQUIRED_FIELDS = ["title", "summary", "key_points", "trigger_reasons", "risks", "suggested_action", "confidence"]
VALID_CONFIDENCE = ["low", "medium", "high"]


def summary_validation_errors(data: dict) -> list[str]:
    """Return schema validation failures without logging generated content."""
    if not isinstance(data, dict):
        return ["response is not an object"]

    errors = []
    for field in REQUIRED_FIELDS:
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

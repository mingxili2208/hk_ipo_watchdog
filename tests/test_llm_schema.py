"""LLM JSON Schema 校验测试。"""

from app.llm.schemas import (
    summary_validation_errors,
    validate_summary_json,
    evaluation_validation_errors,
    validate_evaluation_json,
)


def test_valid_summary():
    data = {
        "title": "新股提醒",
        "summary": "该新股符合条件",
        "key_points": ["要点1"],
        "trigger_reasons": ["原因1"],
        "risks": ["风险1"],
        "suggested_action": "等待",
        "confidence": "medium",
    }
    assert validate_summary_json(data) is True


def test_missing_field():
    data = {
        "title": "新股提醒",
        "summary": "该新股符合条件",
    }
    assert validate_summary_json(data) is False


def test_invalid_confidence():
    data = {
        "title": "新股提醒",
        "summary": "摘要",
        "key_points": [],
        "trigger_reasons": [],
        "risks": [],
        "suggested_action": "等待",
        "confidence": "very_high",
    }
    assert validate_summary_json(data) is False


def test_invalid_type():
    assert validate_summary_json("not a dict") is False
    assert validate_summary_json(None) is False
    assert validate_summary_json([]) is False


def test_key_points_not_list():
    data = {
        "title": "新股提醒",
        "summary": "摘要",
        "key_points": "not a list",
        "trigger_reasons": [],
        "risks": [],
        "suggested_action": "等待",
        "confidence": "medium",
    }
    assert validate_summary_json(data) is False


def test_validation_errors_identify_schema_failure_without_content():
    errors = summary_validation_errors({"title": "private content", "confidence": "中"})

    assert "missing field: summary" in errors
    assert "confidence must be one of: low, medium, high" in errors
    assert all("private content" not in error for error in errors)


# ── 评估 Schema 测试 ──

def _valid_evaluation() -> dict:
    return {
        "business_quality": 7,
        "business_quality_reason": "收入来自三个主要产品线",
        "financial_health": 6,
        "financial_health_reason": "最近一年收入同比增长 20%",
        "valuation_fairness": 5,
        "valuation_fairness_reason": "招股价对应估值接近同行中位数",
        "growth_prospect": 8,
        "growth_prospect_reason": "目标行业市场规模持续增长",
        "risk_level": "medium",
        "risk_factors": ["客户集中度高"],
        "comparable_companies": ["公司A"],
        "recommended_action": "subscribe",
        "confidence": "medium",
        "reasoning": "综合评估尚可",
    }


def test_valid_evaluation():
    assert validate_evaluation_json(_valid_evaluation()) is True


def test_evaluation_missing_field():
    data = _valid_evaluation()
    del data["business_quality"]
    assert validate_evaluation_json(data) is False
    errors = evaluation_validation_errors(data)
    assert any("business_quality" in e for e in errors)


def test_evaluation_score_out_of_range():
    data = _valid_evaluation()
    data["business_quality"] = 11
    assert validate_evaluation_json(data) is False


def test_evaluation_invalid_risk_level():
    data = _valid_evaluation()
    data["risk_level"] = "extreme"
    assert validate_evaluation_json(data) is False


def test_evaluation_invalid_action():
    data = _valid_evaluation()
    data["recommended_action"] = "buy"
    assert validate_evaluation_json(data) is False


def test_evaluation_reason_fields_are_optional_for_tolerant_repair():
    data = _valid_evaluation()
    del data["business_quality_reason"]

    assert validate_evaluation_json(data) is True


def test_evaluation_reason_fields_may_be_empty_for_tolerant_repair():
    data = _valid_evaluation()
    data["financial_health_reason"] = " "

    assert validate_evaluation_json(data) is True


def test_evaluation_not_dict():
    assert validate_evaluation_json("not a dict") is False

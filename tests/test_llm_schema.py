"""LLM JSON Schema 校验测试。"""

from app.llm.schemas import validate_summary_json


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

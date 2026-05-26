"""数据标准化模块。"""

import re
from datetime import date, datetime

import dateparser
from loguru import logger


def normalize_hk_code(code: str) -> str:
    """将港股代码统一为 5 位字符串。

    Examples:
        3888 -> 03888
        HK.3888 -> 03888
        03888.HK -> 03888
    """
    if not isinstance(code, str):
        raise ValueError(f"stock code must be str, got {type(code)}")

    code = code.upper().strip()
    code = code.replace("HK.", "").replace(".HK", "")
    digits = re.sub(r"[^0-9]", "", code)

    if not digits or len(digits) > 5:
        raise ValueError(f"invalid HK stock code: {code}")

    return digits.zfill(5)


def normalize_money(value: str | int | float | None) -> float | None:
    """将金额字符串转为 float。

    Examples:
        HK$2,848.44 -> 2848.44
        2,848.44港元 -> 2848.44
        2848.44 -> 2848.44
    """
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    s = str(value).strip()
    if not s:
        return None

    multiplier = 1.0
    s_lower = s.lower()

    if "billion" in s_lower or "十亿" in s:
        multiplier = 1_000_000_000
    elif "million" in s_lower or "百万" in s:
        multiplier = 1_000_000

    s = re.sub(r"(HK\$|USD|港元|港幣|HKD|\$|million|billion|百万|十亿)", "", s, flags=re.IGNORECASE)
    s = s.replace(",", "").strip()

    try:
        return float(s) * multiplier
    except (ValueError, TypeError):
        logger.warning(f"Failed to parse money value: {value}")
        return None


def normalize_percent(value: str | float | int | None) -> float | None:
    """将百分比字符串转为 float。

    Examples:
        5% -> 5.0
        +5.3% -> 5.3
        -2.1% -> -2.1
    """
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    s = str(value).strip()
    if not s:
        return None

    s = s.replace("%", "").strip()
    try:
        return float(s)
    except (ValueError, TypeError):
        logger.warning(f"Failed to parse percent value: {value}")
        return None


def normalize_date(
    value: str | datetime | date | None, timezone_str: str = "Asia/Hong_Kong"
) -> date | None:
    """将不同格式日期统一为 date。

    支持格式: 2026-05-29, 29/05/2026, May 29, 2026, 2026年5月29日
    """
    if value is None:
        return None

    if isinstance(value, date) and not isinstance(value, datetime):
        return value

    if isinstance(value, datetime):
        return value.date()

    s = str(value).strip()
    if not s:
        return None

    # ISO format
    iso_match = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", s)
    if iso_match:
        try:
            return date(int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3)))
        except ValueError:
            pass

    # DD/MM/YYYY
    dmy_match = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", s)
    if dmy_match:
        try:
            return date(int(dmy_match.group(3)), int(dmy_match.group(2)), int(dmy_match.group(1)))
        except ValueError:
            pass

    # 中文日期: 2026年5月29日
    cn_match = re.match(r"^(\d{4})年(\d{1,2})月(\d{1,2})日?$", s)
    if cn_match:
        try:
            return date(int(cn_match.group(1)), int(cn_match.group(2)), int(cn_match.group(3)))
        except ValueError:
            pass

    # dateparser fallback
    try:
        parsed = dateparser.parse(
            s,
            settings={"TIMEZONE": timezone_str, "RETURN_AS_TIMEZONE_AWARE": False},
        )
        if parsed:
            return parsed.date()
    except Exception:
        pass

    logger.warning(f"Failed to parse date: {value}")
    return None

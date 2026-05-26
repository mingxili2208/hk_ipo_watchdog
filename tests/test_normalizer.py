"""Normalizer 单元测试。"""

from datetime import date
import pytest

from app.parsers.normalizer import normalize_hk_code, normalize_money, normalize_percent, normalize_date


class TestNormalizeHKCode:
    def test_plain_digits(self):
        assert normalize_hk_code("3888") == "03888"

    def test_with_leading_zero(self):
        assert normalize_hk_code("03888") == "03888"

    def test_hk_prefix(self):
        assert normalize_hk_code("HK.3888") == "03888"

    def test_hk_suffix(self):
        assert normalize_hk_code("03888.HK") == "03888"

    def test_lowercase(self):
        assert normalize_hk_code("hk.3888") == "03888"

    def test_short_code(self):
        assert normalize_hk_code("1") == "00001"

    def test_five_digit(self):
        assert normalize_hk_code("12345") == "12345"

    def test_invalid_empty(self):
        with pytest.raises(ValueError):
            normalize_hk_code("")

    def test_invalid_none(self):
        with pytest.raises((ValueError, TypeError)):
            normalize_hk_code(None)

    def test_invalid_too_long(self):
        with pytest.raises(ValueError):
            normalize_hk_code("123456")


class TestNormalizeMoney:
    def test_plain_number(self):
        assert normalize_money(2848.44) == 2848.44

    def test_int(self):
        assert normalize_money(3000) == 3000.0

    def test_hk_dollar_prefix(self):
        assert normalize_money("HK$2,848.44") == 2848.44

    def test_chinese_suffix(self):
        assert normalize_money("2,848.44港元") == 2848.44

    def test_plain_string(self):
        assert normalize_money("2848.44") == 2848.44

    def test_none(self):
        assert normalize_money(None) is None

    def test_empty(self):
        assert normalize_money("") is None

    def test_million(self):
        result = normalize_money("100 million")
        assert result == 100_000_000

    def test_billion(self):
        result = normalize_money("1.5 billion")
        assert result == 1_500_000_000


class TestNormalizePercent:
    def test_simple(self):
        assert normalize_percent("5%") == 5.0

    def test_positive(self):
        assert normalize_percent("+5.3%") == 5.3

    def test_negative(self):
        assert normalize_percent("-2.1%") == -2.1

    def test_float(self):
        assert normalize_percent(5.5) == 5.5

    def test_int(self):
        assert normalize_percent(5) == 5.0

    def test_none(self):
        assert normalize_percent(None) is None

    def test_empty(self):
        assert normalize_percent("") is None


class TestNormalizeDate:
    def test_iso_format(self):
        assert normalize_date("2026-05-29") == date(2026, 5, 29)

    def test_dmy_format(self):
        assert normalize_date("29/05/2026") == date(2026, 5, 29)

    def test_chinese_format(self):
        assert normalize_date("2026年5月29日") == date(2026, 5, 29)

    def test_date_object(self):
        d = date(2026, 5, 29)
        assert normalize_date(d) == d

    def test_none(self):
        assert normalize_date(None) is None

    def test_empty(self):
        assert normalize_date("") is None

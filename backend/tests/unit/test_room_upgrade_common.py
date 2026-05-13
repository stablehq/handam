"""room_upgrade_common.py 단위 테스트 (DB 불필요한 유틸만)."""
from datetime import datetime

import pytest

from app.services.room_upgrade_common import (
    last_night_of_stay,
    matches_target_mode,
)


class _Res:
    def __init__(self, check_in, check_out):
        self.check_in_date = check_in
        self.check_out_date = check_out


class TestLastNightOfStay:
    def test_one_night(self):
        # ci=2026-04-15, co=2026-04-16 → last_night = 2026-04-15
        assert last_night_of_stay(_Res("2026-04-15", "2026-04-16")) == "2026-04-15"

    def test_three_nights(self):
        # ci=2026-04-10, co=2026-04-13 → last_night = 2026-04-12
        assert last_night_of_stay(_Res("2026-04-10", "2026-04-13")) == "2026-04-12"

    def test_null_check_out_uses_check_in(self):
        # co 없으면 check_in 자체가 last_night (1박 가정)
        assert last_night_of_stay(_Res("2026-04-15", None)) == "2026-04-15"

    def test_null_check_in_returns_none(self):
        assert last_night_of_stay(_Res(None, "2026-04-16")) is None

    def test_invalid_format_returns_none(self):
        assert last_night_of_stay(_Res("2026-04-15", "not-a-date")) is None


class TestMatchesTargetMode:
    def test_first_night_match(self):
        res = _Res("2026-04-10", "2026-04-13")
        assert matches_target_mode(res, "2026-04-10", "first_night") is True

    def test_first_night_mismatch(self):
        res = _Res("2026-04-10", "2026-04-13")
        assert matches_target_mode(res, "2026-04-11", "first_night") is False

    def test_last_night_match(self):
        res = _Res("2026-04-10", "2026-04-13")
        # last_night = 2026-04-12
        assert matches_target_mode(res, "2026-04-12", "last_night") is True

    def test_last_night_mismatch(self):
        res = _Res("2026-04-10", "2026-04-13")
        assert matches_target_mode(res, "2026-04-10", "last_night") is False

    def test_no_mode_always_true(self):
        """target_mode None 이면 가드 무시 — 항상 True."""
        res = _Res("2026-04-10", "2026-04-13")
        assert matches_target_mode(res, "2026-04-11", None) is True
        assert matches_target_mode(res, "any", None) is True

    def test_unknown_mode_always_true(self):
        """이상한 target_mode 값은 무시 (방어적)."""
        res = _Res("2026-04-10", "2026-04-13")
        assert matches_target_mode(res, "2026-04-10", "weird_mode") is True

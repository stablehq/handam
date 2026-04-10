"""_resolve_date_target() 유닛 테스트 — static method, DB 불필요."""
from datetime import timedelta
from unittest.mock import patch
from app.scheduler.template_scheduler import TemplateScheduleExecutor
from app.config import today_kst, today_kst_date


class TestResolveDateTarget:
    def test_today(self):
        result = TemplateScheduleExecutor._resolve_date_target('today')
        assert result == today_kst()

    def test_tomorrow(self):
        result = TemplateScheduleExecutor._resolve_date_target('tomorrow')
        expected = (today_kst_date() + timedelta(days=1)).strftime('%Y-%m-%d')
        assert result == expected

    def test_today_checkout(self):
        result = TemplateScheduleExecutor._resolve_date_target('today_checkout')
        assert result == today_kst()

    def test_tomorrow_checkout(self):
        result = TemplateScheduleExecutor._resolve_date_target('tomorrow_checkout')
        expected = (today_kst_date() + timedelta(days=1)).strftime('%Y-%m-%d')
        assert result == expected

    def test_consistency_today_variants(self):
        """today와 today_checkout은 같은 날짜를 반환."""
        assert (
            TemplateScheduleExecutor._resolve_date_target('today')
            == TemplateScheduleExecutor._resolve_date_target('today_checkout')
        )

    def test_consistency_tomorrow_variants(self):
        """tomorrow과 tomorrow_checkout은 같은 날짜를 반환."""
        assert (
            TemplateScheduleExecutor._resolve_date_target('tomorrow')
            == TemplateScheduleExecutor._resolve_date_target('tomorrow_checkout')
        )

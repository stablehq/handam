"""_filter_last_day() 통합 테스트 — Reservation ORM 객체 필요."""
import pytest
from app.db.models import Reservation, ReservationStatus
from app.scheduler.template_scheduler import TemplateScheduleExecutor


def _make_reservation(db, name, check_in, check_out=None, stay_group_id=None):
    res = Reservation(
        tenant_id=1, customer_name=name, phone="01000000000",
        check_in_date=check_in, check_in_time="15:00",
        check_out_date=check_out,
        status=ReservationStatus.CONFIRMED,
        stay_group_id=stay_group_id,
    )
    db.add(res)
    db.flush()
    return res


class TestFilterLastDay:
    def _exec(self, db):
        return TemplateScheduleExecutor(db, tenant=None)

    def test_standalone_last_day(self, db):
        """단독 투숙: checkout - 1 == target_date이면 포함."""
        r = _make_reservation(db, "김철수", "2026-04-10", "2026-04-12")
        executor = self._exec(db)
        # target=4/11 → checkout(4/12) - 1 = 4/11 → 포함
        result = executor._filter_last_day([r], "2026-04-11")
        assert len(result) == 1
        assert result[0].id == r.id

    def test_standalone_not_last_day(self, db):
        """단독 투숙: checkout - 1 != target_date이면 제외."""
        r = _make_reservation(db, "김철수", "2026-04-10", "2026-04-12")
        executor = self._exec(db)
        # target=4/10 → checkout(4/12) - 1 = 4/11 ≠ 4/10 → 제외
        result = executor._filter_last_day([r], "2026-04-10")
        assert len(result) == 0

    def test_group_last_day(self, db):
        """연장 그룹: 그룹 내 max(checkout) - 1 == target이면 포함."""
        group_id = "group-1"
        r1 = _make_reservation(db, "연장1", "2026-04-10", "2026-04-12", stay_group_id=group_id)
        r2 = _make_reservation(db, "연장2", "2026-04-12", "2026-04-14", stay_group_id=group_id)
        executor = self._exec(db)
        # 그룹 max checkout = 4/14, last_day = 4/13
        result = executor._filter_last_day([r1, r2], "2026-04-13")
        assert len(result) == 2

    def test_group_not_last_day(self, db):
        """연장 그룹: 중간 날짜면 제외."""
        group_id = "group-2"
        r1 = _make_reservation(db, "연장1", "2026-04-10", "2026-04-12", stay_group_id=group_id)
        r2 = _make_reservation(db, "연장2", "2026-04-12", "2026-04-14", stay_group_id=group_id)
        executor = self._exec(db)
        result = executor._filter_last_day([r1, r2], "2026-04-11")
        assert len(result) == 0

    def test_null_checkout_excluded(self, db):
        """checkout이 NULL이면 제외."""
        r = _make_reservation(db, "체크아웃없음", "2026-04-10", None)
        executor = self._exec(db)
        result = executor._filter_last_day([r], "2026-04-10")
        assert len(result) == 0

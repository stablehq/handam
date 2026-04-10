"""_check_send_condition() 통합 테스트 — DB 세션 필요."""
import pytest
from app.db.models import (
    Reservation, ReservationStatus, MessageTemplate, TemplateSchedule,
)
from app.scheduler.template_scheduler import TemplateScheduleExecutor
from app.config import today_kst


def _setup_executor(db):
    return TemplateScheduleExecutor(db, tenant=None)


def _make_reservations(db, male_count, female_count, date=None):
    """지정 날짜에 체크인하는 예약 1건 생성 (male_count, female_count 설정)."""
    date = date or today_kst()
    res = Reservation(
        tenant_id=1, customer_name="test", phone="01000000000",
        check_in_date=date, check_in_time="15:00",
        status=ReservationStatus.CONFIRMED,
        male_count=male_count, female_count=female_count,
    )
    db.add(res)
    db.flush()
    return res


def _make_schedule_with_condition(db, date_target='today', ratio=2.0, operator='gte'):
    tpl = MessageTemplate(
        tenant_id=1, template_key="cond_test", name="Test",
        content="hello", is_active=True,
    )
    db.add(tpl)
    db.flush()
    sched = TemplateSchedule(
        tenant_id=1, template_id=tpl.id, schedule_name="cond",
        schedule_type="daily", hour=9, minute=0,
        send_condition_date=date_target,
        send_condition_ratio=ratio,
        send_condition_operator=operator,
    )
    db.add(sched)
    db.flush()
    return sched


class TestCheckSendCondition:
    def test_gte_met(self, db):
        """male/female = 10/5, ratio=2.0, gte → True."""
        _make_reservations(db, 10, 5)
        sched = _make_schedule_with_condition(db, ratio=2.0, operator='gte')
        executor = _setup_executor(db)
        assert executor._check_send_condition(sched) is True

    def test_gte_not_met(self, db):
        """male/female = 3/5, ratio=2.0, gte → False."""
        _make_reservations(db, 3, 5)
        sched = _make_schedule_with_condition(db, ratio=2.0, operator='gte')
        executor = _setup_executor(db)
        assert executor._check_send_condition(sched) is False

    def test_lte_met(self, db):
        """male/female = 3/5, ratio=1.0, lte → True (0.6 <= 1.0)."""
        _make_reservations(db, 3, 5)
        sched = _make_schedule_with_condition(db, ratio=1.0, operator='lte')
        executor = _setup_executor(db)
        assert executor._check_send_condition(sched) is True

    def test_female_zero_gte(self, db):
        """female=0이면 ratio=inf → gte는 항상 True."""
        _make_reservations(db, 5, 0)
        sched = _make_schedule_with_condition(db, ratio=100.0, operator='gte')
        executor = _setup_executor(db)
        assert executor._check_send_condition(sched) is True

    def test_female_zero_lte(self, db):
        """female=0이면 ratio=inf → lte는 항상 False."""
        _make_reservations(db, 5, 0)
        sched = _make_schedule_with_condition(db, ratio=100.0, operator='lte')
        executor = _setup_executor(db)
        assert executor._check_send_condition(sched) is False

    def test_both_zero(self, db):
        """male=0, female=0 → False (데이터 없으면 스킵)."""
        _make_reservations(db, 0, 0)
        sched = _make_schedule_with_condition(db, ratio=1.0, operator='gte')
        executor = _setup_executor(db)
        assert executor._check_send_condition(sched) is False

    def test_no_reservations(self, db):
        """예약이 아예 없으면 → False."""
        sched = _make_schedule_with_condition(db, ratio=1.0, operator='gte')
        executor = _setup_executor(db)
        assert executor._check_send_condition(sched) is False

    def test_multiple_reservations_sum(self, db):
        """여러 예약의 male/female을 합산."""
        _make_reservations(db, 3, 2)
        _make_reservations(db, 4, 1)
        # total: male=7, female=3, ratio=2.33
        sched = _make_schedule_with_condition(db, ratio=2.0, operator='gte')
        executor = _setup_executor(db)
        assert executor._check_send_condition(sched) is True

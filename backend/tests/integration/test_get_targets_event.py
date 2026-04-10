"""_get_targets_event() 통합 테스트 — in-memory SQLite."""
import pytest
from datetime import datetime, timedelta, timezone
from app.db.models import (
    Reservation, ReservationStatus, MessageTemplate, TemplateSchedule,
    ReservationSmsAssignment,
)
from app.scheduler.template_scheduler import TemplateScheduleExecutor
from app.config import today_kst


def _executor(db):
    return TemplateScheduleExecutor(db, tenant=None)


def _make_template(db, key="evt_tpl"):
    tpl = MessageTemplate(
        tenant_id=1, template_key=key, name="Test", content="hello", is_active=True,
    )
    db.add(tpl)
    db.flush()
    return tpl


def _make_event_schedule(db, template, hours_since_booking=None, gender_filter=None,
                          max_checkin_days=None, exclude_sent=False):
    sched = TemplateSchedule(
        tenant_id=1, template_id=template.id, schedule_name="evt_test",
        schedule_type="hourly", hour=None, minute=0,
        schedule_category='event',
        hours_since_booking=hours_since_booking,
        gender_filter=gender_filter,
        max_checkin_days=max_checkin_days,
        exclude_sent=exclude_sent,
        is_active=True,
    )
    db.add(sched)
    db.flush()
    return sched


def _make_reservation(db, check_in=None, confirmed_at=None, gender=None,
                       status=ReservationStatus.CONFIRMED, is_long_stay=False):
    check_in = check_in or today_kst()
    res = Reservation(
        tenant_id=1, customer_name="손님", phone="01012345678",
        check_in_date=check_in, check_in_time="15:00",
        status=status,
        confirmed_at=confirmed_at,
        gender=gender,
        is_long_stay=is_long_stay,
    )
    db.add(res)
    db.flush()
    return res


class TestGetTargetsEvent:
    def test_within_hours_since_booking_included(self, db):
        """예약 확정 N시간 이내 → 포함."""
        tpl = _make_template(db)
        sched = _make_event_schedule(db, tpl, hours_since_booking=24)
        confirmed = datetime.now(timezone.utc) - timedelta(hours=1)
        res = _make_reservation(db, check_in=today_kst(), confirmed_at=confirmed)

        executor = _executor(db)
        targets = executor._get_targets_event(sched)
        assert res.id in [r.id for r in targets]

    def test_outside_hours_since_booking_excluded(self, db):
        """예약 확정 N시간 초과 → 제외."""
        tpl = _make_template(db, key="evt_tpl2")
        sched = _make_event_schedule(db, tpl, hours_since_booking=2)
        old_confirmed = datetime.now(timezone.utc) - timedelta(hours=5)
        res = _make_reservation(db, check_in=today_kst(), confirmed_at=old_confirmed)

        executor = _executor(db)
        targets = executor._get_targets_event(sched)
        assert res.id not in [r.id for r in targets]

    def test_gender_filter_male_only(self, db):
        """gender_filter=male — 남성 예약자만 포함."""
        tpl = _make_template(db, key="evt_male")
        sched = _make_event_schedule(db, tpl, gender_filter='male')
        res_male = _make_reservation(db, check_in=today_kst(), gender='남')
        res_female = _make_reservation(db, check_in=today_kst(), gender='여')

        executor = _executor(db)
        targets = executor._get_targets_event(sched)
        ids = [r.id for r in targets]
        assert res_male.id in ids
        assert res_female.id not in ids

    def test_gender_filter_female_only(self, db):
        """gender_filter=female — 여성 예약자만 포함."""
        tpl = _make_template(db, key="evt_female")
        sched = _make_event_schedule(db, tpl, gender_filter='female')
        res_male = _make_reservation(db, check_in=today_kst(), gender='남')
        res_female = _make_reservation(db, check_in=today_kst(), gender='여')

        executor = _executor(db)
        targets = executor._get_targets_event(sched)
        ids = [r.id for r in targets]
        assert res_female.id in ids
        assert res_male.id not in ids

    def test_max_checkin_days_filters_far_future(self, db):
        """max_checkin_days — 범위 밖 체크인 제외."""
        from datetime import date
        tpl = _make_template(db, key="evt_maxdays")
        sched = _make_event_schedule(db, tpl, max_checkin_days=3)
        far_future = (date.fromisoformat(today_kst()) + timedelta(days=10)).isoformat()
        res = _make_reservation(db, check_in=far_future)

        executor = _executor(db)
        targets = executor._get_targets_event(sched)
        assert res.id not in [r.id for r in targets]

    def test_no_confirmed_at_excluded_when_hours_filter(self, db):
        """confirmed_at=NULL인 수동 예약 → hours_since_booking 필터 시 제외."""
        tpl = _make_template(db, key="evt_nullconf")
        sched = _make_event_schedule(db, tpl, hours_since_booking=24)
        res = _make_reservation(db, check_in=today_kst(), confirmed_at=None)

        executor = _executor(db)
        targets = executor._get_targets_event(sched)
        assert res.id not in [r.id for r in targets]

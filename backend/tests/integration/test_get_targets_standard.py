"""_get_targets_standard() 통합 테스트 — in-memory SQLite."""
import json
import pytest
from datetime import datetime, timezone
from app.db.models import (
    Reservation, ReservationStatus, MessageTemplate, TemplateSchedule,
    ReservationSmsAssignment,
)
from app.scheduler.template_scheduler import TemplateScheduleExecutor
from app.config import today_kst


def _executor(db):
    return TemplateScheduleExecutor(db, tenant=None)


def _make_template(db, key="std_tpl"):
    tpl = MessageTemplate(
        tenant_id=1, template_key=key, name="Test", content="hello", is_active=True,
    )
    db.add(tpl)
    db.flush()
    return tpl


def _make_schedule(db, template, target_mode='once', date_target='today',
                   exclude_sent=False, once_per_stay=False, stay_filter=None):
    sched = TemplateSchedule(
        tenant_id=1, template_id=template.id, schedule_name="std_test",
        schedule_type="daily", hour=9, minute=0,
        target_mode=target_mode,
        date_target=date_target,
        exclude_sent=exclude_sent,
        once_per_stay=once_per_stay,
        stay_filter=stay_filter,
        is_active=True,
    )
    db.add(sched)
    db.flush()
    return sched


def _make_reservation(db, check_in=None, check_out=None, status=ReservationStatus.CONFIRMED,
                       is_long_stay=False, stay_group_id=None):
    check_in = check_in or today_kst()
    res = Reservation(
        tenant_id=1, customer_name="손님", phone="01012345678",
        check_in_date=check_in, check_in_time="15:00",
        check_out_date=check_out,
        status=status,
        is_long_stay=is_long_stay,
        stay_group_id=stay_group_id,
    )
    db.add(res)
    db.flush()
    return res


class TestGetTargetsStandard:
    def test_once_mode_checkin_today_included(self, db):
        """once 모드 — 오늘 체크인 예약 포함."""
        tpl = _make_template(db)
        sched = _make_schedule(db, tpl, target_mode='once', date_target='today')
        res = _make_reservation(db, check_in=today_kst())

        executor = _executor(db)
        targets = executor._get_targets_standard(sched)
        assert res.id in [r.id for r in targets]

    def test_once_mode_future_checkin_excluded(self, db):
        """once 모드 — 미래 체크인 예약 제외."""
        tpl = _make_template(db)
        sched = _make_schedule(db, tpl, target_mode='once', date_target='today')
        res = _make_reservation(db, check_in="2099-01-01")

        executor = _executor(db)
        targets = executor._get_targets_standard(sched)
        assert res.id not in [r.id for r in targets]

    def test_daily_mode_stay_included(self, db):
        """daily 모드 — 오늘 숙박 중인 예약 포함 (체크인 < 오늘 < 체크아웃)."""
        from datetime import timedelta, date
        today = today_kst()
        yesterday = (date.fromisoformat(today) - timedelta(days=1)).isoformat()
        tomorrow = (date.fromisoformat(today) + timedelta(days=1)).isoformat()

        tpl = _make_template(db, key="daily_tpl")
        sched = _make_schedule(db, tpl, target_mode='daily', date_target='today')
        res = _make_reservation(db, check_in=yesterday, check_out=tomorrow)

        executor = _executor(db)
        targets = executor._get_targets_standard(sched)
        assert res.id in [r.id for r in targets]

    def test_exclude_sent_filters_sent_reservation(self, db):
        """exclude_sent=True — 이미 발송된 예약 제외."""
        tpl = _make_template(db, key="excl_tpl")
        sched = _make_schedule(db, tpl, target_mode='once', date_target='today', exclude_sent=True)
        res = _make_reservation(db, check_in=today_kst())

        # Mark as sent
        chip = ReservationSmsAssignment(
            tenant_id=1,
            reservation_id=res.id,
            template_key=tpl.template_key,
            date=today_kst(),
            assigned_by='schedule',
            sent_at=datetime.now(timezone.utc),
        )
        db.add(chip)
        db.flush()

        executor = _executor(db)
        targets = executor._get_targets_standard(sched)
        assert res.id not in [r.id for r in targets]

    def test_stay_filter_exclude_removes_long_stay(self, db):
        """stay_filter=exclude — 연박자 제외."""
        tpl = _make_template(db, key="stay_excl_tpl")
        sched = _make_schedule(db, tpl, target_mode='once', date_target='today',
                               stay_filter='exclude')
        res_normal = _make_reservation(db, check_in=today_kst(), is_long_stay=False)
        res_long = _make_reservation(db, check_in=today_kst(), is_long_stay=True)

        executor = _executor(db)
        targets = executor._get_targets_standard(sched)
        ids = [r.id for r in targets]
        assert res_normal.id in ids
        assert res_long.id not in ids

    def test_cancelled_reservation_excluded(self, db):
        """취소 예약 → 제외."""
        tpl = _make_template(db, key="cancel_tpl")
        sched = _make_schedule(db, tpl, target_mode='once', date_target='today')
        res = _make_reservation(db, check_in=today_kst(),
                                status=ReservationStatus.CANCELLED)

        executor = _executor(db)
        targets = executor._get_targets_standard(sched)
        assert res.id not in [r.id for r in targets]

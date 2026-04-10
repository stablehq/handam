"""reconcile_chips_for_schedule() 통합 테스트 — in-memory SQLite."""
import json
import pytest
from datetime import datetime, timezone
from app.db.models import (
    Reservation, Room, Building, RoomAssignment,
    ReservationStatus, TemplateSchedule, MessageTemplate,
    ReservationSmsAssignment,
)
from app.services.chip_reconciler import reconcile_chips_for_schedule
from app.config import today_kst


def _make_template(db, key="tpl_test"):
    tpl = MessageTemplate(
        tenant_id=1, template_key=key, name="Test", content="hello", is_active=True,
    )
    db.add(tpl)
    db.flush()
    return tpl


def _make_schedule(db, template, is_active=True, target_mode='once', date_target='today'):
    sched = TemplateSchedule(
        tenant_id=1, template_id=template.id, schedule_name="test",
        schedule_type="daily", hour=9, minute=0,
        is_active=is_active,
        target_mode=target_mode,
        date_target=date_target,
    )
    db.add(sched)
    db.flush()
    return sched


def _make_reservation(db, check_in=None, status=ReservationStatus.CONFIRMED):
    check_in = check_in or today_kst()
    res = Reservation(
        tenant_id=1, customer_name="손님", phone="01012345678",
        check_in_date=check_in, check_in_time="15:00",
        status=status,
    )
    db.add(res)
    db.flush()
    return res


class TestReconcileChipsForSchedule:
    def test_active_schedule_creates_chips(self, db):
        """활성 스케줄 + 매칭 예약 → 칩 생성."""
        tpl = _make_template(db)
        sched = _make_schedule(db, tpl, is_active=True)
        res = _make_reservation(db, check_in=today_kst())

        created = reconcile_chips_for_schedule(db, sched)
        db.flush()

        assert created >= 1
        chips = db.query(ReservationSmsAssignment).filter(
            ReservationSmsAssignment.reservation_id == res.id,
            ReservationSmsAssignment.template_key == tpl.template_key,
        ).all()
        assert len(chips) >= 1

    def test_inactive_schedule_deletes_chips(self, db):
        """비활성 스케줄 → 기존 칩 삭제."""
        tpl = _make_template(db, key="tpl_inactive")
        sched = _make_schedule(db, tpl, is_active=False)
        res = _make_reservation(db)

        # Pre-create a chip owned by this schedule
        chip = ReservationSmsAssignment(
            tenant_id=1,
            reservation_id=res.id,
            template_key=tpl.template_key,
            date=today_kst(),
            assigned_by='schedule',
            schedule_id=sched.id,
        )
        db.add(chip)
        db.flush()

        reconcile_chips_for_schedule(db, sched)
        db.flush()

        remaining = db.query(ReservationSmsAssignment).filter(
            ReservationSmsAssignment.reservation_id == res.id,
            ReservationSmsAssignment.template_key == tpl.template_key,
            ReservationSmsAssignment.schedule_id == sched.id,
        ).all()
        assert len(remaining) == 0

    def test_sent_chip_preserved(self, db):
        """sent_at 있는 칩(발송 완료)은 보호 — 삭제 안 됨."""
        tpl = _make_template(db, key="tpl_sent")
        sched = _make_schedule(db, tpl, is_active=False)
        res = _make_reservation(db)

        chip = ReservationSmsAssignment(
            tenant_id=1,
            reservation_id=res.id,
            template_key=tpl.template_key,
            date=today_kst(),
            assigned_by='schedule',
            schedule_id=sched.id,
            sent_at=datetime.now(timezone.utc),
        )
        db.add(chip)
        db.flush()

        reconcile_chips_for_schedule(db, sched)
        db.flush()

        remaining = db.query(ReservationSmsAssignment).filter(
            ReservationSmsAssignment.reservation_id == res.id,
            ReservationSmsAssignment.template_key == tpl.template_key,
        ).all()
        # sent chip preserved
        assert len(remaining) == 1
        assert remaining[0].sent_at is not None

    def test_manual_chip_preserved(self, db):
        """assigned_by='manual' 칩은 보호 — 삭제 안 됨."""
        tpl = _make_template(db, key="tpl_manual")
        sched = _make_schedule(db, tpl, is_active=False)
        res = _make_reservation(db)

        chip = ReservationSmsAssignment(
            tenant_id=1,
            reservation_id=res.id,
            template_key=tpl.template_key,
            date=today_kst(),
            assigned_by='manual',
            schedule_id=sched.id,
        )
        db.add(chip)
        db.flush()

        reconcile_chips_for_schedule(db, sched)
        db.flush()

        remaining = db.query(ReservationSmsAssignment).filter(
            ReservationSmsAssignment.reservation_id == res.id,
            ReservationSmsAssignment.template_key == tpl.template_key,
        ).all()
        assert len(remaining) == 1
        assert remaining[0].assigned_by == 'manual'

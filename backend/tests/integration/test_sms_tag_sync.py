"""sync_sms_tags() / chip_reconciler 통합 테스트 — 객실 배정 변경 시 SMS 배정이 올바르게 동기화되는지."""
import json
import pytest
from app.db.models import (
    Reservation, Room, Building, RoomAssignment,
    ReservationStatus, MessageTemplate, TemplateSchedule,
    ReservationSmsAssignment,
)
from app.services.chip_reconciler import reconcile_chips_for_reservation


def _setup(db):
    """공통 테스트 데이터: 건물, 객실, 템플릿, 스케줄."""
    building = Building(tenant_id=1, name="본관", is_active=True)
    db.add(building)
    db.flush()

    room = Room(
        tenant_id=1, room_number="101", room_type="standard",
        building_id=building.id, is_active=True,
    )
    db.add(room)
    db.flush()

    tpl = MessageTemplate(
        tenant_id=1, template_key="room_guide", name="객실안내",
        content="{{customer_name}}님 {{room_num}}호", is_active=True,
    )
    db.add(tpl)
    db.flush()

    sched = TemplateSchedule(
        tenant_id=1, template_id=tpl.id, schedule_name="객실안내 발송",
        schedule_type="daily", hour=15, minute=0,
        date_target="today", target_mode="once",
        filters=json.dumps([
            {"type": "assignment", "value": "room"},
            {"type": "building", "value": str(building.id)},
        ]),
    )
    db.add(sched)
    db.flush()

    return building, room, tpl, sched


def _make_reservation(db, name="김철수", check_in="2026-04-10", check_out="2026-04-11"):
    res = Reservation(
        tenant_id=1, customer_name=name, phone="01012345678",
        check_in_date=check_in, check_in_time="15:00",
        check_out_date=check_out,
        status=ReservationStatus.CONFIRMED, section="room",
    )
    db.add(res)
    db.flush()
    return res


def _assign_room(db, reservation, room, date="2026-04-10"):
    ra = RoomAssignment(
        tenant_id=1, reservation_id=reservation.id,
        room_id=room.id, date=date, assigned_by="auto",
    )
    db.add(ra)
    db.flush()
    return ra


def _get_chips(db, reservation_id, template_key="room_guide"):
    return db.query(ReservationSmsAssignment).filter(
        ReservationSmsAssignment.reservation_id == reservation_id,
        ReservationSmsAssignment.template_key == template_key,
    ).all()


class TestChipCreation:
    def test_assign_creates_chip(self, db):
        """객실 배정 후 reconcile하면 SMS 칩이 생성된다."""
        building, room, tpl, sched = _setup(db)
        res = _make_reservation(db)
        _assign_room(db, res, room)

        reconcile_chips_for_reservation(db, res.id)
        db.flush()

        chips = _get_chips(db, res.id)
        assert len(chips) >= 1
        assert chips[0].template_key == "room_guide"
        assert chips[0].date == "2026-04-10"

    def test_unassigned_no_chip(self, db):
        """미배정 예약은 building 필터를 통과 못해서 칩 생성 안 됨."""
        building, room, tpl, sched = _setup(db)
        res = _make_reservation(db)
        res.section = "unassigned"
        db.flush()
        # 객실 배정 안 함

        reconcile_chips_for_reservation(db, res.id)
        db.flush()

        chips = _get_chips(db, res.id)
        # unassigned가 building+assignment 필터를 통과할 수도 있으므로
        # 최소한 building 서브쿼리에서 걸러져야 함
        # (building 필터는 RoomAssignment가 있어야 통과)
        room_guide_chips = [c for c in chips if c.template_key == "room_guide"]
        assert len(room_guide_chips) == 0


class TestChipDeletion:
    def test_cancel_clears_unsent_chips(self, db):
        """예약 취소 시 미발송 칩이 삭제된다."""
        building, room, tpl, sched = _setup(db)
        res = _make_reservation(db)
        _assign_room(db, res, room)

        reconcile_chips_for_reservation(db, res.id)
        db.flush()
        assert len(_get_chips(db, res.id)) >= 1

        # 예약 취소
        res.status = ReservationStatus.CANCELLED
        db.flush()

        reconcile_chips_for_reservation(db, res.id)
        db.flush()

        unsent_chips = [c for c in _get_chips(db, res.id) if c.sent_at is None]
        assert len(unsent_chips) == 0


class TestChipProtection:
    def test_sent_chip_not_deleted(self, db):
        """이미 발송된 칩(sent_at 있음)은 삭제되지 않는다."""
        from datetime import datetime, timezone
        building, room, tpl, sched = _setup(db)
        res = _make_reservation(db)
        _assign_room(db, res, room)

        reconcile_chips_for_reservation(db, res.id)
        db.flush()

        chips = _get_chips(db, res.id)
        assert len(chips) >= 1
        # 발송 완료 표시
        chips[0].sent_at = datetime.now(timezone.utc)
        db.flush()

        # 예약 취소해도 발송된 칩은 남아야 함
        res.status = ReservationStatus.CANCELLED
        db.flush()
        reconcile_chips_for_reservation(db, res.id)
        db.flush()

        remaining = _get_chips(db, res.id)
        sent_chips = [c for c in remaining if c.sent_at is not None]
        assert len(sent_chips) == 1

    def test_manual_chip_not_deleted(self, db):
        """수동 배정(assigned_by='manual') 칩은 삭제되지 않는다."""
        building, room, tpl, sched = _setup(db)
        res = _make_reservation(db)

        # 수동으로 칩 생성
        manual_chip = ReservationSmsAssignment(
            tenant_id=1, reservation_id=res.id,
            template_key="room_guide", date="2026-04-10",
            assigned_by="manual",
        )
        db.add(manual_chip)
        db.flush()

        # reconcile 실행 (section이 room이 아니라 필터 불통과해도)
        res.section = "party"
        db.flush()
        reconcile_chips_for_reservation(db, res.id)
        db.flush()

        chips = _get_chips(db, res.id)
        manual_chips = [c for c in chips if c.assigned_by == "manual"]
        assert len(manual_chips) == 1

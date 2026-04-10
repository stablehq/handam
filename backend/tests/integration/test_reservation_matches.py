"""_reservation_matches_schedule() 통합 테스트 — in-memory SQLite."""
import json
import pytest
from app.db.models import (
    Reservation, Room, Building, RoomAssignment,
    ReservationStatus, TemplateSchedule, MessageTemplate,
)
from app.services.chip_reconciler import _reservation_matches_schedule


def _make_template(db, key="tpl_match"):
    tpl = MessageTemplate(
        tenant_id=1, template_key=key, name="Test", content="hello", is_active=True,
    )
    db.add(tpl)
    db.flush()
    return tpl


def _make_schedule(db, template, filters_json=None):
    sched = TemplateSchedule(
        tenant_id=1, template_id=template.id, schedule_name="match_test",
        schedule_type="daily", hour=9, minute=0,
        filters=json.dumps(filters_json) if filters_json else None,
    )
    db.add(sched)
    db.flush()
    return sched


def _make_building(db, name="본관"):
    b = Building(tenant_id=1, name=name, is_active=True)
    db.add(b)
    db.flush()
    return b


def _make_room(db, building_id, room_number="101"):
    r = Room(
        tenant_id=1, room_number=room_number, room_type="standard",
        building_id=building_id, is_active=True,
    )
    db.add(r)
    db.flush()
    return r


def _make_reservation(db, check_in="2026-04-10", check_out="2026-04-12", section="room"):
    res = Reservation(
        tenant_id=1, customer_name="손님", phone="01012345678",
        check_in_date=check_in, check_in_time="15:00",
        check_out_date=check_out,
        status=ReservationStatus.CONFIRMED,
        section=section,
    )
    db.add(res)
    db.flush()
    return res


def _assign_room(db, reservation_id, room_id, date):
    ra = RoomAssignment(
        tenant_id=1, reservation_id=reservation_id,
        room_id=room_id, date=date, assigned_by="auto",
    )
    db.add(ra)
    db.flush()
    return ra


class TestReservationMatchesSchedule:
    def test_no_filters_always_matches(self, db):
        """필터 없음 → 항상 매칭."""
        tpl = _make_template(db)
        sched = _make_schedule(db, tpl, filters_json=None)
        res = _make_reservation(db)

        assert _reservation_matches_schedule(db, sched, res, "2026-04-10") is True

    def test_assignment_filter_room_matches(self, db):
        """section=room + assignment=room 필터 → 매칭."""
        tpl = _make_template(db)
        sched = _make_schedule(db, tpl, [{"type": "assignment", "value": "room"}])
        res = _make_reservation(db, section="room")

        assert _reservation_matches_schedule(db, sched, res, "2026-04-10") is True

    def test_assignment_filter_party_no_match(self, db):
        """section=party + assignment=room 필터 → 미매칭."""
        tpl = _make_template(db)
        sched = _make_schedule(db, tpl, [{"type": "assignment", "value": "room"}])
        res = _make_reservation(db, section="party")

        assert _reservation_matches_schedule(db, sched, res, "2026-04-10") is False

    def test_checkout_date_fallback_to_prev_day(self, db):
        """checkout 당일에는 전날 배정 기준으로 체크."""
        b = _make_building(db)
        room = _make_room(db, b.id)
        tpl = _make_template(db, key="tpl_checkout")
        sched = _make_schedule(db, tpl, [{"type": "building", "value": str(b.id)}])
        res = _make_reservation(db, check_in="2026-04-10", check_out="2026-04-12")

        # Assign on check_out - 1 day (2026-04-11)
        _assign_room(db, res.id, room.id, "2026-04-11")

        # Match on checkout date → fallback to 2026-04-11 assignment
        result = _reservation_matches_schedule(db, sched, res, "2026-04-12")
        assert result is True

    def test_building_filter_no_assignment_no_match(self, db):
        """건물 필터 있는데 배정 없음 → 미매칭."""
        b = _make_building(db)
        tpl = _make_template(db, key="tpl_bld_no_assign")
        sched = _make_schedule(db, tpl, [{"type": "building", "value": str(b.id)}])
        res = _make_reservation(db, section="unassigned")

        assert _reservation_matches_schedule(db, sched, res, "2026-04-10") is False

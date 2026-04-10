"""apply_structural_filters() 통합 테스트 — in-memory SQLite."""
import json
import pytest
from app.db.models import (
    Reservation, Room, Building, RoomAssignment,
    ReservationStatus, TemplateSchedule, MessageTemplate,
)
from app.services.filters import apply_structural_filters


def _make_template(db, key="test_tpl"):
    tpl = MessageTemplate(
        tenant_id=1, template_key=key, name="Test", content="hello", is_active=True,
    )
    db.add(tpl)
    db.flush()
    return tpl


def _make_schedule(db, template, filters_json=None):
    sched = TemplateSchedule(
        tenant_id=1, template_id=template.id, schedule_name="test",
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


def _make_room(db, building_id, room_number="101", is_dorm=False):
    r = Room(
        tenant_id=1, room_number=room_number, room_type="standard",
        building_id=building_id, is_active=True, is_dormitory=is_dorm,
    )
    db.add(r)
    db.flush()
    return r


def _make_reservation(db, name="김철수", section="room", check_in="2026-04-10"):
    res = Reservation(
        tenant_id=1, customer_name=name, phone="01012345678",
        check_in_date=check_in, check_in_time="15:00",
        status=ReservationStatus.CONFIRMED, section=section,
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


class TestAssignmentFilter:
    def test_room_only(self, db):
        r1 = _make_reservation(db, "방배정", section="room")
        r2 = _make_reservation(db, "미배정", section="unassigned")
        tpl = _make_template(db)
        sched = _make_schedule(db, tpl, [{"type": "assignment", "value": "room"}])

        query = db.query(Reservation)
        result = apply_structural_filters(db, query, sched, "2026-04-10")
        ids = {r.id for r in result.all()}

        assert r1.id in ids
        assert r2.id not in ids

    def test_party_only(self, db):
        r1 = _make_reservation(db, "파티", section="party")
        r2 = _make_reservation(db, "방", section="room")
        tpl = _make_template(db)
        sched = _make_schedule(db, tpl, [{"type": "assignment", "value": "party"}])

        query = db.query(Reservation)
        result = apply_structural_filters(db, query, sched, "2026-04-10")
        ids = {r.id for r in result.all()}

        assert r1.id in ids
        assert r2.id not in ids


class TestBuildingFilter:
    def test_single_building(self, db):
        b1 = _make_building(db, "본관")
        b2 = _make_building(db, "별관")
        room1 = _make_room(db, b1.id, "101")
        room2 = _make_room(db, b2.id, "201")
        r1 = _make_reservation(db, "본관손님")
        r2 = _make_reservation(db, "별관손님")
        _assign_room(db, r1, room1)
        _assign_room(db, r2, room2)

        tpl = _make_template(db)
        sched = _make_schedule(db, tpl, [{"type": "building", "value": str(b1.id)}])

        query = db.query(Reservation)
        result = apply_structural_filters(db, query, sched, "2026-04-10")
        ids = {r.id for r in result.all()}

        assert r1.id in ids
        assert r2.id not in ids

    def test_multiple_buildings_or(self, db):
        """같은 타입(building)은 OR로 결합."""
        b1 = _make_building(db, "A동")
        b2 = _make_building(db, "B동")
        room1 = _make_room(db, b1.id, "A101")
        room2 = _make_room(db, b2.id, "B101")
        r1 = _make_reservation(db, "A동손님")
        r2 = _make_reservation(db, "B동손님")
        _assign_room(db, r1, room1)
        _assign_room(db, r2, room2)

        tpl = _make_template(db)
        sched = _make_schedule(db, tpl, [
            {"type": "building", "value": str(b1.id)},
            {"type": "building", "value": str(b2.id)},
        ])

        query = db.query(Reservation)
        result = apply_structural_filters(db, query, sched, "2026-04-10")
        ids = {r.id for r in result.all()}

        assert r1.id in ids
        assert r2.id in ids


class TestCrossTypeAnd:
    def test_building_and_assignment(self, db):
        """다른 타입(building + assignment)은 AND로 결합."""
        b1 = _make_building(db, "본관")
        room1 = _make_room(db, b1.id, "101")
        r1 = _make_reservation(db, "본관+방배정", section="room")
        r2 = _make_reservation(db, "본관+파티", section="party")
        _assign_room(db, r1, room1)
        # r2는 본관에 배정 안 됨

        tpl = _make_template(db)
        sched = _make_schedule(db, tpl, [
            {"type": "building", "value": str(b1.id)},
            {"type": "assignment", "value": "room"},
        ])

        query = db.query(Reservation)
        result = apply_structural_filters(db, query, sched, "2026-04-10")
        ids = {r.id for r in result.all()}

        assert r1.id in ids
        assert r2.id not in ids


class TestColumnMatchFilter:
    def test_contains(self, db):
        r1 = _make_reservation(db, "파티참여")
        r1.party_type = "2"
        r2 = _make_reservation(db, "파티안함")
        r2.party_type = None
        db.flush()

        tpl = _make_template(db)
        sched = _make_schedule(db, tpl, [
            {"type": "column_match", "value": "party_type:is_not_empty:"},
        ])

        query = db.query(Reservation)
        result = apply_structural_filters(db, query, sched, "2026-04-10")
        ids = {r.id for r in result.all()}

        assert r1.id in ids
        assert r2.id not in ids

    def test_is_empty(self, db):
        r1 = _make_reservation(db, "노트있음")
        r1.notes = "요청사항 있음"
        r2 = _make_reservation(db, "노트없음")
        r2.notes = None
        db.flush()

        tpl = _make_template(db)
        sched = _make_schedule(db, tpl, [
            {"type": "column_match", "value": "notes:is_empty:"},
        ])

        query = db.query(Reservation)
        result = apply_structural_filters(db, query, sched, "2026-04-10")
        ids = {r.id for r in result.all()}

        assert r2.id in ids
        assert r1.id not in ids


class TestEmptyFilter:
    def test_no_filters_returns_all(self, db):
        r1 = _make_reservation(db, "손님1")
        r2 = _make_reservation(db, "손님2")

        tpl = _make_template(db)
        sched = _make_schedule(db, tpl, None)

        query = db.query(Reservation)
        result = apply_structural_filters(db, query, sched, "2026-04-10")
        ids = {r.id for r in result.all()}

        assert r1.id in ids
        assert r2.id in ids

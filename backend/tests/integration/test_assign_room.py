"""assign_room() 통합 테스트 — in-memory SQLite."""
import pytest
from app.db.models import Reservation, Room, Building, RoomAssignment, ReservationStatus
from app.services.room_assignment import assign_room


def _make_building(db, name="본관"):
    b = Building(tenant_id=1, name=name, is_active=True)
    db.add(b)
    db.flush()
    return b


def _make_room(db, building_id, room_number="101", is_dorm=False):
    r = Room(
        tenant_id=1, room_number=room_number, room_type="standard",
        building_id=building_id, is_active=True,
        is_dormitory=is_dorm, bed_capacity=2,
    )
    db.add(r)
    db.flush()
    return r


def _make_reservation(db, check_in="2026-04-10", check_out=None, section="unassigned"):
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


class TestAssignRoom:
    def test_single_date_creates_assignment(self, db):
        """단일 날짜 배정 → RoomAssignment 1개 생성."""
        b = _make_building(db)
        room = _make_room(db, b.id)
        res = _make_reservation(db)

        assignments = assign_room(
            db, res.id, room.id, "2026-04-10",
            assigned_by="manual", skip_sms_sync=True, skip_logging=True,
        )
        db.flush()

        assert len(assignments) == 1
        assert assignments[0].room_id == room.id
        assert assignments[0].date == "2026-04-10"

    def test_date_range_creates_multiple_records(self, db):
        """날짜 범위 배정 → 각 날짜 RoomAssignment 생성."""
        b = _make_building(db)
        room = _make_room(db, b.id)
        res = _make_reservation(db, check_in="2026-04-10", check_out="2026-04-13")

        assignments = assign_room(
            db, res.id, room.id, "2026-04-10", end_date="2026-04-13",
            assigned_by="manual", skip_sms_sync=True, skip_logging=True,
        )
        db.flush()

        assert len(assignments) == 3
        dates = {a.date for a in assignments}
        assert dates == {"2026-04-10", "2026-04-11", "2026-04-12"}

    def test_section_updated_to_room(self, db):
        """배정 후 reservation.section → 'room'으로 업데이트."""
        b = _make_building(db)
        room = _make_room(db, b.id)
        res = _make_reservation(db, section="unassigned")

        assign_room(
            db, res.id, room.id, "2026-04-10",
            assigned_by="manual", skip_sms_sync=True, skip_logging=True,
        )
        db.flush()

        assert res.section == "room"

    def test_denormalized_room_number_set(self, db):
        """배정 후 reservation.room_number 비정규화 필드 갱신."""
        b = _make_building(db)
        room = _make_room(db, b.id, room_number="A101")
        res = _make_reservation(db)

        assign_room(
            db, res.id, room.id, "2026-04-10",
            assigned_by="manual", skip_sms_sync=True, skip_logging=True,
        )
        db.flush()

        assert res.room_number == "A101"

    def test_reassign_overwrites_existing(self, db):
        """재배정 시 기존 같은 날짜 배정 삭제 후 신규 생성."""
        b = _make_building(db)
        room1 = _make_room(db, b.id, room_number="101")
        room2 = _make_room(db, b.id, room_number="102")
        res = _make_reservation(db)

        assign_room(
            db, res.id, room1.id, "2026-04-10",
            assigned_by="manual", skip_sms_sync=True, skip_logging=True,
        )
        db.flush()

        assign_room(
            db, res.id, room2.id, "2026-04-10",
            assigned_by="manual", skip_sms_sync=True, skip_logging=True,
        )
        db.flush()

        assignments = db.query(RoomAssignment).filter(
            RoomAssignment.reservation_id == res.id,
            RoomAssignment.date == "2026-04-10",
        ).all()
        assert len(assignments) == 1
        assert assignments[0].room_id == room2.id

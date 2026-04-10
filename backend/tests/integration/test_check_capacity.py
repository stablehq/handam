"""check_capacity_all_dates() 통합 테스트 — in-memory SQLite."""
import pytest
from app.db.models import Reservation, Room, Building, RoomAssignment, ReservationStatus
from app.services.room_assignment import check_capacity_all_dates


def _make_building(db):
    b = Building(tenant_id=1, name="본관", is_active=True)
    db.add(b)
    db.flush()
    return b


def _make_room(db, building_id, is_dorm=False, bed_capacity=2, room_number="101"):
    r = Room(
        tenant_id=1, room_number=room_number, room_type="standard",
        building_id=building_id, is_active=True,
        is_dormitory=is_dorm, bed_capacity=bed_capacity,
    )
    db.add(r)
    db.flush()
    return r


def _make_reservation(db, party_size=1, check_in="2026-04-10", check_out="2026-04-11"):
    res = Reservation(
        tenant_id=1, customer_name="손님", phone="01012345678",
        check_in_date=check_in, check_in_time="15:00",
        check_out_date=check_out,
        status=ReservationStatus.CONFIRMED,
        party_size=party_size,
    )
    db.add(res)
    db.flush()
    return res


def _assign(db, reservation_id, room_id, date):
    ra = RoomAssignment(
        tenant_id=1, reservation_id=reservation_id,
        room_id=room_id, date=date, assigned_by="auto",
    )
    db.add(ra)
    db.flush()
    return ra


class TestCheckCapacity:
    def test_empty_room_returns_true(self, db):
        """빈 방 → True."""
        b = _make_building(db)
        room = _make_room(db, b.id, is_dorm=False)
        result = check_capacity_all_dates(db, room.id, "2026-04-10", "2026-04-11")
        assert result is True

    def test_full_non_dorm_returns_false(self, db):
        """비도미토리 방 이미 점유 → False."""
        b = _make_building(db)
        room = _make_room(db, b.id, is_dorm=False)
        res = _make_reservation(db)
        _assign(db, res.id, room.id, "2026-04-10")

        result = check_capacity_all_dates(db, room.id, "2026-04-10", "2026-04-11")
        assert result is False

    def test_dorm_under_capacity_returns_true(self, db):
        """도미토리 잔여 침대 있음 → True."""
        b = _make_building(db)
        room = _make_room(db, b.id, is_dorm=True, bed_capacity=4)
        res = _make_reservation(db, party_size=1)
        _assign(db, res.id, room.id, "2026-04-10")

        result = check_capacity_all_dates(db, room.id, "2026-04-10", "2026-04-11", people_count=1)
        assert result is True

    def test_dorm_over_capacity_returns_false(self, db):
        """도미토리 초과 → False."""
        b = _make_building(db)
        room = _make_room(db, b.id, is_dorm=True, bed_capacity=2)
        res1 = _make_reservation(db, party_size=1)
        res2 = _make_reservation(db, party_size=1)
        _assign(db, res1.id, room.id, "2026-04-10")
        _assign(db, res2.id, room.id, "2026-04-10")

        result = check_capacity_all_dates(db, room.id, "2026-04-10", "2026-04-11", people_count=1)
        assert result is False

    def test_exclude_reservation_id(self, db):
        """자기 자신 제외하면 빈 방으로 간주 → True."""
        b = _make_building(db)
        room = _make_room(db, b.id, is_dorm=False)
        res = _make_reservation(db)
        _assign(db, res.id, room.id, "2026-04-10")

        result = check_capacity_all_dates(
            db, room.id, "2026-04-10", "2026-04-11",
            exclude_reservation_id=res.id,
        )
        assert result is True

    def test_multi_date_one_full_returns_false(self, db):
        """여러 날짜 중 하나라도 꽉 차면 False."""
        b = _make_building(db)
        room = _make_room(db, b.id, is_dorm=False)
        res = _make_reservation(db, check_in="2026-04-10", check_out="2026-04-12")
        _assign(db, res.id, room.id, "2026-04-11")  # 2일째만 점유

        result = check_capacity_all_dates(db, room.id, "2026-04-10", "2026-04-12")
        assert result is False

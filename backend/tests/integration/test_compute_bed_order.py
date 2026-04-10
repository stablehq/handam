"""_compute_bed_order() 통합 테스트 — in-memory SQLite."""
import pytest
from app.db.models import Reservation, Room, Building, RoomAssignment, ReservationStatus
from app.services.room_assignment import _compute_bed_order


def _make_building(db):
    b = Building(tenant_id=1, name="본관", is_active=True)
    db.add(b)
    db.flush()
    return b


def _make_room(db, building_id, is_dorm=True, bed_capacity=4):
    r = Room(
        tenant_id=1, room_number="D1", room_type="dormitory",
        building_id=building_id, is_active=True,
        is_dormitory=is_dorm, bed_capacity=bed_capacity,
    )
    db.add(r)
    db.flush()
    return r


def _make_reservation(db, check_in="2026-04-10", check_out="2026-04-13", stay_group_id=None):
    res = Reservation(
        tenant_id=1, customer_name="테스트", phone="01000000000",
        check_in_date=check_in, check_in_time="15:00",
        check_out_date=check_out,
        status=ReservationStatus.CONFIRMED,
        stay_group_id=stay_group_id,
    )
    db.add(res)
    db.flush()
    return res


def _assign(db, reservation_id, room_id, date, bed_order=1):
    ra = RoomAssignment(
        tenant_id=1, reservation_id=reservation_id,
        room_id=room_id, date=date,
        assigned_by="auto", bed_order=bed_order,
    )
    db.add(ra)
    db.flush()
    return ra


class TestComputeBedOrder:
    def test_non_dormitory_returns_zero(self, db):
        """비도미토리 방 → 항상 0."""
        b = _make_building(db)
        room = _make_room(db, b.id, is_dorm=False)
        res = _make_reservation(db)
        result = _compute_bed_order(db, res.id, room.id, "2026-04-10", room)
        assert result == 0

    def test_same_reservation_prev_day_inherits_bed_order(self, db):
        """전날 같은 예약 배정 있으면 → 같은 bed_order 재사용."""
        b = _make_building(db)
        room = _make_room(db, b.id, is_dorm=True)
        res = _make_reservation(db, check_in="2026-04-10", check_out="2026-04-13")
        _assign(db, res.id, room.id, "2026-04-10", bed_order=2)

        result = _compute_bed_order(db, res.id, room.id, "2026-04-11", room)
        assert result == 2

    def test_stay_group_prev_day_inherits_bed_order(self, db):
        """같은 그룹 멤버가 전날 배정 → 그 bed_order 재사용."""
        b = _make_building(db)
        room = _make_room(db, b.id, is_dorm=True)
        res1 = _make_reservation(db, check_in="2026-04-09", check_out="2026-04-11", stay_group_id="g1")
        res2 = _make_reservation(db, check_in="2026-04-11", check_out="2026-04-13", stay_group_id="g1")
        _assign(db, res1.id, room.id, "2026-04-10", bed_order=3)

        result = _compute_bed_order(db, res2.id, room.id, "2026-04-11", room)
        assert result == 3

    def test_no_previous_finds_first_vacant_slot(self, db):
        """이전 배정 없음 → 빈 슬롯 1번."""
        b = _make_building(db)
        room = _make_room(db, b.id, is_dorm=True)
        res = _make_reservation(db)

        result = _compute_bed_order(db, res.id, room.id, "2026-04-10", room)
        assert result == 1

    def test_slot_1_taken_returns_2(self, db):
        """슬롯 1이 이미 점유 → 슬롯 2 반환."""
        b = _make_building(db)
        room = _make_room(db, b.id, is_dorm=True)
        res_other = _make_reservation(db, check_in="2026-04-10", check_out="2026-04-11")
        _assign(db, res_other.id, room.id, "2026-04-10", bed_order=1)

        res = _make_reservation(db)
        result = _compute_bed_order(db, res.id, room.id, "2026-04-10", room)
        assert result == 2

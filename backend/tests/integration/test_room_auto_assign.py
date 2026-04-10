"""room_auto_assign 관련 로직 통합 테스트 — in-memory SQLite."""
import pytest
from app.db.models import (
    Reservation, Room, Building, RoomAssignment, RoomBizItemLink,
    ReservationStatus,
)
from app.services.room_assignment import check_capacity_all_dates, assign_room


def _make_building(db, name="본관"):
    b = Building(tenant_id=1, name=name, is_active=True)
    db.add(b)
    db.flush()
    return b


def _make_room(db, building_id, room_number="D1", is_dorm=True, bed_capacity=4):
    r = Room(
        tenant_id=1, room_number=room_number, room_type="dormitory",
        building_id=building_id, is_active=True,
        is_dormitory=is_dorm, bed_capacity=bed_capacity,
    )
    db.add(r)
    db.flush()
    return r


def _make_reservation(db, check_in="2026-04-10", check_out="2026-04-11",
                       gender=None, party_size=1, male_count=None, female_count=None):
    res = Reservation(
        tenant_id=1, customer_name="손님", phone="01012345678",
        check_in_date=check_in, check_in_time="15:00",
        check_out_date=check_out,
        status=ReservationStatus.CONFIRMED,
        gender=gender,
        party_size=party_size,
        male_count=male_count,
        female_count=female_count,
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


class TestGenderLockVerification:
    def test_dorm_not_full_male_can_enter(self, db):
        """도미토리 여유 있음 — 남성 입실 가능."""
        b = _make_building(db)
        room = _make_room(db, b.id, bed_capacity=4)
        res_male = _make_reservation(db, gender='남', party_size=1)
        _assign(db, res_male.id, room.id, "2026-04-10", bed_order=1)

        new_res = _make_reservation(db, gender='남', party_size=1)
        result = check_capacity_all_dates(db, room.id, "2026-04-10", "2026-04-11", people_count=1)
        assert result is True

    def test_dorm_full_cannot_enter(self, db):
        """도미토리 꽉 참 — 추가 입실 불가."""
        b = _make_building(db)
        room = _make_room(db, b.id, bed_capacity=2)

        res1 = _make_reservation(db, gender='남', party_size=1)
        res2 = _make_reservation(db, gender='남', party_size=1)
        _assign(db, res1.id, room.id, "2026-04-10", bed_order=1)
        _assign(db, res2.id, room.id, "2026-04-10", bed_order=2)

        result = check_capacity_all_dates(db, room.id, "2026-04-10", "2026-04-11", people_count=1)
        assert result is False


class TestPrioritySorting:
    def test_lower_bed_order_assigned_first(self, db):
        """bed_order가 낮은 슬롯부터 채워짐 확인."""
        b = _make_building(db)
        room = _make_room(db, b.id, bed_capacity=4)

        res1 = _make_reservation(db)
        assign_room(
            db, res1.id, room.id, "2026-04-10",
            assigned_by="auto", skip_sms_sync=True, skip_logging=True,
        )
        db.flush()

        # First assignment gets bed_order=1
        ra = db.query(RoomAssignment).filter(
            RoomAssignment.reservation_id == res1.id,
            RoomAssignment.date == "2026-04-10",
        ).first()
        assert ra is not None
        assert ra.bed_order == 1

    def test_second_guest_gets_next_bed_order(self, db):
        """두 번째 손님은 슬롯 2번."""
        b = _make_building(db)
        room = _make_room(db, b.id, bed_capacity=4)

        res1 = _make_reservation(db)
        assign_room(
            db, res1.id, room.id, "2026-04-10",
            assigned_by="auto", skip_sms_sync=True, skip_logging=True,
        )
        db.flush()

        res2 = _make_reservation(db)
        assign_room(
            db, res2.id, room.id, "2026-04-10",
            assigned_by="auto", skip_sms_sync=True, skip_logging=True,
        )
        db.flush()

        ra2 = db.query(RoomAssignment).filter(
            RoomAssignment.reservation_id == res2.id,
            RoomAssignment.date == "2026-04-10",
        ).first()
        assert ra2 is not None
        assert ra2.bed_order == 2

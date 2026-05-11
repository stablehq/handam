"""check_assignment_validity() 불변식 검증 통합 테스트 — in-memory SQLite."""
from unittest.mock import patch
from datetime import datetime
from app.db.models import (
    Reservation, Room, Building, RoomAssignment, ReservationStatus,
)
from app.services.room_assignment_invariants import check_assignment_validity


def _make_building(db):
    b = Building(tenant_id=1, name="본관", is_active=True)
    db.add(b)
    db.flush()
    return b


def _make_dorm_room(db, building_id, bed_capacity=4):
    r = Room(
        tenant_id=1, room_number="D1", room_type="dormitory",
        building_id=building_id, is_active=True,
        is_dormitory=True, bed_capacity=bed_capacity,
    )
    db.add(r)
    db.flush()
    return r


def _make_regular_room(db, building_id, room_number="R101"):
    r = Room(
        tenant_id=1, room_number=room_number, room_type="standard",
        building_id=building_id, is_active=True,
        is_dormitory=False, base_capacity=2, max_capacity=2,
    )
    db.add(r)
    db.flush()
    return r


def _make_reservation(db, gender=None, party_size=1):
    res = Reservation(
        tenant_id=1, customer_name="손님", phone="01012345678",
        check_in_date="2026-04-10", check_in_time="15:00",
        check_out_date="2026-04-12",
        status=ReservationStatus.CONFIRMED,
        gender=gender,
        party_size=party_size,
    )
    db.add(res)
    db.flush()
    return res


def _assign(db, reservation_id, room_id, date, bed_order=1):
    ra = RoomAssignment(
        tenant_id=1, reservation_id=reservation_id,
        room_id=room_id, date=date,
        assigned_by="manual", bed_order=bed_order,
    )
    db.add(ra)
    db.flush()
    return ra


# Freeze "today" to a past date so test assignments are always "future"
FROZEN_TODAY = "2026-04-09"


class TestCheckAssignmentValidity:
    def test_no_violation_returns_empty(self, db):
        """정상 배정 → 빈 리스트 반환."""
        b = _make_building(db)
        room = _make_dorm_room(db, b.id, bed_capacity=4)
        res = _make_reservation(db, gender="남", party_size=1)
        _assign(db, res.id, room.id, "2026-04-10")

        with patch("app.services.room_assignment_invariants.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 9, 10, 0)
            mock_dt.strptime = datetime.strptime
            invalid = check_assignment_validity(db, res)

        assert invalid == []

    def test_dorm_gender_conflict_flagged(self, db):
        """도미토리에 이미 입실한 성별 다른 예약자 → 해당 날짜 invalid."""
        b = _make_building(db)
        room = _make_dorm_room(db, b.id, bed_capacity=4)

        female_res = _make_reservation(db, gender="여", party_size=1)
        _assign(db, female_res.id, room.id, "2026-04-10", bed_order=1)

        male_res = _make_reservation(db, gender="남", party_size=1)
        _assign(db, male_res.id, room.id, "2026-04-10", bed_order=2)

        with patch("app.services.room_assignment_invariants.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 9, 10, 0)
            mock_dt.strptime = datetime.strptime
            invalid = check_assignment_validity(db, male_res)

        assert "2026-04-10" in invalid

    def test_regular_room_double_booking_allowed(self, db):
        """일반실 다중 점유 = 운영자 수동 결정으로 허용 → invariant 위반 아님."""
        b = _make_building(db)
        room = _make_regular_room(db, b.id)

        res1 = _make_reservation(db, party_size=1)
        _assign(db, res1.id, room.id, "2026-04-10", bed_order=1)

        res2 = _make_reservation(db, party_size=1)
        _assign(db, res2.id, room.id, "2026-04-10", bed_order=2)

        with patch("app.services.room_assignment_invariants.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 9, 10, 0)
            mock_dt.strptime = datetime.strptime
            invalid = check_assignment_validity(db, res2)

        assert "2026-04-10" not in invalid

    def test_past_dates_not_checked(self, db):
        """과거/당일 배정은 체크 대상 아님 → 위반 있어도 빈 리스트."""
        b = _make_building(db)
        room = _make_regular_room(db, b.id)

        res1 = _make_reservation(db, party_size=1)
        _assign(db, res1.id, room.id, "2026-04-10", bed_order=1)

        res2 = _make_reservation(db, party_size=1)
        _assign(db, res2.id, room.id, "2026-04-10", bed_order=2)

        # "Today" is 2026-04-10, so 4/10 is today (not future) → skipped
        with patch("app.services.room_assignment_invariants.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 10, 10, 0)
            mock_dt.strptime = datetime.strptime
            invalid = check_assignment_validity(db, res2)

        assert "2026-04-10" not in invalid

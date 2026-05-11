"""일반실 수동 공동 점유 정책 통합 테스트 — in-memory SQLite.

정책: 수동 배정은 오늘/미래 구분 없이 공동 점유 허용 (운영자 의도 신뢰).
      자동 배정만 한 방 1팀 강제 (ValueError raise).
"""
from unittest.mock import patch
from datetime import datetime
import pytest
from app.db.models import (
    Reservation, Room, Building, RoomAssignment, ReservationStatus,
)
from app.services.room_assignment import assign_room


def _make_building(db):
    b = Building(tenant_id=1, name="본관", is_active=True)
    db.add(b)
    db.flush()
    return b


def _make_regular_room(db, building_id, room_number="R101"):
    r = Room(
        tenant_id=1, room_number=room_number, room_type="standard",
        building_id=building_id, is_active=True,
        is_dormitory=False, base_capacity=2, max_capacity=2,
    )
    db.add(r)
    db.flush()
    return r


def _make_reservation(db, section="unassigned", party_size=1):
    res = Reservation(
        tenant_id=1, customer_name="손님", phone="01012345678",
        check_in_date="2026-04-10", check_in_time="15:00",
        check_out_date="2026-04-12",
        status=ReservationStatus.CONFIRMED,
        section=section,
        party_size=party_size,
    )
    db.add(res)
    db.flush()
    return res


def _assign_direct(db, reservation_id, room_id, date):
    ra = RoomAssignment(
        tenant_id=1, reservation_id=reservation_id,
        room_id=room_id, date=date,
        assigned_by="manual", bed_order=1,
    )
    db.add(ra)
    db.flush()
    return ra


class TestManualCoOccupancyPolicy:
    def test_future_manual_double_booking_co_occupies(self, db):
        """일반실 미래 수동 이중배정 시 기존자 보존 + 두 RoomAssignment 공존."""
        b = _make_building(db)
        room = _make_regular_room(db, b.id)

        res_existing = _make_reservation(db, section="room")
        _assign_direct(db, res_existing.id, room.id, "2026-04-20")

        res_new = _make_reservation(db, section="unassigned")

        with patch("app.services.room_assignment.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 10, 10, 0)
            mock_dt.strptime = datetime.strptime
            assignments, pushed_out = assign_room(
                db, res_new.id, room.id, "2026-04-20",
                assigned_by="manual", skip_sms_sync=True, skip_logging=True,
            )
        db.flush()

        # 기존 예약자 section 유지 (unassigned 로 바뀌면 안 됨)
        db.refresh(res_existing)
        assert res_existing.section == "room"

        # push-out 없음
        assert pushed_out == []

        # 같은 (room, date) 에 두 RoomAssignment 공존
        rows = db.query(RoomAssignment).filter(
            RoomAssignment.room_id == room.id,
            RoomAssignment.date == "2026-04-20",
        ).all()
        assert len(rows) == 2
        res_ids = {ra.reservation_id for ra in rows}
        assert res_ids == {res_existing.id, res_new.id}

    def test_today_manual_double_booking_co_occupies(self, db):
        """당일 수동 이중배정도 공동 점유 (오늘/미래 동일 정책)."""
        b = _make_building(db)
        room = _make_regular_room(db, b.id)

        res_existing = _make_reservation(db, section="room")
        _assign_direct(db, res_existing.id, room.id, "2026-04-10")

        res_new = _make_reservation(db, section="unassigned")

        with patch("app.services.room_assignment.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 10, 10, 0)
            mock_dt.strptime = datetime.strptime
            assignments, pushed_out = assign_room(
                db, res_new.id, room.id, "2026-04-10",
                assigned_by="manual", skip_sms_sync=True, skip_logging=True,
            )
        db.flush()

        db.refresh(res_existing)
        assert res_existing.section == "room"
        assert pushed_out == []

        rows = db.query(RoomAssignment).filter(
            RoomAssignment.room_id == room.id,
            RoomAssignment.date == "2026-04-10",
        ).all()
        assert len(rows) == 2

    def test_auto_double_booking_raises(self, db):
        """자동 배정은 여전히 한 방 1팀 강제 — 충돌 시 ValueError."""
        b = _make_building(db)
        room = _make_regular_room(db, b.id)

        res_existing = _make_reservation(db, section="room")
        _assign_direct(db, res_existing.id, room.id, "2026-04-20")

        res_new = _make_reservation(db, section="unassigned")

        with patch("app.services.room_assignment.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 10, 10, 0)
            mock_dt.strptime = datetime.strptime
            with pytest.raises(ValueError, match="already occupied"):
                assign_room(
                    db, res_new.id, room.id, "2026-04-20",
                    assigned_by="auto", skip_sms_sync=True, skip_logging=True,
                )

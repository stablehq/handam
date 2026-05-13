"""room_upgrade_promise.py 통합 테스트 — in-memory SQLite.

약속 (첫박 발송) 칩 자동 생성/삭제 검증.
review 와 도메인 룰은 동일하지만 target_date == check_in_date (첫박) 가드.
"""
from datetime import datetime, timezone

from app.db.models import (
    Building,
    MessageTemplate,
    NaverBizItem,
    Reservation,
    ReservationSmsAssignment,
    ReservationStatus,
    Room,
    RoomAssignment,
    TemplateSchedule,
)
from app.services.room_upgrade_promise import (
    ROOM_UPGRADE_PROMISE,
    decide_chip,
    reconcile_room_upgrade_promise,
    reconcile_room_upgrade_promise_batch,
    _delete_all_room_upgrade_promise_chips,
)


DATE = "2026-04-15"
TPL_KEY = "room_upgrade_promise_msg"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_building(db, name="본관"):
    b = Building(tenant_id=1, name=name, is_active=True)
    db.add(b)
    db.flush()
    return b


def _make_room(db, building_id, room_number="R101", base_capacity=2, grade=None):
    r = Room(
        tenant_id=1,
        room_number=room_number,
        room_type="객실",
        building_id=building_id,
        is_active=True,
        is_dormitory=False,
        base_capacity=base_capacity,
        grade=grade,
    )
    db.add(r)
    db.flush()
    return r


def _make_biz_item(db, biz_item_id="BIZ-1", grade=None, default_capacity=2):
    item = NaverBizItem(
        tenant_id=1,
        biz_item_id=biz_item_id,
        name="테스트상품",
        default_capacity=default_capacity,
        grade=grade,
        is_active=True,
    )
    db.add(item)
    db.flush()
    return item


def _make_reservation(
    db, biz_item_id="BIZ-1", party_size=2, check_in=DATE, check_out="2026-04-16"
):
    res = Reservation(
        tenant_id=1,
        customer_name="테스트",
        phone="01012345678",
        check_in_date=check_in,
        check_in_time="15:00",
        check_out_date=check_out,
        status=ReservationStatus.CONFIRMED,
        party_size=party_size,
        naver_biz_item_id=biz_item_id,
    )
    db.add(res)
    db.flush()
    return res


def _make_assignment(db, reservation_id, room_id, date=DATE):
    ra = RoomAssignment(
        tenant_id=1,
        reservation_id=reservation_id,
        room_id=room_id,
        date=date,
        assigned_by="manual",
    )
    db.add(ra)
    db.flush()
    return ra


def _make_template(db):
    t = MessageTemplate(
        tenant_id=1,
        template_key=TPL_KEY,
        name="약속",
        content="무료 업그레이드 약속",
        is_active=True,
    )
    db.add(t)
    db.flush()
    return t


def _make_schedule(db, template, active=True, target_mode="first_night"):
    s = TemplateSchedule(
        tenant_id=1,
        template_id=template.id,
        schedule_name="약속 스케줄",
        schedule_type="daily",
        hour=16,
        minute=0,
        schedule_category="custom_schedule",
        custom_type=ROOM_UPGRADE_PROMISE,
        target_mode=target_mode,
        is_active=active,
    )
    db.add(s)
    db.flush()
    return s


def _chips(db, reservation_id, date=None):
    q = db.query(ReservationSmsAssignment).filter(
        ReservationSmsAssignment.reservation_id == reservation_id,
        ReservationSmsAssignment.template_key == TPL_KEY,
    )
    if date is not None:
        q = q.filter(ReservationSmsAssignment.date == date)
    return q.all()


def _setup_schedule(db, active=True):
    tpl = _make_template(db)
    return _make_schedule(db, tpl, active=active)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDecideChip:
    def test_first_night_upgrade(self, db):
        b = _make_building(db)
        room = _make_room(db, b.id, grade=3)
        item = _make_biz_item(db, grade=2)
        res = _make_reservation(db, biz_item_id=item.biz_item_id, party_size=2)
        _make_assignment(db, res.id, room.id, date=res.check_in_date)
        assert decide_chip(db, res, res.check_in_date) is True

    def test_non_first_night_returns_false(self, db):
        """target_date != check_in_date 면 False (마지막박 영역)."""
        b = _make_building(db)
        room = _make_room(db, b.id, grade=3)
        item = _make_biz_item(db, grade=2)
        res = _make_reservation(
            db,
            biz_item_id=item.biz_item_id,
            party_size=2,
            check_in="2026-04-10",
            check_out="2026-04-12",
        )
        _make_assignment(db, res.id, room.id, date="2026-04-11")
        assert decide_chip(db, res, "2026-04-11") is False

    def test_same_grade_returns_false(self, db):
        b = _make_building(db)
        room = _make_room(db, b.id, grade=2)
        item = _make_biz_item(db, grade=2)
        res = _make_reservation(db, biz_item_id=item.biz_item_id, party_size=2)
        _make_assignment(db, res.id, room.id, date=res.check_in_date)
        assert decide_chip(db, res, res.check_in_date) is False


class TestReconcile:
    def test_first_night_creates_chip(self, db):
        _setup_schedule(db)
        b = _make_building(db)
        room = _make_room(db, b.id, grade=3)
        item = _make_biz_item(db, grade=2)
        res = _make_reservation(db, biz_item_id=item.biz_item_id, party_size=2)
        _make_assignment(db, res.id, room.id, date=res.check_in_date)

        reconcile_room_upgrade_promise(db, res.id, res.check_in_date)
        chips = _chips(db, res.id)
        assert len(chips) == 1
        assert chips[0].date == res.check_in_date

    def test_last_night_skipped(self, db):
        """다박: D1=동급, D2=업. promise 는 D1 (첫박) 만 봄 → 칩 없음.
        D2 (마지막박) 업그레이드는 review 가 처리할 영역.
        """
        _setup_schedule(db)
        b = _make_building(db)
        room_d1 = _make_room(db, b.id, room_number="D1_SAME", grade=2)
        room_d2 = _make_room(db, b.id, room_number="D2_HIGH", grade=5)
        item = _make_biz_item(db, grade=2)
        res = _make_reservation(
            db,
            biz_item_id=item.biz_item_id,
            party_size=2,
            check_in="2026-04-10",
            check_out="2026-04-12",
        )
        _make_assignment(db, res.id, room_d1.id, date="2026-04-10")
        _make_assignment(db, res.id, room_d2.id, date="2026-04-11")

        for d in ["2026-04-10", "2026-04-11"]:
            reconcile_room_upgrade_promise(db, res.id, d)
        assert _chips(db, res.id) == []

    def test_first_night_upgrade_other_nights_skip(self, db):
        """다박: D1=업, D2=동급. promise 는 D1 에만 칩 1개."""
        _setup_schedule(db)
        b = _make_building(db)
        room_d1 = _make_room(db, b.id, room_number="D1_HIGH", grade=5)
        room_d2 = _make_room(db, b.id, room_number="D2_SAME", grade=2)
        item = _make_biz_item(db, grade=2)
        res = _make_reservation(
            db,
            biz_item_id=item.biz_item_id,
            party_size=2,
            check_in="2026-04-10",
            check_out="2026-04-12",
        )
        _make_assignment(db, res.id, room_d1.id, date="2026-04-10")
        _make_assignment(db, res.id, room_d2.id, date="2026-04-11")

        for d in ["2026-04-10", "2026-04-11"]:
            reconcile_room_upgrade_promise(db, res.id, d)
        chips = _chips(db, res.id)
        assert len(chips) == 1
        assert chips[0].date == "2026-04-10"

    def test_no_schedule_no_chip_no_critical(self, db):
        b = _make_building(db)
        room = _make_room(db, b.id, grade=3)
        item = _make_biz_item(db, grade=2)
        res = _make_reservation(db, biz_item_id=item.biz_item_id, party_size=2)
        _make_assignment(db, res.id, room.id, date=res.check_in_date)
        # 스케줄 안 만듦
        reconcile_room_upgrade_promise(db, res.id, res.check_in_date)
        assert _chips(db, res.id) == []

    def test_inactive_schedule_no_chip(self, db):
        _setup_schedule(db, active=False)
        b = _make_building(db)
        room = _make_room(db, b.id, grade=3)
        item = _make_biz_item(db, grade=2)
        res = _make_reservation(db, biz_item_id=item.biz_item_id, party_size=2)
        _make_assignment(db, res.id, room.id, date=res.check_in_date)
        reconcile_room_upgrade_promise(db, res.id, res.check_in_date)
        assert _chips(db, res.id) == []

    def test_idempotent(self, db):
        _setup_schedule(db)
        b = _make_building(db)
        room = _make_room(db, b.id, grade=3)
        item = _make_biz_item(db, grade=2)
        res = _make_reservation(db, biz_item_id=item.biz_item_id, party_size=2)
        _make_assignment(db, res.id, room.id, date=res.check_in_date)
        reconcile_room_upgrade_promise(db, res.id, res.check_in_date)
        reconcile_room_upgrade_promise(db, res.id, res.check_in_date)
        assert len(_chips(db, res.id, res.check_in_date)) == 1


class TestPromiseAndReviewCoexist:
    """약속 + 객후 두 schedule 이 같은 stay 에 칩 1개씩 — 각자 독립."""

    def test_both_chips_in_same_stay(self, db):
        """다박 D1=업, D2=업. promise 첫박 칩 + review 마지막박 칩 둘 다 생성.

        예약 더블(2), D1=스위트(5), D2=트윈(3), check_out=2026-04-12.
        last_night = 2026-04-11.
        promise → D1 (2026-04-10) 칩.
        review  → D2 (2026-04-11) 칩.
        """
        # promise schedule
        _setup_schedule(db)

        # review schedule + template (별도 template_key)
        from app.services.room_upgrade_review import ROOM_UPGRADE_REVIEW
        rv_tpl = MessageTemplate(
            tenant_id=1, template_key="rv_review", name="객후",
            content="후기 요청", is_active=True,
        )
        db.add(rv_tpl)
        db.flush()
        rv_sched = TemplateSchedule(
            tenant_id=1, template_id=rv_tpl.id,
            schedule_name="객후 스케줄",
            schedule_type="daily", hour=12, minute=30,
            schedule_category="custom_schedule",
            custom_type=ROOM_UPGRADE_REVIEW,
            target_mode="last_night",
            is_active=True,
        )
        db.add(rv_sched)
        db.flush()

        b = _make_building(db)
        room_d1 = _make_room(db, b.id, room_number="D1", grade=5)
        room_d2 = _make_room(db, b.id, room_number="D2", grade=3)
        item = _make_biz_item(db, grade=2)
        res = _make_reservation(
            db,
            biz_item_id=item.biz_item_id,
            party_size=2,
            check_in="2026-04-10",
            check_out="2026-04-12",
        )
        _make_assignment(db, res.id, room_d1.id, date="2026-04-10")
        _make_assignment(db, res.id, room_d2.id, date="2026-04-11")

        from app.services.room_upgrade_review import reconcile_room_upgrade_review
        for d in ["2026-04-10", "2026-04-11"]:
            reconcile_room_upgrade_promise(db, res.id, d)
            reconcile_room_upgrade_review(db, res.id, d)

        promise_chips = _chips(db, res.id)  # TPL_KEY = promise
        rv_chips = db.query(ReservationSmsAssignment).filter(
            ReservationSmsAssignment.reservation_id == res.id,
            ReservationSmsAssignment.template_key == "rv_review",
        ).all()
        assert len(promise_chips) == 1
        assert promise_chips[0].date == "2026-04-10"
        assert len(rv_chips) == 1
        assert rv_chips[0].date == "2026-04-11"


class TestDeleteAll:
    def test_delete_all_chips(self, db):
        _setup_schedule(db)
        b = _make_building(db)
        room = _make_room(db, b.id, grade=3)
        item = _make_biz_item(db, grade=2)
        res = _make_reservation(db, biz_item_id=item.biz_item_id, party_size=2)
        _make_assignment(db, res.id, room.id, date=res.check_in_date)

        reconcile_room_upgrade_promise(db, res.id, res.check_in_date)
        assert len(_chips(db, res.id)) == 1

        _delete_all_room_upgrade_promise_chips(db, res.id, res.check_in_date)
        assert _chips(db, res.id) == []


class TestBatch:
    def test_batch_no_schedule_no_op(self, db):
        b = _make_building(db)
        room = _make_room(db, b.id, grade=3)
        item = _make_biz_item(db, grade=2)
        res = _make_reservation(db, biz_item_id=item.biz_item_id, party_size=2)
        _make_assignment(db, res.id, room.id, date=res.check_in_date)
        reconcile_room_upgrade_promise_batch(db, [res.id], res.check_in_date)
        assert _chips(db, res.id) == []

    def test_batch_processes_multiple(self, db):
        _setup_schedule(db)
        b = _make_building(db)
        room1 = _make_room(db, b.id, room_number="A", grade=3)
        room2 = _make_room(db, b.id, room_number="B", grade=3)
        item = _make_biz_item(db, grade=2)
        res1 = _make_reservation(db, biz_item_id=item.biz_item_id, party_size=2)
        res2 = _make_reservation(db, biz_item_id=item.biz_item_id, party_size=2)
        _make_assignment(db, res1.id, room1.id, date=res1.check_in_date)
        _make_assignment(db, res2.id, room2.id, date=res2.check_in_date)

        reconcile_room_upgrade_promise_batch(db, [res1.id, res2.id], res1.check_in_date)
        assert len(_chips(db, res1.id)) == 1
        assert len(_chips(db, res2.id)) == 1

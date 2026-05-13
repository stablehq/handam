"""room_upgrade_review.py 통합 테스트 — in-memory SQLite.

객후 (무료 업그레이드 후기 안내) 칩 자동 발생/삭제 검증.
도메인 룰:
  - 배정 객실 등급 > 예약 상품 등급 AND 인원 미초과 → 칩 발송 대상
  - 인원 초과 → skip (surcharge 영역)
  - 등급 NULL → grade_missing critical + skip
  - stay 당 1칩 (다박 박일별 row 복수 생성 방지)
  - 스케줄 비활성/미존재 → reconcile 즉시 return (critical diag 미발화)
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
from app.services.room_upgrade_review import (
    ROOM_UPGRADE_REVIEW,
    decide_chip,
    reconcile_room_upgrade_review,
    reconcile_room_upgrade_review_batch,
    _delete_all_room_upgrade_review_chips,
)


DATE = "2026-04-15"
TPL_KEY = "room_upgrade_review_msg"


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
    db,
    biz_item_id="BIZ-1",
    party_size=2,
    check_in=DATE,
    check_out="2026-04-16",
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
        name="객후",
        content="무료 업그레이드 안내",
        is_active=True,
    )
    db.add(t)
    db.flush()
    return t


def _make_schedule(db, template, active=True):
    s = TemplateSchedule(
        tenant_id=1,
        template_id=template.id,
        schedule_name="객후 스케줄",
        schedule_type="daily",
        hour=13,
        minute=30,
        schedule_category="custom_schedule",
        custom_type=ROOM_UPGRADE_REVIEW,
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
    def test_upgrade_no_overcapacity(self, db):
        """더블(2) 예약 → 트윈(3) 배정, 인원 2명 → True."""
        b = _make_building(db)
        room = _make_room(db, b.id, room_number="T", grade=3, base_capacity=3)
        item = _make_biz_item(db, biz_item_id="BIZ-D", grade=2, default_capacity=2)
        res = _make_reservation(db, biz_item_id=item.biz_item_id, party_size=2)
        _make_assignment(db, res.id, room.id)

        assert decide_chip(db, res, DATE) is True

    def test_same_grade_returns_false(self, db):
        """더블(2) → 더블(2) → False."""
        b = _make_building(db)
        room = _make_room(db, b.id, grade=2)
        item = _make_biz_item(db, grade=2)
        res = _make_reservation(db, biz_item_id=item.biz_item_id, party_size=2)
        _make_assignment(db, res.id, room.id)

        assert decide_chip(db, res, DATE) is False

    def test_downgrade_returns_false(self, db):
        """트윈(3) → 더블(2) → False (다운그레이드)."""
        b = _make_building(db)
        room = _make_room(db, b.id, grade=2)
        item = _make_biz_item(db, grade=3)
        res = _make_reservation(db, biz_item_id=item.biz_item_id, party_size=2)
        _make_assignment(db, res.id, room.id)

        assert decide_chip(db, res, DATE) is False

    def test_overcapacity_returns_false(self, db):
        """더블(2, default_capacity=2) → 스위트(5), 인원 3 → 인원 초과 → False (surcharge 영역)."""
        b = _make_building(db)
        room = _make_room(db, b.id, grade=5, base_capacity=4)
        item = _make_biz_item(db, grade=2, default_capacity=2)
        res = _make_reservation(db, biz_item_id=item.biz_item_id, party_size=3)
        _make_assignment(db, res.id, room.id)

        assert decide_chip(db, res, DATE) is False

    def test_room_grade_null_returns_false(self, db):
        """Room.grade NULL → grade_missing → False."""
        b = _make_building(db)
        room = _make_room(db, b.id, grade=None)
        item = _make_biz_item(db, grade=2)
        res = _make_reservation(db, biz_item_id=item.biz_item_id, party_size=2)
        _make_assignment(db, res.id, room.id)

        assert decide_chip(db, res, DATE) is False

    def test_biz_item_grade_null_returns_false(self, db):
        """NaverBizItem.grade NULL → grade_missing → False."""
        b = _make_building(db)
        room = _make_room(db, b.id, grade=3)
        item = _make_biz_item(db, grade=None)
        res = _make_reservation(db, biz_item_id=item.biz_item_id, party_size=2)
        _make_assignment(db, res.id, room.id)

        assert decide_chip(db, res, DATE) is False

    def test_no_assignment_returns_false(self, db):
        """RoomAssignment 없음 → False."""
        b = _make_building(db)
        _make_room(db, b.id, grade=3)
        item = _make_biz_item(db, grade=2)
        res = _make_reservation(db, biz_item_id=item.biz_item_id, party_size=2)
        # 의도적으로 RoomAssignment 안 만듦

        assert decide_chip(db, res, DATE) is False

    def test_biz_item_id_null_returns_false(self, db):
        """biz_item_id NULL (수동 예약) → grade_missing → False."""
        b = _make_building(db)
        room = _make_room(db, b.id, grade=3)
        _make_biz_item(db, grade=2)
        res = _make_reservation(db, biz_item_id=None, party_size=2)
        _make_assignment(db, res.id, room.id)

        assert decide_chip(db, res, DATE) is False

    def test_dormitory_to_double_upgrade(self, db):
        """도미(1) → 더블(2) 무료 업그레이드 → True (도미 면제 가드 없음)."""
        b = _make_building(db)
        room = _make_room(db, b.id, grade=2)
        item = _make_biz_item(db, grade=1, default_capacity=1)
        res = _make_reservation(db, biz_item_id=item.biz_item_id, party_size=1)
        _make_assignment(db, res.id, room.id)

        assert decide_chip(db, res, DATE) is True


class TestReconcile:
    def test_upgrade_creates_chip(self, db):
        _setup_schedule(db)
        b = _make_building(db)
        room = _make_room(db, b.id, grade=3)
        item = _make_biz_item(db, grade=2)
        res = _make_reservation(db, biz_item_id=item.biz_item_id, party_size=2)
        _make_assignment(db, res.id, room.id)

        reconcile_room_upgrade_review(db, res.id, DATE)
        chips = _chips(db, res.id, DATE)
        assert len(chips) == 1
        assert chips[0].sent_at is None

    def test_same_grade_no_chip(self, db):
        _setup_schedule(db)
        b = _make_building(db)
        room = _make_room(db, b.id, grade=2)
        item = _make_biz_item(db, grade=2)
        res = _make_reservation(db, biz_item_id=item.biz_item_id, party_size=2)
        _make_assignment(db, res.id, room.id)

        reconcile_room_upgrade_review(db, res.id, DATE)
        assert _chips(db, res.id) == []

    def test_idempotent(self, db):
        """같은 reconcile 을 2번 호출해도 칩 1개만."""
        _setup_schedule(db)
        b = _make_building(db)
        room = _make_room(db, b.id, grade=3)
        item = _make_biz_item(db, grade=2)
        res = _make_reservation(db, biz_item_id=item.biz_item_id, party_size=2)
        _make_assignment(db, res.id, room.id)

        reconcile_room_upgrade_review(db, res.id, DATE)
        reconcile_room_upgrade_review(db, res.id, DATE)
        assert len(_chips(db, res.id, DATE)) == 1

    def test_no_schedule_no_chip_no_critical(self, db):
        """스케줄 미존재 → reconcile 호출해도 no-op. decide_chip 도 호출 안 됨."""
        # 스케줄 일부러 만들지 않음
        b = _make_building(db)
        room = _make_room(db, b.id, grade=3)
        item = _make_biz_item(db, grade=2)
        res = _make_reservation(db, biz_item_id=item.biz_item_id, party_size=2)
        _make_assignment(db, res.id, room.id)

        # 예외 없이 통과해야 함 (진입 가드)
        reconcile_room_upgrade_review(db, res.id, DATE)
        assert _chips(db, res.id) == []

    def test_inactive_schedule_no_chip(self, db):
        """스케줄 비활성 → reconcile 호출해도 칩 없음."""
        _setup_schedule(db, active=False)
        b = _make_building(db)
        room = _make_room(db, b.id, grade=3)
        item = _make_biz_item(db, grade=2)
        res = _make_reservation(db, biz_item_id=item.biz_item_id, party_size=2)
        _make_assignment(db, res.id, room.id)

        reconcile_room_upgrade_review(db, res.id, DATE)
        assert _chips(db, res.id) == []

    def test_decide_false_deletes_unsent_chip(self, db):
        """이미 미발송 칩이 있고 decide_chip == False 가 되면 삭제."""
        _setup_schedule(db)
        b = _make_building(db)
        room_high = _make_room(db, b.id, room_number="HIGH", grade=3)
        room_same = _make_room(db, b.id, room_number="SAME", grade=2)
        item = _make_biz_item(db, grade=2)
        res = _make_reservation(db, biz_item_id=item.biz_item_id, party_size=2)
        _make_assignment(db, res.id, room_high.id)

        # 1) 업그레이드 칩 생성
        reconcile_room_upgrade_review(db, res.id, DATE)
        assert len(_chips(db, res.id, DATE)) == 1

        # 2) 같은 등급으로 재배정 (assignment 갱신)
        ra = db.query(RoomAssignment).filter(
            RoomAssignment.reservation_id == res.id,
            RoomAssignment.date == DATE,
        ).first()
        ra.room_id = room_same.id
        db.flush()

        # 3) reconcile → 미발송 칩 삭제
        reconcile_room_upgrade_review(db, res.id, DATE)
        assert _chips(db, res.id, DATE) == []

    def test_sent_chip_not_deleted(self, db):
        """sent 칩은 reconcile 에서 삭제 안 됨 (이미 발송된 SMS)."""
        _setup_schedule(db)
        b = _make_building(db)
        room_high = _make_room(db, b.id, room_number="HIGH", grade=3)
        room_same = _make_room(db, b.id, room_number="SAME", grade=2)
        item = _make_biz_item(db, grade=2)
        res = _make_reservation(db, biz_item_id=item.biz_item_id, party_size=2)
        _make_assignment(db, res.id, room_high.id)

        # 1) 칩 생성 + 발송 처리
        reconcile_room_upgrade_review(db, res.id, DATE)
        chip = _chips(db, res.id, DATE)[0]
        chip.sent_at = datetime.now(timezone.utc)
        db.flush()

        # 2) 등급 다운그레이드 후 reconcile → sent 칩 보존
        ra = db.query(RoomAssignment).filter(
            RoomAssignment.reservation_id == res.id,
            RoomAssignment.date == DATE,
        ).first()
        ra.room_id = room_same.id
        db.flush()
        reconcile_room_upgrade_review(db, res.id, DATE)
        assert len(_chips(db, res.id, DATE)) == 1


class TestStayDedup:
    def test_multinight_only_one_chip(self, db):
        """다박 D1=더블(2)/D2=스위트(5)/D3=트윈(3), 예약 상품=더블(2).
        D1 동급 → 칩 없음. D2 업그레이드 → 칩 1개. D3 reconcile → stay 1칩 가드로 skip.
        """
        _setup_schedule(db)
        b = _make_building(db)
        room_d1 = _make_room(db, b.id, room_number="D1", grade=2)  # 더블
        room_d2 = _make_room(db, b.id, room_number="D2", grade=5)  # 스위트
        room_d3 = _make_room(db, b.id, room_number="D3", grade=3)  # 트윈
        item = _make_biz_item(db, grade=2)
        res = _make_reservation(
            db,
            biz_item_id=item.biz_item_id,
            party_size=2,
            check_in="2026-04-10",
            check_out="2026-04-13",
        )
        _make_assignment(db, res.id, room_d1.id, date="2026-04-10")
        _make_assignment(db, res.id, room_d2.id, date="2026-04-11")
        _make_assignment(db, res.id, room_d3.id, date="2026-04-12")

        # 각 박일에 reconcile 호출 (실제 호출 패턴 모사)
        for d in ["2026-04-10", "2026-04-11", "2026-04-12"]:
            reconcile_room_upgrade_review(db, res.id, d)

        # stay 전체에 칩 1개만
        chips = _chips(db, res.id)
        assert len(chips) == 1
        # D2 (첫 업그레이드 박일) 에 생성됨 — D1 이 동급이라 skip 됐기 때문
        assert chips[0].date == "2026-04-11"

    def test_existing_sent_chip_blocks_new(self, db):
        """stay 내 sent 칩이 있으면 다른 박일도 추가 생성 skip."""
        _setup_schedule(db)
        b = _make_building(db)
        room_d1 = _make_room(db, b.id, room_number="D1", grade=3)
        room_d2 = _make_room(db, b.id, room_number="D2", grade=5)
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

        # D1 칩 생성 + 발송 처리
        reconcile_room_upgrade_review(db, res.id, "2026-04-10")
        chip = _chips(db, res.id)[0]
        chip.sent_at = datetime.now(timezone.utc)
        db.flush()

        # D2 reconcile → sent 칩 있어서 추가 생성 안 됨
        reconcile_room_upgrade_review(db, res.id, "2026-04-11")
        chips = _chips(db, res.id)
        assert len(chips) == 1
        assert chips[0].date == "2026-04-10"


class TestSurchargeIndependence:
    """객후는 surcharge 칩 상태와 무관 (B안 핵심 검증)."""

    def _make_surcharge_chip(self, db, res_id, date, sent_at=None):
        """발송된/미발송 surcharge 칩 생성 (테스트 더블)."""
        tpl = MessageTemplate(
            tenant_id=1, template_key=f"add_standard", name="추가요금",
            content="추가요금", is_active=True,
        )
        db.add(tpl)
        db.flush()
        sched = TemplateSchedule(
            tenant_id=1, template_id=tpl.id,
            schedule_name="surcharge",
            schedule_type="daily", hour=13, minute=30,
            schedule_category="custom_schedule",
            custom_type="surcharge_standard", is_active=True,
        )
        db.add(sched)
        db.flush()
        chip = ReservationSmsAssignment(
            tenant_id=1, reservation_id=res_id,
            template_key=tpl.template_key, date=date,
            assigned_by="auto", schedule_id=sched.id, sent_at=sent_at,
        )
        db.add(chip)
        db.flush()

    def test_unsent_surcharge_does_not_block(self, db):
        """surcharge 미발송 칩 존재 + 인원 미초과 + 등급 업 → 객후 발송."""
        _setup_schedule(db)
        b = _make_building(db)
        room = _make_room(db, b.id, grade=3)
        item = _make_biz_item(db, grade=2)
        res = _make_reservation(db, biz_item_id=item.biz_item_id, party_size=2)
        _make_assignment(db, res.id, room.id)

        self._make_surcharge_chip(db, res.id, DATE, sent_at=None)

        reconcile_room_upgrade_review(db, res.id, DATE)
        chips = _chips(db, res.id, DATE)
        assert len(chips) == 1

    def test_sent_surcharge_does_not_block(self, db):
        """surcharge sent 칩 존재 + 인원 미초과 + 등급 업 → 객후 발송."""
        _setup_schedule(db)
        b = _make_building(db)
        room = _make_room(db, b.id, grade=3)
        item = _make_biz_item(db, grade=2)
        res = _make_reservation(db, biz_item_id=item.biz_item_id, party_size=2)
        _make_assignment(db, res.id, room.id)

        self._make_surcharge_chip(db, res.id, DATE, sent_at=datetime.now(timezone.utc))

        reconcile_room_upgrade_review(db, res.id, DATE)
        chips = _chips(db, res.id, DATE)
        assert len(chips) == 1


class TestDeleteAll:
    def test_delete_all_chips(self, db):
        """_delete_all_room_upgrade_review_chips → 미발송 칩 삭제 (sent 보존)."""
        _setup_schedule(db)
        b = _make_building(db)
        room = _make_room(db, b.id, grade=3)
        item = _make_biz_item(db, grade=2)
        res = _make_reservation(db, biz_item_id=item.biz_item_id, party_size=2)
        _make_assignment(db, res.id, room.id)

        reconcile_room_upgrade_review(db, res.id, DATE)
        assert len(_chips(db, res.id, DATE)) == 1

        _delete_all_room_upgrade_review_chips(db, res.id, DATE)
        assert _chips(db, res.id, DATE) == []


class TestBatch:
    def test_batch_no_schedule_no_op(self, db):
        """스케줄 없을 때 batch 호출 → no-op (예외 없음)."""
        b = _make_building(db)
        room = _make_room(db, b.id, grade=3)
        item = _make_biz_item(db, grade=2)
        res = _make_reservation(db, biz_item_id=item.biz_item_id, party_size=2)
        _make_assignment(db, res.id, room.id)

        reconcile_room_upgrade_review_batch(db, [res.id], DATE)
        assert _chips(db, res.id) == []

    def test_batch_processes_multiple(self, db):
        _setup_schedule(db)
        b = _make_building(db)
        room1 = _make_room(db, b.id, room_number="A", grade=3)
        room2 = _make_room(db, b.id, room_number="B", grade=3)
        item = _make_biz_item(db, grade=2)
        res1 = _make_reservation(db, biz_item_id=item.biz_item_id, party_size=2)
        res2 = _make_reservation(db, biz_item_id=item.biz_item_id, party_size=2)
        _make_assignment(db, res1.id, room1.id)
        _make_assignment(db, res2.id, room2.id)

        reconcile_room_upgrade_review_batch(db, [res1.id, res2.id], DATE)
        assert len(_chips(db, res1.id, DATE)) == 1
        assert len(_chips(db, res2.id, DATE)) == 1

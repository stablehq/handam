"""chip_store.py PR1 동작 검증 — ensure_chip / remove_chip.

검증 핵심:
  1. ensure_chip 의 idempotent 동작 (race 안전)
  2. remove_chip 의 보호 가드 비대칭 해결:
     - force=False: sent_at IS NULL AND assigned_by NOT IN ('manual','excluded','failed')
     - force=True: 무조건 삭제 (cancel/delete cascade)
  3. OQ-3 가드 키 분기: schedule_id 우선 + template_key fallback

참고: docs/plans/chip-store-migration-plan.md
"""
from datetime import datetime, timezone

from app.db.models import (
    MessageTemplate,
    Reservation,
    ReservationSmsAssignment,
    ReservationStatus,
    TemplateSchedule,
)
from app.services.chip_store import (
    ensure_chip,
    remove_chip,
    delete_chips_for_reservation,
    delete_chips_for_schedule,
    record_sent,
    record_failed,
    PROTECTED_ASSIGNED_BY,
)


# ════════════════════════════════════════════════════════════════════
# 헬퍼
# ════════════════════════════════════════════════════════════════════

def _make_template(db, key="checkin_guide"):
    t = MessageTemplate(
        tenant_id=1,
        template_key=key,
        name=key,
        content="content",
        is_active=True,
    )
    db.add(t)
    db.flush()
    return t


def _make_schedule(db, template):
    s = TemplateSchedule(
        tenant_id=1,
        template_id=template.id,
        schedule_name=template.template_key,
        schedule_type="daily",
        hour=10,
        minute=0,
    )
    db.add(s)
    db.flush()
    return s


def _make_reservation(db, *, check_in="2026-04-20", check_out="2026-04-22"):
    r = Reservation(
        tenant_id=1,
        customer_name="손님",
        phone="01012345678",
        check_in_date=check_in,
        check_out_date=check_out,
        check_in_time="15:00",
        status=ReservationStatus.CONFIRMED,
    )
    db.add(r)
    db.flush()
    return r


def _query_chip(db, *, reservation_id, template_key, date):
    return db.query(ReservationSmsAssignment).filter(
        ReservationSmsAssignment.reservation_id == reservation_id,
        ReservationSmsAssignment.template_key == template_key,
        ReservationSmsAssignment.date == date,
    ).first()


# ════════════════════════════════════════════════════════════════════
# ensure_chip
# ════════════════════════════════════════════════════════════════════

class TestEnsureChipCreation:
    def test_creates_new_chip(self, db):
        r = _make_reservation(db)
        chip = ensure_chip(
            db,
            reservation_id=r.id,
            template_key="checkin_guide",
            date="2026-04-20",
        )
        assert chip is not None
        assert chip.reservation_id == r.id
        assert chip.template_key == "checkin_guide"
        assert chip.date == "2026-04-20"
        assert chip.assigned_by == "auto"  # default
        assert chip.schedule_id is None
        assert chip.tenant_id == 1  # ContextVar 자동 주입

    def test_passes_schedule_id_and_assigned_by(self, db):
        r = _make_reservation(db)
        t = _make_template(db)
        s = _make_schedule(db, t)
        chip = ensure_chip(
            db,
            reservation_id=r.id,
            template_key="checkin_guide",
            date="2026-04-20",
            assigned_by="manual",
            schedule_id=s.id,
        )
        assert chip.assigned_by == "manual"
        assert chip.schedule_id == s.id


class TestEnsureChipIdempotent:
    def test_returns_existing_on_duplicate_call(self, db):
        r = _make_reservation(db)
        first = ensure_chip(
            db,
            reservation_id=r.id,
            template_key="checkin_guide",
            date="2026-04-20",
        )
        second = ensure_chip(
            db,
            reservation_id=r.id,
            template_key="checkin_guide",
            date="2026-04-20",
        )
        # 같은 row 리턴 — 신규 생성 안 됨
        assert second.id == first.id
        # DB 에 row 1개만
        count = db.query(ReservationSmsAssignment).filter(
            ReservationSmsAssignment.reservation_id == r.id,
        ).count()
        assert count == 1

    def test_ignores_extra_args_on_existing(self, db):
        """이미 있는 칩에 다른 assigned_by 요청해도 기존 그대로 반환."""
        r = _make_reservation(db)
        first = ensure_chip(
            db,
            reservation_id=r.id,
            template_key="k",
            date="2026-04-20",
            assigned_by="auto",
        )
        second = ensure_chip(
            db,
            reservation_id=r.id,
            template_key="k",
            date="2026-04-20",
            assigned_by="manual",  # 기존 칩의 assigned_by 갱신 안 됨
        )
        assert second.id == first.id
        assert second.assigned_by == "auto"  # 기존 값 유지


# ════════════════════════════════════════════════════════════════════
# remove_chip — 보호 가드 (PR1 의 핵심 가치)
# ════════════════════════════════════════════════════════════════════

class TestRemoveChipForceFalse:
    """force=False — 자동 reconcile 사이클용. manual/excluded/failed 보호."""

    def test_deletes_auto_chip(self, db):
        r = _make_reservation(db)
        ensure_chip(
            db, reservation_id=r.id, template_key="k",
            date="2026-04-20", assigned_by="auto",
        )
        deleted = remove_chip(
            db, reservation_id=r.id, template_key="k", date="2026-04-20",
        )
        assert deleted == 1
        assert _query_chip(db, reservation_id=r.id, template_key="k", date="2026-04-20") is None

    def test_protects_manual_chip(self, db):
        """⭐ OQ-1 핵심 — 운영자 수동 칩이 자동 reconcile 에서 보호됨."""
        r = _make_reservation(db)
        ensure_chip(
            db, reservation_id=r.id, template_key="k",
            date="2026-04-20", assigned_by="manual",
        )
        deleted = remove_chip(
            db, reservation_id=r.id, template_key="k", date="2026-04-20",
        )
        assert deleted == 0
        assert _query_chip(db, reservation_id=r.id, template_key="k", date="2026-04-20") is not None

    def test_protects_excluded_chip(self, db):
        r = _make_reservation(db)
        ensure_chip(
            db, reservation_id=r.id, template_key="k",
            date="2026-04-20", assigned_by="excluded",
        )
        deleted = remove_chip(
            db, reservation_id=r.id, template_key="k", date="2026-04-20",
        )
        assert deleted == 0

    def test_protects_failed_chip(self, db):
        """⭐ OQ-5 — failed 칩 영구 보호."""
        r = _make_reservation(db)
        ensure_chip(
            db, reservation_id=r.id, template_key="k",
            date="2026-04-20", assigned_by="failed",
        )
        deleted = remove_chip(
            db, reservation_id=r.id, template_key="k", date="2026-04-20",
        )
        assert deleted == 0

    def test_protects_already_sent_chip(self, db):
        """sent_at IS NOT NULL 칩 보호."""
        r = _make_reservation(db)
        chip = ensure_chip(
            db, reservation_id=r.id, template_key="k",
            date="2026-04-20", assigned_by="auto",
        )
        chip.sent_at = datetime.now(timezone.utc)
        db.flush()
        deleted = remove_chip(
            db, reservation_id=r.id, template_key="k", date="2026-04-20",
        )
        assert deleted == 0

    def test_protects_legacy_failed_send_status(self, db):
        """⭐ PR7 호환 — 옛 데이터 assigned_by='auto' + send_status='failed' 보호.

        PR4 (OQ-5) 이전에는 record_sms_failed 가 assigned_by 갱신 안 함.
        그런 옛 칩이 자동 reconcile 사이클에서 삭제 안 되도록 추가 가드.
        """
        r = _make_reservation(db)
        chip = ensure_chip(
            db, reservation_id=r.id, template_key="k",
            date="2026-04-20", assigned_by="auto",
        )
        chip.send_status = 'failed'
        chip.send_error = 'legacy phone error'
        db.flush()
        deleted = remove_chip(
            db, reservation_id=r.id, template_key="k", date="2026-04-20",
        )
        assert deleted == 0  # 보호됨!


class TestRemoveChipForceTrue:
    """force=True — cancel/delete cascade. 가드 우회."""

    def test_force_deletes_manual_chip(self, db):
        """⭐ OQ-2-a/2-b — 예약 취소·삭제 시 manual 도 cascade."""
        r = _make_reservation(db)
        ensure_chip(
            db, reservation_id=r.id, template_key="k",
            date="2026-04-20", assigned_by="manual",
        )
        deleted = remove_chip(
            db, reservation_id=r.id, template_key="k", date="2026-04-20",
            force=True,
        )
        assert deleted == 1

    def test_force_keeps_sent_by_default(self, db):
        """⭐ PR9 — force=True 의 기본은 protect_sent=True (sent 보존)."""
        r = _make_reservation(db)
        chip = ensure_chip(
            db, reservation_id=r.id, template_key="k",
            date="2026-04-20", assigned_by="auto",
        )
        chip.sent_at = datetime.now(timezone.utc)
        db.flush()
        deleted = remove_chip(
            db, reservation_id=r.id, template_key="k", date="2026-04-20",
            force=True,  # protect_sent=True (default)
        )
        assert deleted == 0  # sent 보호

    def test_force_with_protect_sent_false_deletes_sent(self, db):
        """⭐ PR9 — protect_sent=False 명시 시만 sent cascade (on_reservation_deleted)."""
        r = _make_reservation(db)
        chip = ensure_chip(
            db, reservation_id=r.id, template_key="k",
            date="2026-04-20", assigned_by="auto",
        )
        chip.sent_at = datetime.now(timezone.utc)
        db.flush()
        deleted = remove_chip(
            db, reservation_id=r.id, template_key="k", date="2026-04-20",
            force=True, protect_sent=False,
        )
        assert deleted == 1


class TestRemoveChipScheduleIdMatching:
    """⭐ OQ-3 — schedule_id 우선 + template_key fallback."""

    def test_schedule_id_matches_specific_schedule(self, db):
        """같은 (res, template_key, date) 면 schedule_id 로만 식별."""
        r = _make_reservation(db)
        t = _make_template(db)
        s1 = _make_schedule(db, t)
        # 같은 date+template_key 에 schedule_id=s1 칩 1개만 생성 (uq 제약)
        ensure_chip(
            db, reservation_id=r.id, template_key="k",
            date="2026-04-20", schedule_id=s1.id, assigned_by="auto",
        )
        # schedule_id=s1 매칭으로 삭제 → 정확히 1개
        deleted = remove_chip(
            db, reservation_id=r.id, template_key="k", date="2026-04-20",
            schedule_id=s1.id,
        )
        assert deleted == 1

    def test_schedule_id_skips_different_schedule(self, db):
        r = _make_reservation(db)
        t = _make_template(db)
        s1 = _make_schedule(db, t)
        s2 = _make_schedule(db, t)
        # schedule_id=s1 의 칩만 존재
        ensure_chip(
            db, reservation_id=r.id, template_key="k",
            date="2026-04-20", schedule_id=s1.id, assigned_by="auto",
        )
        # schedule_id=s2 로 remove 시도 → 매칭 안 됨
        deleted = remove_chip(
            db, reservation_id=r.id, template_key="k", date="2026-04-20",
            schedule_id=s2.id,
        )
        assert deleted == 0
        # 원본 칩은 그대로
        assert _query_chip(db, reservation_id=r.id, template_key="k", date="2026-04-20") is not None

    def test_schedule_id_none_matches_only_null(self, db):
        """schedule_id 가 None 이면 schedule_id IS NULL 칩만 매칭 (운영자 수동)."""
        r = _make_reservation(db)
        t = _make_template(db)
        s = _make_schedule(db, t)
        # schedule_id 있는 칩 (스케줄러 생성)
        ensure_chip(
            db, reservation_id=r.id, template_key="k",
            date="2026-04-20", schedule_id=s.id, assigned_by="auto",
        )
        # remove_chip(schedule_id=None, template_key="k") → schedule_id IS NULL 만 매칭 → 0
        deleted = remove_chip(
            db, reservation_id=r.id, template_key="k", date="2026-04-20",
            schedule_id=None,
        )
        assert deleted == 0


class TestRemoveChipReturnsZero:
    def test_nonexistent_chip(self, db):
        r = _make_reservation(db)
        deleted = remove_chip(
            db, reservation_id=r.id, template_key="ghost", date="2026-04-20",
        )
        assert deleted == 0


# ════════════════════════════════════════════════════════════════════
# 상수
# ════════════════════════════════════════════════════════════════════

class TestProtectedAssignedBy:
    def test_constant_value(self):
        """OQ-1 + OQ-5 정책 반영."""
        assert PROTECTED_ASSIGNED_BY == ('manual', 'excluded', 'failed')


# ════════════════════════════════════════════════════════════════════
# delete_chips_for_reservation — PR2 단계 #4
# ════════════════════════════════════════════════════════════════════

class TestDeleteChipsForReservationAllOptions:
    """옵션 전부 None — 예약의 모든 칩 정리 (가드만 적용)."""

    def test_force_false_protects_manual_chips(self, db):
        """⭐ OQ-1 — 자동 reconcile 사이클에서 manual 칩 보호."""
        r = _make_reservation(db)
        ensure_chip(db, reservation_id=r.id, template_key="auto1", date="2026-04-20", assigned_by="auto")
        ensure_chip(db, reservation_id=r.id, template_key="manual1", date="2026-04-20", assigned_by="manual")
        ensure_chip(db, reservation_id=r.id, template_key="excluded1", date="2026-04-20", assigned_by="excluded")
        ensure_chip(db, reservation_id=r.id, template_key="failed1", date="2026-04-20", assigned_by="failed")
        # 자동 reconcile — auto 만 삭제
        deleted = delete_chips_for_reservation(db, reservation_id=r.id)
        assert deleted == 1
        # 나머지 3개 보존
        remaining = db.query(ReservationSmsAssignment).filter(
            ReservationSmsAssignment.reservation_id == r.id,
        ).count()
        assert remaining == 3

    def test_force_true_cascade_deletes_all(self, db):
        """⭐ OQ-2-a/2-b — cancel/delete cascade 시 manual 도 삭제."""
        r = _make_reservation(db)
        ensure_chip(db, reservation_id=r.id, template_key="auto1", date="2026-04-20", assigned_by="auto")
        ensure_chip(db, reservation_id=r.id, template_key="manual1", date="2026-04-20", assigned_by="manual")
        ensure_chip(db, reservation_id=r.id, template_key="failed1", date="2026-04-20", assigned_by="failed")
        deleted = delete_chips_for_reservation(db, reservation_id=r.id, force=True)
        assert deleted == 3
        remaining = db.query(ReservationSmsAssignment).filter(
            ReservationSmsAssignment.reservation_id == r.id,
        ).count()
        assert remaining == 0


class TestDeleteChipsForReservationByDates:
    def test_dates_filter_matches_only_specified(self, db):
        r = _make_reservation(db)
        ensure_chip(db, reservation_id=r.id, template_key="k", date="2026-04-20", assigned_by="auto")
        ensure_chip(db, reservation_id=r.id, template_key="k", date="2026-04-21", assigned_by="auto")
        ensure_chip(db, reservation_id=r.id, template_key="k", date="2026-04-22", assigned_by="auto")
        # 20, 22 만 삭제 (21 은 보존)
        deleted = delete_chips_for_reservation(
            db, reservation_id=r.id, dates=["2026-04-20", "2026-04-22"],
        )
        assert deleted == 2
        remaining_dates = [
            c.date for c in db.query(ReservationSmsAssignment).filter(
                ReservationSmsAssignment.reservation_id == r.id,
            ).all()
        ]
        assert remaining_dates == ["2026-04-21"]

    def test_empty_dates_list_treated_as_no_filter(self, db):
        """빈 리스트는 옵션 미적용 — 모든 날짜 매칭."""
        r = _make_reservation(db)
        ensure_chip(db, reservation_id=r.id, template_key="k", date="2026-04-20", assigned_by="auto")
        ensure_chip(db, reservation_id=r.id, template_key="k", date="2026-04-21", assigned_by="auto")
        deleted = delete_chips_for_reservation(db, reservation_id=r.id, dates=[])
        assert deleted == 2  # 빈 list → falsy → 필터 미적용


class TestDeleteChipsForReservationByScheduleIds:
    def test_schedule_ids_filter(self, db):
        r = _make_reservation(db)
        t = _make_template(db)
        s1 = _make_schedule(db, t)
        s2 = _make_schedule(db, t)
        ensure_chip(db, reservation_id=r.id, template_key="k1", date="2026-04-20", schedule_id=s1.id, assigned_by="auto")
        ensure_chip(db, reservation_id=r.id, template_key="k2", date="2026-04-20", schedule_id=s2.id, assigned_by="auto")
        # s1 만 삭제
        deleted = delete_chips_for_reservation(
            db, reservation_id=r.id, schedule_ids=[s1.id],
        )
        assert deleted == 1
        remaining = db.query(ReservationSmsAssignment).filter(
            ReservationSmsAssignment.reservation_id == r.id,
        ).all()
        assert len(remaining) == 1
        assert remaining[0].schedule_id == s2.id


class TestDeleteChipsForReservationCombined:
    def test_dates_and_schedule_ids_and_match(self, db):
        """dates AND schedule_ids 교집합 매칭."""
        r = _make_reservation(db)
        t = _make_template(db)
        s1 = _make_schedule(db, t)
        s2 = _make_schedule(db, t)
        # (D1, s1), (D1, s2), (D2, s1), (D2, s2) — 4개
        ensure_chip(db, reservation_id=r.id, template_key="k1", date="2026-04-20", schedule_id=s1.id, assigned_by="auto")
        ensure_chip(db, reservation_id=r.id, template_key="k2", date="2026-04-20", schedule_id=s2.id, assigned_by="auto")
        ensure_chip(db, reservation_id=r.id, template_key="k3", date="2026-04-21", schedule_id=s1.id, assigned_by="auto")
        ensure_chip(db, reservation_id=r.id, template_key="k4", date="2026-04-21", schedule_id=s2.id, assigned_by="auto")
        # (D1, s1) 만 삭제 (교집합)
        deleted = delete_chips_for_reservation(
            db, reservation_id=r.id, dates=["2026-04-20"], schedule_ids=[s1.id],
        )
        assert deleted == 1
        remaining = db.query(ReservationSmsAssignment).filter(
            ReservationSmsAssignment.reservation_id == r.id,
        ).count()
        assert remaining == 3


class TestDeleteChipsForReservationEdgeCases:
    def test_nonexistent_reservation_returns_zero(self, db):
        deleted = delete_chips_for_reservation(db, reservation_id=99999)
        assert deleted == 0


class TestDeleteChipsForReservationProtectSent:
    """⭐ PR9 — protect_sent 옵션 (OQ-2-a 정확 매핑)."""

    def test_force_with_protect_sent_keeps_sent_chips(self, db):
        """on_status_cancelled — force=True 라도 sent 보존."""
        r = _make_reservation(db)
        c1 = ensure_chip(db, reservation_id=r.id, template_key="manual_unsent",
                         date="2026-04-20", assigned_by="manual")
        c2 = ensure_chip(db, reservation_id=r.id, template_key="sent",
                         date="2026-04-20", assigned_by="auto")
        c2.sent_at = datetime.now(timezone.utc)
        db.flush()
        deleted = delete_chips_for_reservation(
            db, reservation_id=r.id, force=True, protect_sent=True,
        )
        assert deleted == 1  # manual unsent 만
        remaining = db.query(ReservationSmsAssignment).filter(
            ReservationSmsAssignment.reservation_id == r.id,
        ).all()
        assert len(remaining) == 1
        assert remaining[0].sent_at is not None  # sent 보존됨

    def test_force_with_protect_sent_false_deletes_all(self, db):
        """on_reservation_deleted — force=True + protect_sent=False cascade."""
        r = _make_reservation(db)
        ensure_chip(db, reservation_id=r.id, template_key="manual_unsent",
                    date="2026-04-20", assigned_by="manual")
        c2 = ensure_chip(db, reservation_id=r.id, template_key="sent",
                         date="2026-04-20", assigned_by="auto")
        c2.sent_at = datetime.now(timezone.utc)
        db.flush()
        deleted = delete_chips_for_reservation(
            db, reservation_id=r.id, force=True, protect_sent=False,
        )
        assert deleted == 2  # 전부


# ════════════════════════════════════════════════════════════════════
# delete_chips_for_schedule — PR2 단계 #5
# ════════════════════════════════════════════════════════════════════

class TestDeleteChipsForSchedule:
    def test_deletes_all_chips_for_schedule(self, db):
        r1 = _make_reservation(db)
        r2 = _make_reservation(db)
        t = _make_template(db)
        s = _make_schedule(db, t)
        ensure_chip(db, reservation_id=r1.id, template_key="k", date="2026-04-20", schedule_id=s.id, assigned_by="auto")
        ensure_chip(db, reservation_id=r2.id, template_key="k", date="2026-04-20", schedule_id=s.id, assigned_by="auto")
        deleted = delete_chips_for_schedule(db, schedule_id=s.id)
        assert deleted == 2

    def test_force_false_protects_manual(self, db):
        """⭐ template_schedules.py:518 와 동일 가드 (manual/excluded/failed 보호)."""
        r = _make_reservation(db)
        t = _make_template(db)
        s = _make_schedule(db, t)
        ensure_chip(db, reservation_id=r.id, template_key="k1", date="2026-04-20", schedule_id=s.id, assigned_by="auto")
        ensure_chip(db, reservation_id=r.id, template_key="k2", date="2026-04-20", schedule_id=s.id, assigned_by="manual")
        ensure_chip(db, reservation_id=r.id, template_key="k3", date="2026-04-20", schedule_id=s.id, assigned_by="failed")
        deleted = delete_chips_for_schedule(db, schedule_id=s.id)
        assert deleted == 1  # auto 만

    def test_force_true_deletes_all(self, db):
        r = _make_reservation(db)
        t = _make_template(db)
        s = _make_schedule(db, t)
        ensure_chip(db, reservation_id=r.id, template_key="k1", date="2026-04-20", schedule_id=s.id, assigned_by="auto")
        ensure_chip(db, reservation_id=r.id, template_key="k2", date="2026-04-20", schedule_id=s.id, assigned_by="manual")
        deleted = delete_chips_for_schedule(db, schedule_id=s.id, force=True)
        assert deleted == 2

    def test_does_not_match_other_schedules(self, db):
        r = _make_reservation(db)
        t = _make_template(db)
        s1 = _make_schedule(db, t)
        s2 = _make_schedule(db, t)
        ensure_chip(db, reservation_id=r.id, template_key="k1", date="2026-04-20", schedule_id=s1.id, assigned_by="auto")
        ensure_chip(db, reservation_id=r.id, template_key="k2", date="2026-04-20", schedule_id=s2.id, assigned_by="auto")
        deleted = delete_chips_for_schedule(db, schedule_id=s1.id)
        assert deleted == 1
        remaining = db.query(ReservationSmsAssignment).all()
        assert len(remaining) == 1
        assert remaining[0].schedule_id == s2.id

    def test_nonexistent_schedule_returns_zero(self, db):
        deleted = delete_chips_for_schedule(db, schedule_id=99999)
        assert deleted == 0

    def test_does_not_match_schedule_id_null_chips(self, db):
        """schedule_id=NULL 인 칩 (운영자 수동) 은 delete_chips_for_schedule 매칭 안 됨."""
        r = _make_reservation(db)
        t = _make_template(db)
        s = _make_schedule(db, t)
        # schedule_id 있는 칩
        ensure_chip(db, reservation_id=r.id, template_key="auto", date="2026-04-20", schedule_id=s.id, assigned_by="auto")
        # schedule_id NULL 칩 (운영자 수동)
        ensure_chip(db, reservation_id=r.id, template_key="manual_no_sched", date="2026-04-20", schedule_id=None, assigned_by="auto")
        deleted = delete_chips_for_schedule(db, schedule_id=s.id)
        assert deleted == 1  # schedule_id 있는 것만
        remaining = db.query(ReservationSmsAssignment).all()
        assert len(remaining) == 1
        assert remaining[0].schedule_id is None


# ════════════════════════════════════════════════════════════════════
# record_sent — PR3 단계 #6
# ════════════════════════════════════════════════════════════════════

class TestRecordSentNewChip:
    """OQ-4 — 칩 없을 시 신규 INSERT 정상 흐름 (이벤트 SMS / race)."""

    def test_creates_chip_when_none_exists(self, db):
        r = _make_reservation(db)
        chip = record_sent(
            db,
            reservation_id=r.id,
            template_key="event_sms",
            date="2026-04-20",
        )
        assert chip is not None
        assert chip.send_status == 'sent'
        assert chip.sent_at is not None
        assert chip.assigned_by == 'auto'  # default
        assert chip.tenant_id == 1

    def test_creates_chip_with_custom_assigned_by(self, db):
        r = _make_reservation(db)
        chip = record_sent(
            db,
            reservation_id=r.id,
            template_key="event_sms",
            date="2026-04-20",
            assigned_by="manual",  # 운영자가 직접 발송
        )
        assert chip.assigned_by == 'manual'

    def test_creates_chip_with_custom_sent_at(self, db):
        r = _make_reservation(db)
        custom_time = datetime(2026, 4, 20, 12, 0, 0, tzinfo=timezone.utc)
        chip = record_sent(
            db,
            reservation_id=r.id,
            template_key="event_sms",
            date="2026-04-20",
            sent_at=custom_time,
        )
        assert chip.sent_at == custom_time

    def test_creates_chip_with_schedule_id(self, db):
        r = _make_reservation(db)
        t = _make_template(db)
        s = _make_schedule(db, t)
        chip = record_sent(
            db,
            reservation_id=r.id,
            template_key="k",
            date="2026-04-20",
            schedule_id=s.id,
        )
        assert chip.schedule_id == s.id


class TestRecordSentUpdatesExisting:
    def test_updates_existing_auto_chip(self, db):
        r = _make_reservation(db)
        first = ensure_chip(
            db, reservation_id=r.id, template_key="k",
            date="2026-04-20", assigned_by="auto",
        )
        assert first.sent_at is None
        # 발송 기록
        chip = record_sent(
            db,
            reservation_id=r.id,
            template_key="k",
            date="2026-04-20",
        )
        assert chip.id == first.id  # same row
        assert chip.sent_at is not None
        assert chip.send_status == 'sent'
        assert chip.send_error is None

    def test_clears_send_error_on_success(self, db):
        """이전에 실패했던 칩이 재발송 성공 시 send_error 클리어."""
        r = _make_reservation(db)
        first = ensure_chip(
            db, reservation_id=r.id, template_key="k",
            date="2026-04-20", assigned_by="auto",
        )
        first.send_status = 'failed'
        first.send_error = "phone format error"
        db.flush()
        # 운영자 phone 수정 후 재발송 성공
        chip = record_sent(db, reservation_id=r.id, template_key="k", date="2026-04-20")
        assert chip.send_status == 'sent'
        assert chip.send_error is None

    def test_preserves_assigned_by_on_update(self, db):
        """기존 'manual' 칩 발송 성공 시 assigned_by 보존."""
        r = _make_reservation(db)
        first = ensure_chip(
            db, reservation_id=r.id, template_key="k",
            date="2026-04-20", assigned_by="manual",
        )
        chip = record_sent(db, reservation_id=r.id, template_key="k", date="2026-04-20")
        assert chip.id == first.id
        assert chip.assigned_by == 'manual'  # caller 의 assigned_by="auto" default 무시


# ════════════════════════════════════════════════════════════════════
# record_failed — PR3 단계 #6 (OQ-5 fix 포함)
# ════════════════════════════════════════════════════════════════════

class TestRecordFailedNewChip:
    """OQ-5: 신규 INSERT 시 assigned_by='failed' 강제."""

    def test_creates_failed_chip_when_none_exists(self, db):
        r = _make_reservation(db)
        chip = record_failed(
            db,
            reservation_id=r.id,
            template_key="k",
            date="2026-04-20",
            error="Aligo API timeout",
        )
        assert chip is not None
        assert chip.send_status == 'failed'
        assert chip.send_error == "Aligo API timeout"
        # ⭐ OQ-5: assigned_by='failed' 강제
        assert chip.assigned_by == 'failed'

    def test_default_error_message(self, db):
        r = _make_reservation(db)
        chip = record_failed(db, reservation_id=r.id, template_key="k", date="2026-04-20")
        assert chip.send_error == 'unknown'

    def test_truncates_long_error(self, db):
        r = _make_reservation(db)
        long_error = "A" * 1000
        chip = record_failed(
            db, reservation_id=r.id, template_key="k", date="2026-04-20",
            error=long_error,
        )
        assert len(chip.send_error) == 500


class TestRecordFailedSilentFix:
    """⭐ OQ-5 silent fix — 기존 칩의 assigned_by 를 'failed' 로 승격."""

    def test_promotes_auto_to_failed(self, db):
        """기존 'auto' 칩 발송 실패 시 'failed' 로 승격 → 다음 reconcile 가드가 보호."""
        r = _make_reservation(db)
        first = ensure_chip(
            db, reservation_id=r.id, template_key="k",
            date="2026-04-20", assigned_by="auto",
        )
        # 발송 실패
        chip = record_failed(
            db, reservation_id=r.id, template_key="k", date="2026-04-20",
            error="phone format error",
        )
        assert chip.id == first.id
        # ⭐ OQ-5 fix
        assert chip.assigned_by == 'failed'
        assert chip.send_status == 'failed'
        assert chip.send_error == 'phone format error'

    def test_promotes_manual_to_failed(self, db):
        """⭐ 운영자 수동 칩의 발송 실패도 'failed' 마크 (위치 추적용)."""
        r = _make_reservation(db)
        ensure_chip(
            db, reservation_id=r.id, template_key="k",
            date="2026-04-20", assigned_by="manual",
        )
        chip = record_failed(
            db, reservation_id=r.id, template_key="k", date="2026-04-20",
            error="Aligo down",
        )
        assert chip.assigned_by == 'failed'

    def test_protected_by_remove_chip_after_failed(self, db):
        """⭐ E2E: record_failed → remove_chip(force=False) 보호 흐름 검증.

        OQ-5 의 핵심 — failed 칩이 자동 reconcile 사이클에서 사라지지 않음.
        """
        r = _make_reservation(db)
        ensure_chip(
            db, reservation_id=r.id, template_key="k",
            date="2026-04-20", assigned_by="auto",
        )
        record_failed(
            db, reservation_id=r.id, template_key="k", date="2026-04-20",
            error="failed",
        )
        # 다음 reconcile 사이클 시뮬레이션
        deleted = remove_chip(
            db, reservation_id=r.id, template_key="k", date="2026-04-20",
        )
        assert deleted == 0  # 보호됨!
        # delete_chips_for_reservation 도 보호 확인
        deleted = delete_chips_for_reservation(db, reservation_id=r.id)
        assert deleted == 0

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
from app.services.chip_store import ensure_chip, remove_chip, PROTECTED_ASSIGNED_BY


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

    def test_force_deletes_sent_chip(self, db):
        r = _make_reservation(db)
        chip = ensure_chip(
            db, reservation_id=r.id, template_key="k",
            date="2026-04-20", assigned_by="auto",
        )
        chip.sent_at = datetime.now(timezone.utc)
        db.flush()
        deleted = remove_chip(
            db, reservation_id=r.id, template_key="k", date="2026-04-20",
            force=True,
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

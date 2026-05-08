"""consecutive_stay 연속 감지 및 link/unlink 동작 검증.

unlink_from_group 은 reservations.py, naver_sync.py 에서 사용.
link_reservations, _validate_link_inputs 는 수동 연박 묶기 API 에서 사용.

stay_group_excluded 옵션:
  - 사용자 수동 unlink → excluded=True 박힘
  - 시스템 자동 unlink (기본값 False) → excluded 변경 없음
  - excluded=True 예약은 detect 스캔에서 제외
  - 시스템 자동 unlink 후 detect 가 다시 묶을 수 있음
"""
import pytest

from app.db.models import Reservation, ReservationStatus
from app.services.consecutive_stay import (
    unlink_from_group,
    _validate_link_inputs,
    link_reservations,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_reservation(
    db,
    *,
    check_in,
    check_out,
    name="손님",
    phone="01012345678",
    status=ReservationStatus.CONFIRMED,
    stay_group_id=None,
):
    r = Reservation(
        tenant_id=1,
        customer_name=name,
        phone=phone,
        check_in_date=check_in,
        check_in_time="15:00",
        check_out_date=check_out,
        status=status,
        stay_group_id=stay_group_id,
    )
    db.add(r)
    db.flush()
    return r


# ---------------------------------------------------------------------------
# _validate_link_inputs
# ---------------------------------------------------------------------------

class TestValidateLinkInputs:
    def test_fewer_than_2_raises(self):
        with pytest.raises(ValueError, match="2개 이상"):
            _validate_link_inputs([])

    def test_single_reservation_raises(self, db):
        r = _make_reservation(db, check_in="2026-04-01", check_out="2026-04-02")
        with pytest.raises(ValueError, match="2개 이상"):
            _validate_link_inputs([r])

    def test_cancelled_member_raises(self, db):
        r1 = _make_reservation(db, check_in="2026-04-01", check_out="2026-04-02")
        r2 = _make_reservation(
            db,
            check_in="2026-04-02",
            check_out="2026-04-03",
            name="취소자",
            status=ReservationStatus.CANCELLED,
        )
        with pytest.raises(ValueError, match="확정 상태"):
            _validate_link_inputs([r1, r2])

    def test_non_consecutive_raises(self, db):
        r1 = _make_reservation(db, check_in="2026-04-01", check_out="2026-04-02")
        r2 = _make_reservation(db, check_in="2026-04-05", check_out="2026-04-06")
        with pytest.raises(ValueError, match="이어지지 않습니다"):
            _validate_link_inputs([r1, r2])

    def test_consecutive_passes(self, db):
        r1 = _make_reservation(db, check_in="2026-04-01", check_out="2026-04-02")
        r2 = _make_reservation(db, check_in="2026-04-02", check_out="2026-04-03")
        # 예외 없이 통과
        _validate_link_inputs([r1, r2])

    def test_null_checkout_passes(self, db):
        """NULL check_out 은 당일 예약으로 해석되어 다음 날 check_in 과 이어짐."""
        r1 = _make_reservation(db, check_in="2026-04-01", check_out=None)  # 당일
        r2 = _make_reservation(db, check_in="2026-04-02", check_out="2026-04-03")
        _validate_link_inputs([r1, r2])


# ---------------------------------------------------------------------------
# link_reservations — removed in extend-stay refactor 2026-05-09
# ---------------------------------------------------------------------------

class TestLinkReservations:
    def test_two_standalone_reservations(self, db):
        """기존 그룹 없는 예약 2건 → 새 manual-UUID 로 묶임."""
        r1 = _make_reservation(db, check_in="2026-04-01", check_out="2026-04-02")
        r2 = _make_reservation(db, check_in="2026-04-02", check_out="2026-04-03")

        group_id, linked_ids = link_reservations(db, [r1.id, r2.id])

        assert group_id.startswith("manual-")
        assert set(linked_ids) == {r1.id, r2.id}
        assert r1.stay_group_id == group_id
        assert r2.stay_group_id == group_id
        assert r1.stay_group_order == 0
        assert r2.stay_group_order == 1
        assert r1.is_last_in_group is False
        assert r2.is_last_in_group is True
        assert r1.is_long_stay is True
        assert r2.is_long_stay is True

    def test_auto_expands_from_partial_selection(self, db):
        """[r2, r3] 만 선택해도 같은 그룹의 r1, r4 가 자동 포함되어 통합."""
        # 기존 그룹 A: [r1, r2] (4/1~4/3)
        r1 = _make_reservation(db, check_in="2026-04-01", check_out="2026-04-02", stay_group_id="manual-A")
        r2 = _make_reservation(db, check_in="2026-04-02", check_out="2026-04-03", stay_group_id="manual-A")
        # 기존 그룹 B: [r3, r4] (4/3~4/5)
        r3 = _make_reservation(db, check_in="2026-04-03", check_out="2026-04-04", stay_group_id="manual-B")
        r4 = _make_reservation(db, check_in="2026-04-04", check_out="2026-04-05", stay_group_id="manual-B")

        # 사용자가 가운데만 선택
        group_id, linked_ids = link_reservations(db, [r2.id, r3.id])

        # 자동 확장으로 4명 모두 새 그룹에 포함 — linked_ids 도 전체 반환
        assert group_id.startswith("manual-")
        assert group_id != "manual-A"
        assert group_id != "manual-B"
        assert set(linked_ids) == {r1.id, r2.id, r3.id, r4.id}
        for r in (r1, r2, r3, r4):
            assert r.stay_group_id == group_id
        assert r1.stay_group_order == 0
        assert r4.stay_group_order == 3
        assert r4.is_last_in_group is True

    def test_extend_single_existing_group(self, db):
        """기존 단일 그룹 멤버들 + 새 예약 → 새 manual-UUID (항상 manual 전환)."""
        # 기존 그룹: [r1, r2]
        r1 = _make_reservation(db, check_in="2026-04-01", check_out="2026-04-02", stay_group_id="old-group-xyz")
        r2 = _make_reservation(db, check_in="2026-04-02", check_out="2026-04-03", stay_group_id="old-group-xyz")
        # 새 예약 (extend_stay 시나리오)
        r_new = _make_reservation(db, check_in="2026-04-03", check_out="2026-04-04")

        group_id, linked_ids = link_reservations(db, [r1.id, r2.id, r_new.id])

        # 항상 새 manual-UUID 생성 (사용자 개입 = manual 격리)
        assert group_id.startswith("manual-")
        assert group_id != "old-group-xyz"
        assert set(linked_ids) == {r1.id, r2.id, r_new.id}
        for r in (r1, r2, r_new):
            assert r.stay_group_id == group_id

    def test_merge_two_groups_creates_new_uuid(self, db):
        """서로 다른 두 그룹 통째 합치기 → 새 manual-UUID 로 통합."""
        r1 = _make_reservation(db, check_in="2026-04-01", check_out="2026-04-02", stay_group_id="manual-A")
        r2 = _make_reservation(db, check_in="2026-04-02", check_out="2026-04-03", stay_group_id="manual-A")
        r3 = _make_reservation(db, check_in="2026-04-03", check_out="2026-04-04", stay_group_id="manual-B")
        r4 = _make_reservation(db, check_in="2026-04-04", check_out="2026-04-05", stay_group_id="manual-B")

        group_id, linked_ids = link_reservations(db, [r1.id, r2.id, r3.id, r4.id])

        assert group_id.startswith("manual-")
        assert group_id not in ("manual-A", "manual-B")
        assert set(linked_ids) == {r1.id, r2.id, r3.id, r4.id}
        for r in (r1, r2, r3, r4):
            assert r.stay_group_id == group_id

    def test_filters_out_cancelled_in_existing_group(self, db):
        """기존 그룹에 stale CANCELLED 멤버가 있어도 자동 확장이 제외하고 통과."""
        # 기존 그룹 [r1(CONFIRMED), r2(CANCELLED, 과거 취소됐지만 stay_group_id 그대로)]
        r1 = _make_reservation(db, check_in="2026-04-01", check_out="2026-04-02", stay_group_id="manual-A")
        _make_reservation(
            db,
            check_in="2026-04-02",
            check_out="2026-04-03",
            status=ReservationStatus.CANCELLED,
            stay_group_id="manual-A",
        )
        # 새 예약 (r1 이후에 이어짐)
        r_new = _make_reservation(db, check_in="2026-04-02", check_out="2026-04-03")

        # r1 + r_new 로 링크 → r1의 기존 그룹에 CANCELLED r2 있지만 자동 확장 쿼리가 제외
        group_id, linked_ids = link_reservations(db, [r1.id, r_new.id])

        assert group_id.startswith("manual-")
        assert set(linked_ids) == {r1.id, r_new.id}
        assert r1.stay_group_id == group_id
        assert r_new.stay_group_id == group_id

    def test_null_checkout_treated_as_same_day(self, db):
        """NULL check_out 예약은 당일 예약으로 간주되어 다음 날 예약과 연속으로 취급."""
        r1 = _make_reservation(db, check_in="2026-04-01", check_out=None)  # NULL = 당일
        r2 = _make_reservation(db, check_in="2026-04-02", check_out="2026-04-03")

        group_id, linked_ids = link_reservations(db, [r1.id, r2.id])

        assert group_id.startswith("manual-")
        assert set(linked_ids) == {r1.id, r2.id}
        assert r1.stay_group_id == group_id
        assert r2.stay_group_id == group_id

    def test_fewer_than_2_raises_valueerror(self, db):
        r = _make_reservation(db, check_in="2026-04-01", check_out="2026-04-02")
        with pytest.raises(ValueError, match="2개 이상"):
            link_reservations(db, [r.id])

    def test_non_consecutive_raises_valueerror(self, db):
        r1 = _make_reservation(db, check_in="2026-04-01", check_out="2026-04-02")
        r2 = _make_reservation(db, check_in="2026-04-10", check_out="2026-04-11")
        with pytest.raises(ValueError, match="이어지지 않습니다"):
            link_reservations(db, [r1.id, r2.id])


# ---------------------------------------------------------------------------
# PATCH 경로의 CANCELLED → stay_group 자동 해제 로직 (reservations.py:PATCH)
# ---------------------------------------------------------------------------

class TestPatchCancelledUnlinks:
    """PATCH 로 status=CANCELLED 시 unlink_from_group 호출되는지 검증.

    실제 HTTP 경로 대신 unlink_from_group 자체의 동작만 단위로 검증.
    (HTTP 통합 테스트는 별도 auth/fixture 필요 — 여기선 서비스 레벨)
    """

    def test_unlink_dissolves_two_member_group(self, db):
        """2명짜리 그룹에서 1명 해제 → 남은 1명도 자동으로 그룹 해체."""
        from app.services.consecutive_stay import unlink_from_group

        r1 = _make_reservation(db, check_in="2026-04-01", check_out="2026-04-02", stay_group_id="manual-A")
        r1.stay_group_order = 0
        r1.is_last_in_group = False
        r1.is_long_stay = True
        r2 = _make_reservation(db, check_in="2026-04-02", check_out="2026-04-03", stay_group_id="manual-A")
        r2.stay_group_order = 1
        r2.is_last_in_group = True
        r2.is_long_stay = True
        db.flush()

        result = unlink_from_group(db, r2.id)

        assert result is True
        assert r2.stay_group_id is None
        assert r2.stay_group_order is None
        assert r2.is_last_in_group is None
        # 남은 1명도 그룹 해체
        assert r1.stay_group_id is None
        assert r1.stay_group_order is None

    def test_unlink_preserves_group_with_2plus_remaining(self, db):
        """3명짜리 그룹에서 1명 해제 → 남은 2명 그대로 유지 + re-order."""
        from app.services.consecutive_stay import unlink_from_group

        r1 = _make_reservation(db, check_in="2026-04-01", check_out="2026-04-02", stay_group_id="manual-A")
        r1.stay_group_order = 0
        r1.is_long_stay = True
        r2 = _make_reservation(db, check_in="2026-04-02", check_out="2026-04-03", stay_group_id="manual-A")
        r2.stay_group_order = 1
        r2.is_long_stay = True
        r3 = _make_reservation(db, check_in="2026-04-03", check_out="2026-04-04", stay_group_id="manual-A")
        r3.stay_group_order = 2
        r3.is_last_in_group = True
        r3.is_long_stay = True
        db.flush()

        # 가운데 r2 를 해제 (취소 시나리오)
        result = unlink_from_group(db, r2.id)

        assert result is True
        assert r2.stay_group_id is None
        # r1, r3 그대로 유지 + re-order
        assert r1.stay_group_id == "manual-A"
        assert r3.stay_group_id == "manual-A"
        assert r1.stay_group_order == 0
        assert r3.stay_group_order == 1
        assert r1.is_last_in_group is False
        assert r3.is_last_in_group is True


# ---------------------------------------------------------------------------
# stay_group_excluded 옵션 D 픽스 (11회차 diag)
# ---------------------------------------------------------------------------

class TestStayGroupExcluded:
    """stay_group_excluded 플래그 동작 검증."""

    def test_user_unlink_sets_excluded_flag(self, db):
        """exclude_from_auto_link=True 호출 → DB 에 stay_group_excluded=True 박힘."""
        r1 = _make_reservation(db, check_in="2026-04-01", check_out="2026-04-02", stay_group_id="manual-A")
        r1.stay_group_order = 0
        r1.is_last_in_group = False
        r1.is_long_stay = True
        r2 = _make_reservation(db, check_in="2026-04-02", check_out="2026-04-03", stay_group_id="manual-A")
        r2.stay_group_order = 1
        r2.is_last_in_group = True
        r2.is_long_stay = True
        db.flush()

        result = unlink_from_group(db, r1.id, exclude_from_auto_link=True)

        assert result is True
        assert r1.stay_group_id is None
        assert r1.stay_group_excluded is True

    def test_default_unlink_does_not_set_excluded(self, db):
        """인자 없이 호출(기본값 False) → stay_group_excluded=False 유지 (네이버 sync/cascade 회귀 방지)."""
        r1 = _make_reservation(db, check_in="2026-04-01", check_out="2026-04-02", stay_group_id="manual-A")
        r1.stay_group_order = 0
        r1.is_last_in_group = False
        r1.is_long_stay = True
        r2 = _make_reservation(db, check_in="2026-04-02", check_out="2026-04-03", stay_group_id="manual-A")
        r2.stay_group_order = 1
        r2.is_last_in_group = True
        r2.is_long_stay = True
        db.flush()

        result = unlink_from_group(db, r1.id)  # exclude_from_auto_link 기본값 False

        assert result is True
        assert r1.stay_group_id is None
        assert r1.stay_group_excluded is False

    def test_detect_skips_excluded_reservations(self, db):
        """excluded=True 인 예약은 detect 스캔에서 빠져 재묶이지 않음.

        detect 날짜 범위 내 예약으로 세팅해야 실제 필터 동작을 검증할 수 있음.
        """
        from app.services.consecutive_stay import detect_and_link_consecutive_stays
        from app.config import today_kst_date
        from datetime import timedelta

        today = today_kst_date()
        d1 = (today + timedelta(days=1)).strftime("%Y-%m-%d")
        d2 = (today + timedelta(days=2)).strftime("%Y-%m-%d")
        d3 = (today + timedelta(days=3)).strftime("%Y-%m-%d")

        r1 = _make_reservation(db, check_in=d1, check_out=d2)
        r2 = _make_reservation(db, check_in=d2, check_out=d3)
        # r1 을 사용자가 수동 unlink → excluded=True
        r1.stay_group_excluded = True
        db.flush()

        result = detect_and_link_consecutive_stays(db, tenant_id=1)

        # r1 이 excluded 라 chain 이 형성되지 않음 (r2 단독은 2명 미만이라 그룹 안 됨)
        assert result["linked"] == 0
        db.refresh(r1)
        db.refresh(r2)
        assert r1.stay_group_id is None
        assert r2.stay_group_id is None

    def test_link_reservations_clears_excluded_flag(self, db):
        """수동 link 시 chain 멤버의 stay_group_excluded=False 로 reset."""
        r1 = _make_reservation(db, check_in="2026-04-01", check_out="2026-04-02")
        r2 = _make_reservation(db, check_in="2026-04-02", check_out="2026-04-03")
        # r1 이 이전에 excluded 상태였음
        r1.stay_group_excluded = True
        db.flush()

        group_id, linked_ids = link_reservations(db, [r1.id, r2.id])

        assert group_id.startswith("manual-")
        assert r1.stay_group_excluded is False
        assert r2.stay_group_excluded is False

    def test_status_cancelled_then_restored_can_relink(self, db):
        """시스템 자동 unlink (exclude_from_auto_link=False) 후 detect 가 다시 묶을 수 있음.

        detect 날짜 범위: check_out >= today AND check_in <= today+5.
        동적으로 날짜를 생성해 범위 내 예약을 보장.
        """
        from app.services.consecutive_stay import detect_and_link_consecutive_stays
        from app.config import today_kst_date
        from datetime import timedelta

        today = today_kst_date()
        d1 = (today + timedelta(days=1)).strftime("%Y-%m-%d")
        d2 = (today + timedelta(days=2)).strftime("%Y-%m-%d")
        d3 = (today + timedelta(days=3)).strftime("%Y-%m-%d")

        r1 = _make_reservation(db, check_in=d1, check_out=d2, stay_group_id="manual-A")
        r1.stay_group_order = 0
        r1.is_last_in_group = False
        r1.is_long_stay = True
        r2 = _make_reservation(db, check_in=d2, check_out=d3, stay_group_id="manual-A")
        r2.stay_group_order = 1
        r2.is_last_in_group = True
        r2.is_long_stay = True
        db.flush()

        # 시스템 자동 unlink (CANCELLED 처리 등) — exclude_from_auto_link=False (기본값)
        unlink_from_group(db, r1.id)
        assert r1.stay_group_excluded is False  # excluded 미설정

        # detect 실행 → 두 예약 다시 CONFIRMED 이고 excluded=False 라 재묶임
        result = detect_and_link_consecutive_stays(db, tenant_id=1)

        assert result["linked"] > 0
        db.refresh(r1)
        db.refresh(r2)
        assert r1.stay_group_id is not None
        assert r1.stay_group_id == r2.stay_group_id

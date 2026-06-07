"""split_group_guard (split-group P2 경보 + P3 자동 전파) 통합 테스트.

검증:
  - find_confirmed_siblings: 그룹 키 기준 CONFIRMED sibling 만 조회 (+ min_checkout 경계)
  - alert_cancel_orphan: ActivityLog 생성 + 일 1회 dedup + dedup=False 즉시 발화
  - alert-only 불변: 경보가 sibling 의 status 를 절대 바꾸지 않음
  - alert_bc_drift: 그룹 총 row 수(취소 포함) 비교 + primary CONFIRMED 가드 + dedup
  - alert_unsplit_multi: 비분할 bc 1→N 경보 + CONFIRMED 가드
  - sweep_orphan_groups: 취소 primary × CONFIRMED sibling(check_out>=today) + dedup 공유
  - propagate_cancel (P3): 비보호 전파 + cancelled_at + sent 칩 보존 + 보호신호 skip
    + 그룹당 1회 ledger (재전파 금지) + 수동 stay_group unlink
  - alert_reactivated_orphan (P3): 부활 경보 (전이 기반, 자동 복구 없음)
  - 기본 모드: SPLIT_CANCEL_MODE='alert' (스위치 OFF)
"""
import pytest

from app.config import settings
from app.db.models import (
    ActivityLog,
    Reservation,
    ReservationSmsAssignment,
    ReservationStatus,
    RoomAssignment,
)
from app.services.split_group_guard import (
    TYPE_BC_DRIFT,
    TYPE_CANCEL_ORPHAN,
    TYPE_CANCEL_PROPAGATED,
    TYPE_REACTIVATED,
    alert_bc_drift,
    alert_cancel_orphan,
    alert_reactivated_orphan,
    alert_unsplit_multi,
    find_confirmed_siblings,
    propagate_cancel,
    sweep_orphan_groups,
)


def _make_res(db, *, source="naver", gid=None, status=ReservationStatus.CONFIRMED,
              naver_booking_id=None, check_in="2026-07-01", check_out="2026-07-02",
              name="김철수", phone="01012345678"):
    res = Reservation(
        tenant_id=1,
        customer_name=name,
        phone=phone,
        check_in_date=check_in,
        check_in_time="15:00",
        check_out_date=check_out,
        status=status,
        booking_source=source,
        naver_booking_id=naver_booking_id,
        split_group_id=gid,
        booking_count=1,
    )
    db.add(res)
    db.flush()
    return res


def _make_group(db, gid="nsplit-777", primary_status=ReservationStatus.CANCELLED,
                sibling_count=1, **kw):
    primary = _make_res(db, source="naver", gid=gid, status=primary_status,
                        naver_booking_id="777", **kw)
    siblings = [
        _make_res(db, source="naver_split", gid=gid, **kw)
        for _ in range(sibling_count)
    ]
    db.commit()
    return primary, siblings


def _alert_logs(db, activity_type):
    return db.query(ActivityLog).filter(ActivityLog.activity_type == activity_type).all()


class TestFindConfirmedSiblings:
    def test_finds_only_confirmed_split_siblings(self, db):
        primary, sibs = _make_group(db, sibling_count=2)
        # 하나는 취소 처리 → 조회 제외돼야 함
        sibs[1].status = ReservationStatus.CANCELLED
        db.commit()

        found = find_confirmed_siblings(db, "nsplit-777", primary.id)
        assert [r.id for r in found] == [sibs[0].id]

    def test_min_checkout_boundary(self, db):
        primary, (sib,) = _make_group(db, check_in="2026-07-01", check_out="2026-07-02")
        assert find_confirmed_siblings(db, "nsplit-777", primary.id, min_checkout="2026-07-02")
        assert not find_confirmed_siblings(db, "nsplit-777", primary.id, min_checkout="2026-07-03")


class TestAlertCancelOrphan:
    def test_creates_activity_log_and_dedups_same_day(self, db):
        primary, (sib,) = _make_group(db)

        first = alert_cancel_orphan(db, primary, source="naver_sync")
        assert first == [sib.id]
        assert len(_alert_logs(db, TYPE_CANCEL_ORPHAN)) == 1

        # 같은 날 재호출 (5분 cron 시뮬레이션) → dedup
        second = alert_cancel_orphan(db, primary, source="naver_sync")
        assert second == []
        assert len(_alert_logs(db, TYPE_CANCEL_ORPHAN)) == 1

    def test_dedup_marker_no_substring_collision(self, db):
        """nsplit-77 경보가 nsplit-777 의 기존 경보에 의해 억제되면 안 됨 (JSON 경계 마커)."""
        p_long, _ = _make_group(db, gid="nsplit-777", name="긴키", phone="0101")
        p_short, (sib_short,) = _make_group(db, gid="nsplit-77", name="짧은키", phone="0102")

        alert_cancel_orphan(db, p_long, source="naver_sync")
        # nsplit-777 경보가 있어도 nsplit-77 은 독립 발화돼야 함
        assert alert_cancel_orphan(db, p_short, source="naver_sync") == [sib_short.id]
        assert len(_alert_logs(db, TYPE_CANCEL_ORPHAN)) == 2

    def test_dedup_false_fires_again(self, db):
        primary, (sib,) = _make_group(db)
        alert_cancel_orphan(db, primary, source="naver_sync")
        # 운영자 직접 행동 (DELETE/PATCH) — dedup 무시하고 즉시 발화
        again = alert_cancel_orphan(db, primary, source="delete", dedup=False)
        assert again == [sib.id]
        assert len(_alert_logs(db, TYPE_CANCEL_ORPHAN)) == 2

    def test_noop_when_no_confirmed_sibling(self, db):
        primary, (sib,) = _make_group(db)
        sib.status = ReservationStatus.CANCELLED
        db.commit()
        assert alert_cancel_orphan(db, primary, source="naver_sync") == []
        assert not _alert_logs(db, TYPE_CANCEL_ORPHAN)

    def test_noop_without_group_key(self, db):
        primary = _make_res(db, status=ReservationStatus.CANCELLED, naver_booking_id="888")
        db.commit()
        assert alert_cancel_orphan(db, primary, source="naver_sync") == []

    def test_alert_only_never_mutates_sibling(self, db):
        """alert-only 불변 — P3 전까지 어떤 경보도 sibling 데이터를 바꾸면 안 됨."""
        primary, (sib,) = _make_group(db)
        alert_cancel_orphan(db, primary, source="naver_sync")
        db.commit()
        db.refresh(sib)
        assert sib.status == ReservationStatus.CONFIRMED
        assert sib.split_group_id == "nsplit-777"


class TestAlertBcDrift:
    def test_fires_on_mismatch_counting_cancelled_rows(self, db):
        """비교식은 취소 포함 총 row 수 — sibling 취소돼도 그룹 크기는 유지 (오탐 방지)."""
        primary, (sib,) = _make_group(db, primary_status=ReservationStatus.CONFIRMED)
        sib.status = ReservationStatus.CANCELLED
        db.commit()
        # 그룹 총 row=2 (취소 포함). 네이버 bc=2 → 불일치 아님 (alive=1 비교였다면 오탐)
        assert alert_bc_drift(db, primary.id, "nsplit-777", 2, source="naver_sync") is False
        # 네이버가 3으로 증설 → 진짜 drift
        assert alert_bc_drift(db, primary.id, "nsplit-777", 3, source="naver_sync") is True
        assert len(_alert_logs(db, TYPE_BC_DRIFT)) == 1

    def test_cancelled_primary_guard(self, db):
        primary, _ = _make_group(db, primary_status=ReservationStatus.CANCELLED)
        assert alert_bc_drift(db, primary.id, "nsplit-777", 5, source="naver_sync") is False
        assert not _alert_logs(db, TYPE_BC_DRIFT)

    def test_daily_dedup(self, db):
        primary, _ = _make_group(db, primary_status=ReservationStatus.CONFIRMED)
        assert alert_bc_drift(db, primary.id, "nsplit-777", 3, source="naver_sync") is True
        assert alert_bc_drift(db, primary.id, "nsplit-777", 3, source="naver_sync") is False
        assert len(_alert_logs(db, TYPE_BC_DRIFT)) == 1


class TestAlertUnsplitMulti:
    def test_fires_for_confirmed_and_dedups(self, db):
        res = _make_res(db, naver_booking_id="999")
        db.commit()
        assert alert_unsplit_multi(db, res.id, 2, source="naver_sync") is True
        assert alert_unsplit_multi(db, res.id, 2, source="naver_sync") is False
        assert len(_alert_logs(db, TYPE_BC_DRIFT)) == 1

    def test_cancelled_guard(self, db):
        res = _make_res(db, status=ReservationStatus.CANCELLED, naver_booking_id="999")
        db.commit()
        assert alert_unsplit_multi(db, res.id, 2, source="naver_sync") is False


class TestSweep:
    def test_alerts_future_checkout_only(self, db):
        # 미래 체류 고아 (경보 대상)
        _make_group(db, gid="nsplit-100", check_in="2026-07-01", check_out="2026-07-02",
                    name="미래", phone="0101")
        # 과거 체류 고아 (제외 — 발송/배정 위험 없음)
        _make_group(db, gid="nsplit-200", check_in="2026-05-01", check_out="2026-05-02",
                    name="과거", phone="0102")

        result = sweep_orphan_groups(db, today_str="2026-06-07")
        assert result["groups_scanned"] == 2
        assert result["groups_alerted"] == 1
        assert result["siblings_alerted"] == 1

    def test_sweep_shares_dedup_with_sync_path(self, db):
        primary, _ = _make_group(db, gid="nsplit-100", check_in="2026-07-01",
                                 check_out="2026-07-02")
        # sync 경로가 먼저 경보한 날 → sweep 은 중복 발화 안 함
        alert_cancel_orphan(db, primary, source="naver_sync")
        result = sweep_orphan_groups(db, today_str="2026-06-07")
        assert result["groups_alerted"] == 0
        assert len(_alert_logs(db, TYPE_CANCEL_ORPHAN)) == 1


# ── P3: 자동 전파 ──

def _add_chip(db, res_id, *, assigned_by="auto", sent_at=None, key="t1", date="2026-07-01"):
    chip = ReservationSmsAssignment(
        tenant_id=1, reservation_id=res_id, template_key=key, date=date,
        assigned_by=assigned_by, sent_at=sent_at,
    )
    db.add(chip)
    db.flush()
    return chip


class TestPropagateCancel:
    def test_code_default_mode_is_alert(self):
        """코드 기본값은 alert — auto 는 운영 절차(§7) 거쳐 .env 명시로만 전환.
        (런타임 settings 가 아닌 필드 default 검증 — .env 에 auto 가 켜져 있어도 통과)"""
        from app.config import Settings
        assert Settings.model_fields["SPLIT_CANCEL_MODE"].default == "alert"

    def test_propagates_unprotected_sibling(self, db):
        primary, (sib,) = _make_group(db)
        result = propagate_cancel(db, primary, source="naver_sync")
        db.commit()

        assert result["propagated"] == [sib.id]
        assert result["skipped"] == {} and result["failed"] == []
        db.refresh(sib)
        assert sib.status == ReservationStatus.CANCELLED
        # cancelled_at 명시 복사 — CancelledZone 노출 + paired-state invariant
        assert sib.cancelled_at is not None
        # ledger 기록
        assert len(_alert_logs(db, TYPE_CANCEL_PROPAGATED)) == 1

    def test_sent_chip_preserved_unsent_deleted(self, db):
        primary, (sib,) = _make_group(db)
        from datetime import datetime
        sent = _add_chip(db, sib.id, sent_at=datetime(2026, 6, 1, 12, 0), key="sent_t")
        unsent = _add_chip(db, sib.id, assigned_by="auto", key="unsent_t")
        db.commit()

        propagate_cancel(db, primary, source="naver_sync")
        db.commit()

        remaining = {c.template_key for c in db.query(ReservationSmsAssignment)
                     .filter(ReservationSmsAssignment.reservation_id == sib.id).all()}
        assert "sent_t" in remaining       # 발송 이력 보존 (중복발송 dedup 근거)
        assert "unsent_t" not in remaining  # 미발송 자동 칩은 lifecycle 이 정리

    @pytest.mark.parametrize("setup", ["check_out_pinned", "mef", "gender_manual",
                                       "manual_ra", "protected_chip"])
    def test_protection_signals_skip(self, db, setup):
        primary, (sib,) = _make_group(db)
        if setup == "check_out_pinned":
            sib.check_out_pinned = True
        elif setup == "mef":
            sib.manually_edited_fields = {"customer_name": "2026-06-01T00:00:00Z"}
        elif setup == "gender_manual":
            sib.gender_manual = True
        elif setup == "manual_ra":
            # SQLite fixture 는 FK 미강제 — Room row 없이 room_id 만으로 충분
            db.add(RoomAssignment(tenant_id=1, reservation_id=sib.id,
                                  date="2026-07-01", room_id=1,
                                  assigned_by="manual"))
        elif setup == "protected_chip":
            _add_chip(db, sib.id, assigned_by="manual")  # 미발송 보호 칩
        db.commit()

        result = propagate_cancel(db, primary, source="naver_sync")
        db.commit()
        db.refresh(sib)

        assert result["propagated"] == []
        assert sib.id in result["skipped"]
        assert sib.status == ReservationStatus.CONFIRMED  # 자동 취소 금지
        # skip 잔존은 즉시 경보로 가시화
        assert len(_alert_logs(db, TYPE_CANCEL_ORPHAN)) == 1

    def test_confirmed_primary_guard_blocks_propagation(self, db):
        """mef status 핀 '진짜 모순' 상태 (primary CONFIRMED + 네이버 cancelled) —
        시스템이 '경보만, 데이터 안전 우선'을 선언한 상태이므로 전파도 경보 강등."""
        primary, (sib,) = _make_group(db, primary_status=ReservationStatus.CONFIRMED)
        result = propagate_cancel(db, primary, source="naver_sync")
        db.commit()
        db.refresh(sib)

        assert result["propagated"] == []
        assert sib.status == ReservationStatus.CONFIRMED  # 자동 취소 금지
        assert not _alert_logs(db, TYPE_CANCEL_PROPAGATED)  # ledger 미기록
        assert len(_alert_logs(db, TYPE_CANCEL_ORPHAN)) == 1  # 경보 강등

    def test_legacy_failed_chip_protects_sibling(self, db):
        """PR4 이전 레거시 실패칩 (assigned_by='auto' + send_status='failed') 도 보호신호."""
        primary, (sib,) = _make_group(db)
        chip = _add_chip(db, sib.id, assigned_by="auto", key="legacy_fail")
        chip.send_status = "failed"
        db.commit()

        result = propagate_cancel(db, primary, source="naver_sync")
        db.commit()
        db.refresh(sib)

        assert sib.id in result["skipped"]
        assert "protected_unsent_chip" in result["skipped"][sib.id]
        assert sib.status == ReservationStatus.CONFIRMED

    def test_ledger_blocks_repropagation_after_operator_revival(self, db):
        """부분취소 시나리오 — 운영자가 sibling 을 살린 뒤 재전파로 또 취소되면 안 됨."""
        primary, (sib,) = _make_group(db)
        propagate_cancel(db, primary, source="naver_sync")
        db.commit()

        # 운영자가 sibling 복구 (PATCH confirmed 시뮬)
        sib.status = ReservationStatus.CONFIRMED
        sib.cancelled_at = None
        db.commit()

        # 네이버 fetch 윈도우 동안 술어식이 매 sync 재발화 → ledger 가 차단
        result = propagate_cancel(db, primary, source="naver_sync")
        db.commit()
        db.refresh(sib)

        assert result["ledger_skip"] is True
        assert sib.status == ReservationStatus.CONFIRMED  # 재취소 안 됨
        assert len(_alert_logs(db, TYPE_CANCEL_PROPAGATED)) == 1  # ledger 1회뿐
        # 잔존은 경보로 강등됨
        assert len(_alert_logs(db, TYPE_CANCEL_ORPHAN)) == 1

    def test_manual_stay_group_unlinked(self, db):
        primary, (sib,) = _make_group(db)
        # 운영자가 sibling 을 수동 연박그룹에 묶어둔 상태
        peer = _make_res(db, name="동행", phone="0109", check_in="2026-07-02",
                         check_out="2026-07-03", naver_booking_id="555")
        sib.stay_group_id = "manual-abc"
        peer.stay_group_id = "manual-abc"
        db.commit()

        propagate_cancel(db, primary, source="naver_sync")
        db.commit()
        db.refresh(sib)

        assert sib.status == ReservationStatus.CANCELLED
        assert sib.stay_group_id is None  # unlink (lifecycle docstring: caller 책임)


class TestFinalAuditFixes:
    """2026-06-08 최종 전수감사 finding 수정 회귀 고정."""

    def test_propagate_skips_past_stay(self, db):
        """과거 체류 sibling 은 전파 제외 (RA 이력 소급 삭제 방지) + ledger 미기록."""
        primary, (sib,) = _make_group(db, check_in="2026-05-01", check_out="2026-05-02")
        result = propagate_cancel(db, primary, source="naver_sync")
        db.commit()
        db.refresh(sib)

        assert result["propagated"] == []
        assert sib.status == ReservationStatus.CONFIRMED  # 과거분 미접촉
        assert not _alert_logs(db, TYPE_CANCEL_PROPAGATED)  # ledger 없음

    def test_cleanup_ledger_blocks_propagation(self, db):
        """cleanup 스크립트(TYPE_ORPHAN_CLEANUP) 원장도 재전파 차단 — ledger OR 조회."""
        from app.services.activity_logger import log_activity
        from app.services.split_group_guard import TYPE_ORPHAN_CLEANUP

        primary, (sib,) = _make_group(db)
        # cleanup 스크립트가 남기는 원장 시뮬레이션
        log_activity(db, type=TYPE_ORPHAN_CLEANUP, title="정리",
                     detail={"split_group_id": "nsplit-777"})
        db.commit()

        result = propagate_cancel(db, primary, source="naver_sync")
        db.commit()
        db.refresh(sib)

        assert result["ledger_skip"] is True
        assert sib.status == ReservationStatus.CONFIRMED  # 재취소 안 됨

    def test_unsplit_alert_distinguishes_keyless_split_group(self, db):
        """키 없는 분할 primary 는 '분할 미적용' 오도 문구 대신 '키 누락' 으로 분기."""
        import json
        res = _make_res(db, naver_booking_id="999")          # 키 없는 primary
        _make_res(db, source="naver_split")                   # 6-필드 동일 sibling (분할은 됨)
        db.commit()

        assert alert_unsplit_multi(db, res.id, 2, source="naver_sync") is True
        log = _alert_logs(db, TYPE_BC_DRIFT)[0]
        assert "키 누락" in log.title and "객실 추가 생성 금지" in log.title
        assert json.loads(log.detail)["kind"] == "keyless_split_group"

    def test_failed_only_propagation_skips_ledger(self, db, monkeypatch):
        """전원 SAVEPOINT 실패 시 ledger 미기록 → 다음 sync 자연 재시도 허용."""
        from app.services import split_group_guard as g

        primary, (sib,) = _make_group(db)

        def _boom(*a, **kw):
            raise RuntimeError("transient db error")
        monkeypatch.setattr(
            "app.services.reservation_lifecycle.on_status_cancelled", _boom)

        result = propagate_cancel(db, primary, source="naver_sync")
        db.commit()

        assert result["propagated"] == [] and result["failed"] == [sib.id]
        assert not _alert_logs(db, TYPE_CANCEL_PROPAGATED)  # ledger 없음 → 재시도 가능
        assert g._propagated_before(db, "nsplit-777") is False

    def test_sweep_alert_excludes_past_checkout_from_detail(self, db):
        """sweep 경보 detail 에 과거 체크아웃 sibling 혼입 금지 (min_checkout 전달)."""
        import json
        primary, sibs = _make_group(db, sibling_count=2, check_in="2026-07-01",
                                    check_out="2026-07-02")
        # 한 sibling 만 과거 체류로 변경
        sibs[1].check_in_date = "2026-05-01"
        sibs[1].check_out_date = "2026-05-02"
        db.commit()

        result = sweep_orphan_groups(db, today_str="2026-06-08")
        assert result["groups_alerted"] == 1
        log = _alert_logs(db, TYPE_CANCEL_ORPHAN)[0]
        ids = json.loads(log.detail)["sibling_ids"]
        assert ids == [sibs[0].id]  # 미래분만 — 과거 sibs[1] 미혼입


class TestReactivatedAlert:
    def test_alerts_when_cancelled_siblings_remain(self, db):
        primary, (sib,) = _make_group(db, primary_status=ReservationStatus.CONFIRMED)
        sib.status = ReservationStatus.CANCELLED
        db.commit()

        assert alert_reactivated_orphan(db, primary, source="naver_sync") is True
        assert len(_alert_logs(db, TYPE_REACTIVATED)) == 1
        # 자동 복구 금지 — sibling 은 CANCELLED 유지
        db.refresh(sib)
        assert sib.status == ReservationStatus.CANCELLED
        # 일일 dedup
        assert alert_reactivated_orphan(db, primary, source="naver_sync") is False

    def test_noop_when_all_confirmed(self, db):
        primary, _ = _make_group(db, primary_status=ReservationStatus.CONFIRMED)
        assert alert_reactivated_orphan(db, primary, source="naver_sync") is False

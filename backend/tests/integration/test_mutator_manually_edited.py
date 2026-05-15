"""Mutator 의 manually_edited_fields 방명록 가드 검증 (PR1 단계).

검증 핵심:
  - MANUAL 수정 시 guarded 필드를 방명록에 timestamp 함께 자동 등록
  - 다음 NAVER 호출이 방명록 체크 후 skip
  - 다양한 케이스: 신규/기존, 단건/다건, 가드/always 필드 혼합
"""
from datetime import datetime, timezone

from app.db.models import Reservation, ReservationStatus
from app.services.reservation_mutator import ReservationMutator, ChangeSource


def _make_reservation(db, **kwargs):
    defaults = dict(
        tenant_id=1,
        customer_name="naver홍길동",
        phone="01000000000",
        check_in_date="2026-05-20",
        check_in_time="15:00",
        check_out_date="2026-05-22",
        status=ReservationStatus.CONFIRMED,
    )
    defaults.update(kwargs)
    r = Reservation(**defaults)
    db.add(r)
    db.flush()
    return r


# ════════════════════════════════════════════════════════════════════
# MANUAL 수정 → 방명록 자동 등록
# ════════════════════════════════════════════════════════════════════

class TestManualEditAutoLogs:
    def test_phone_edit_logs_in_dict(self, db):
        r = _make_reservation(db)
        assert r.manually_edited_fields == {}

        ReservationMutator.apply_changes(
            db, r, ChangeSource.MANUAL,
            {"phone": "01012345678"},
        )
        assert r.phone == "01012345678"
        assert "phone" in r.manually_edited_fields
        # timestamp 가 ISO 형식
        ts = r.manually_edited_fields["phone"]
        datetime.fromisoformat(ts.replace("Z", "+00:00"))  # 파싱 가능

    def test_customer_name_edit_logs(self, db):
        r = _make_reservation(db)
        ReservationMutator.apply_changes(
            db, r, ChangeSource.MANUAL,
            {"customer_name": "정정된이름"},
        )
        assert "customer_name" in r.manually_edited_fields

    def test_multiple_fields_logged(self, db):
        r = _make_reservation(db)
        ReservationMutator.apply_changes(
            db, r, ChangeSource.MANUAL,
            {
                "customer_name": "새이름",
                "phone": "01099999999",
                "visitor_name": "방문자A",
            },
        )
        edits = r.manually_edited_fields
        assert "customer_name" in edits
        assert "phone" in edits
        assert "visitor_name" in edits

    def test_no_change_no_log(self, db):
        """값 동일하면 applied 미포함 → 방명록에도 안 등록."""
        r = _make_reservation(db, phone="01012345678")
        ReservationMutator.apply_changes(
            db, r, ChangeSource.MANUAL,
            {"phone": "01012345678"},  # 동일값
        )
        assert "phone" not in r.manually_edited_fields


# ════════════════════════════════════════════════════════════════════
# NAVER 가드 — 방명록에 있는 필드는 skip
# ════════════════════════════════════════════════════════════════════

class TestNaverGuardedByDict:
    def test_naver_blocked_when_phone_edited(self, db):
        """⭐ 핵심 시나리오 — 운영자 수정 후 네이버 sync 차단."""
        r = _make_reservation(db, phone="01012345678")
        # 1. 운영자 수정 → 방명록 등록
        ReservationMutator.apply_changes(
            db, r, ChangeSource.MANUAL,
            {"phone": "01099999999"},
        )
        assert r.phone == "01099999999"
        assert "phone" in r.manually_edited_fields
        # 2. 다음 5분 sync — 네이버가 다른 phone 보내옴
        ReservationMutator.apply_changes(
            db, r, ChangeSource.NAVER,
            {"phone": "01088888888"},   # 운영자 값 덮어쓰기 시도
        )
        # 3. 보호됨!
        assert r.phone == "01099999999"

    def test_naver_blocked_for_customer_name(self, db):
        r = _make_reservation(db, customer_name="원래이름")
        ReservationMutator.apply_changes(
            db, r, ChangeSource.MANUAL,
            {"customer_name": "운영자정정"},
        )
        ReservationMutator.apply_changes(
            db, r, ChangeSource.NAVER,
            {"customer_name": "네이버이름"},
        )
        assert r.customer_name == "운영자정정"

    def test_naver_blocked_for_special_requests(self, db):
        r = _make_reservation(db)
        ReservationMutator.apply_changes(
            db, r, ChangeSource.MANUAL,
            {"special_requests": "VIP 케어"},
        )
        ReservationMutator.apply_changes(
            db, r, ChangeSource.NAVER,
            {"special_requests": "네이버 폼 응답"},
        )
        assert r.special_requests == "VIP 케어"

    def test_naver_unblocked_for_non_edited_field(self, db):
        """⭐ 운영자가 수정 안 한 필드는 네이버 가 자유롭게 갱신."""
        r = _make_reservation(db, customer_name="원래이름", phone="01000000000")
        # 운영자가 customer_name 만 수정
        ReservationMutator.apply_changes(
            db, r, ChangeSource.MANUAL,
            {"customer_name": "운영자정정"},
        )
        # 네이버가 phone 갱신 — 이건 허용돼야 함
        ReservationMutator.apply_changes(
            db, r, ChangeSource.NAVER,
            {"phone": "01077777777"},
        )
        assert r.customer_name == "운영자정정"   # 보호됨
        assert r.phone == "01077777777"          # 갱신됨


# ════════════════════════════════════════════════════════════════════
# 기존 pin 컬럼 (날짜) 호환성 — PR1 점진 통합
# ════════════════════════════════════════════════════════════════════

class TestExistingPinCompat:
    def test_date_uses_pin_column_only(self, db):
        """check_in_date 는 PR1 시점에 컬럼 + 방명록 둘 다 — 컬럼 가드 우선."""
        r = _make_reservation(db)
        # 운영자가 날짜 변경
        ReservationMutator.apply_changes(
            db, r, ChangeSource.MANUAL,
            {"check_in_date": "2026-06-01"},
        )
        # PR1 호환: pin 컬럼 + 방명록 둘 다 설정됨
        assert r.check_in_pinned is True
        assert "check_in_date" in r.manually_edited_fields
        # 네이버 sync 시도 → 차단
        ReservationMutator.apply_changes(
            db, r, ChangeSource.NAVER,
            {"check_in_date": "2026-07-01"},
        )
        assert r.check_in_date == "2026-06-01"


# ════════════════════════════════════════════════════════════════════
# Edge cases
# ════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    def test_dict_persists_across_multiple_edits(self, db):
        r = _make_reservation(db)
        ReservationMutator.apply_changes(
            db, r, ChangeSource.MANUAL,
            {"customer_name": "이름1"},
        )
        first_ts = r.manually_edited_fields["customer_name"]

        # 두 번째 운영자 수정 (같은 필드)
        ReservationMutator.apply_changes(
            db, r, ChangeSource.MANUAL,
            {"customer_name": "이름2"},
        )
        # 타임스탬프 갱신됨, 여전히 dict 에 있음
        assert "customer_name" in r.manually_edited_fields
        assert r.customer_name == "이름2"

    def test_system_source_no_log(self, db):
        """SYSTEM 변경은 방명록에 안 남음 (운영자 수정 아니므로)."""
        r = _make_reservation(db)
        # section 은 SYSTEM=always
        ReservationMutator.apply_changes(
            db, r, ChangeSource.SYSTEM,
            {"section": "room"},
        )
        assert r.section == "room"
        assert "section" not in (r.manually_edited_fields or {})

    def test_naver_source_no_log(self, db):
        """NAVER 변경도 방명록에 안 남음."""
        r = _make_reservation(db, customer_name="원본")
        ReservationMutator.apply_changes(
            db, r, ChangeSource.NAVER,
            {"customer_name": "네이버응답"},
        )
        assert r.customer_name == "네이버응답"
        assert "customer_name" not in (r.manually_edited_fields or {})

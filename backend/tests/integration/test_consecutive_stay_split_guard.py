"""detect_and_link_consecutive_stays: naver_split sibling 제외 회귀 테스트.

배경:
  네이버 일반실 booking_count>1 예약은 naver_sync 단계에서 primary + sibling N-1 row 로
  split 된다. sibling 은 customer_name+phone 이 primary 와 동일하므로 연박 감지 로직이
  순진하게 묶으면 sibling 이 다음날 진짜 새 예약과 가짜 chain 을 형성하여 primary 가
  stay_group 에서 누락되는 정합성 위반 발생 (CRITICAL).

  consecutive_stay.py 의 identity_map 빌드 시 booking_source='naver_split' row 를 후보에서
  제외하여 이 위험 차단.

검증:
  - sibling + 다음날 진짜 예약 → primary 가 chain 에 들어가고 sibling 은 빠짐
  - sibling 만 단독 + 다음날 진짜 예약 → 가짜 chain 형성 안 됨
"""
import pytest

from app.db.models import Reservation, ReservationStatus
from app.services.consecutive_stay import detect_and_link_consecutive_stays


def _make_res(db, *, check_in, check_out, booking_source="naver", external_id=None,
              naver_booking_id=None, name="김철수", phone="01012345678"):
    r = Reservation(
        tenant_id=1,
        customer_name=name,
        phone=phone,
        check_in_date=check_in,
        check_in_time="15:00",
        check_out_date=check_out,
        status=ReservationStatus.CONFIRMED,
        booking_source=booking_source,
        external_id=external_id,
        naver_booking_id=naver_booking_id,
    )
    db.add(r)
    db.flush()
    return r


def _dates_from_today(offset_start: int, count: int):
    """오늘 기준 동적 날짜 생성. detect 범위(today ~ today+5) 내 보장."""
    from app.config import today_kst_date
    from datetime import timedelta
    today = today_kst_date()
    return [(today + timedelta(days=offset_start + i)).strftime("%Y-%m-%d") for i in range(count + 1)]


class TestConsecutiveStaySplitGuard:
    def test_sibling_excluded_primary_chains_with_next_day(self, db):
        """primary + sibling (d1~d2) + 다음날 진짜 예약 (d2~d3) →
        primary 만 chain 에 들어가야 함. sibling 은 stay_group 누락."""
        d1, d2, d3 = _dates_from_today(1, 2)
        primary = _make_res(
            db, check_in=d1, check_out=d2,
            booking_source="naver", external_id="12345", naver_booking_id="12345",
        )
        sibling = _make_res(
            db, check_in=d1, check_out=d2,
            booking_source="naver_split",  # external_id/naver_booking_id NULL
        )
        next_day = _make_res(
            db, check_in=d2, check_out=d3,
            booking_source="naver", external_id="67890", naver_booking_id="67890",
        )

        result = detect_and_link_consecutive_stays(db)

        # primary + next_day 가 같은 stay_group 에 묶임
        db.refresh(primary)
        db.refresh(sibling)
        db.refresh(next_day)
        assert primary.stay_group_id is not None
        assert primary.stay_group_id == next_day.stay_group_id
        # sibling 은 chain 후보에서 제외 → stay_group 없음
        assert sibling.stay_group_id is None

    def test_sibling_alone_no_fake_chain(self, db):
        """sibling 1건 + 다음날 진짜 예약 1건 → sibling 은 후보에서 빠지므로
        identity_map 에 1건만 남아 chain 형성 안 됨."""
        d1, d2, d3 = _dates_from_today(1, 2)
        sibling = _make_res(
            db, check_in=d1, check_out=d2,
            booking_source="naver_split",
        )
        next_day = _make_res(
            db, check_in=d2, check_out=d3,
            booking_source="naver", external_id="67890", naver_booking_id="67890",
        )

        detect_and_link_consecutive_stays(db)

        db.refresh(sibling)
        db.refresh(next_day)
        # 둘 다 stay_group 없음 (sibling 은 가드로 제외, next_day 는 단독)
        assert sibling.stay_group_id is None
        assert next_day.stay_group_id is None

    def test_two_naver_naturally_chain_unaffected(self, db):
        """sibling 없는 평범한 연박 케이스: 가드가 정상 동작에 영향 없음."""
        d1, d2, d3 = _dates_from_today(1, 2)
        r1 = _make_res(
            db, check_in=d1, check_out=d2,
            booking_source="naver", external_id="A", naver_booking_id="A",
        )
        r2 = _make_res(
            db, check_in=d2, check_out=d3,
            booking_source="naver", external_id="B", naver_booking_id="B",
        )

        detect_and_link_consecutive_stays(db)

        db.refresh(r1)
        db.refresh(r2)
        assert r1.stay_group_id is not None
        assert r1.stay_group_id == r2.stay_group_id

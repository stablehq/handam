"""_update_reservation freeze 회귀 테스트 (split-group P4 — 8cc7423 시나리오).

지금까지 freeze(is_split_managed) 동작 테스트가 0건이던 갭 해소:
  ① split primary: booking_count/total_price/party_size 가 네이버 원본으로 안 덮임
  ② P4 핵심 — 매핑 해제(_has_room_link=False) + split_group_id 보유: freeze 유지
     (휘발 조건이 풀려도 그룹 키 OR 가 이중계상 차단)
  ③ 매핑 해제 + 무키: 네이버 원본 갱신 (기존 동작 보존 증명)
"""
from app.db.models import Reservation, ReservationStatus
from app.services.naver_sync import _update_reservation


def _primary(db, *, gid="nsplit-777"):
    res = Reservation(
        tenant_id=1, customer_name="한기문", phone="01099998888",
        check_in_date="2026-07-01", check_in_time="15:00",
        check_out_date="2026-07-02", status=ReservationStatus.CONFIRMED,
        booking_source="naver", naver_booking_id="777",
        split_group_id=gid, booking_count=1, total_price=60_000, party_size=2,
    )
    db.add(res)
    db.commit()
    return res


def _naver_payload(**over):
    """네이버 원본 응답 시뮬 — split 전 값 (bc=2, 총액 120,000, 4명)."""
    base = {
        "status": "confirmed",
        "customer_name": "한기문", "phone": "01099998888",
        "date": "2026-07-01", "time": "15:00", "end_date": "2026-07-02",
        "booking_count": 2,
        "total_price": 120_000,
        "people_count": 4,
        "_is_dormitory": False,
        "_has_room_link": True,
    }
    base.update(over)
    return base


class TestSplitFreeze:
    def test_split_primary_frozen_8cc7423(self, db):
        """8cc7423 사고 시나리오 — 재동기화가 분할값을 원본으로 토글하면 안 됨."""
        res = _primary(db)
        _update_reservation(db, res, _naver_payload())
        db.commit()
        db.refresh(res)
        assert res.booking_count == 1
        assert res.total_price == 60_000
        assert res.party_size == 2

    def test_mapping_removed_with_group_key_still_frozen(self, db):
        """P4 핵심 — 매핑 해제로 휘발 조건이 풀려도 그룹 키가 freeze 유지."""
        res = _primary(db)
        _update_reservation(db, res, _naver_payload(_has_room_link=False))
        db.commit()
        db.refresh(res)
        assert res.booking_count == 1
        assert res.total_price == 60_000
        assert res.party_size == 2

    def test_mapping_removed_without_key_updates(self, db):
        """기존 동작 보존 — 무키 + 미매핑(정체불명 상품)은 네이버 원본 그대로 갱신."""
        res = _primary(db, gid=None)
        _update_reservation(db, res, _naver_payload(_has_room_link=False))
        db.commit()
        db.refresh(res)
        assert res.booking_count == 2
        assert res.total_price == 120_000
        assert res.party_size == 4

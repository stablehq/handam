"""_split_multi_room_reservations 단위 테스트 (DB 불필요).

검증:
  - 일반실 + booking_count > 1 → primary in-place 정규화 + sibling N-1 추가
  - 도미토리 (_is_dormitory=True) → split 안 함
  - 재동기화 (existing_map 매칭) → split 안 함
  - 인원/금액 균등분할 (floor + 나머지 primary 몰빵, 합계 보존)
  - 홀수 케이스 (인원 < booking_count) 안전 처리
  - sibling 의 식별자 NULL + booking_source override 마킹
"""
from app.services.naver_sync import _split_multi_room_reservations


def _make_res(**overrides):
    base = {
        "external_id": "12345",
        "naver_booking_id": "12345",
        "customer_name": "김철수",
        "phone": "01012345678",
        "date": "2026-05-01",
        "end_date": "2026-05-02",
        "biz_item_name": "트윈",
        "booking_count": 2,
        "total_price": 200_000,
        "people_count": 2,
        "gender": "여",
        "_has_room_link": True,  # split 가드 통과 (RoomBizItemLink 매핑 있는 정상 일반실)
    }
    base.update(overrides)
    return base


class TestSplitMultiRoom:
    def test_no_split_when_booking_count_1(self):
        res = _make_res(booking_count=1)
        result = _split_multi_room_reservations([res], existing_map={})
        assert len(result) == 1
        assert result[0]["booking_count"] == 1
        assert "_booking_source_override" not in result[0]

    def test_no_split_for_dormitory(self):
        res = _make_res(booking_count=4, _is_dormitory=True)
        result = _split_multi_room_reservations([res], existing_map={})
        assert len(result) == 1
        assert result[0]["booking_count"] == 4  # 도미토리는 booking_count 가 인원수

    def test_no_split_for_unmapped_biz(self):
        """RoomBizItemLink 매핑 없는 biz_item (차량투어, 미등록 상품 등) 은 split 안 함."""
        res = _make_res(booking_count=3, _has_room_link=False)
        result = _split_multi_room_reservations([res], existing_map={})
        assert len(result) == 1
        assert result[0]["booking_count"] == 3  # 손대지 않음

    def test_no_split_when_existing(self):
        """재동기화: existing_map 에 이미 있으면 split 안 함."""
        res = _make_res(booking_count=2)
        existing_map = {"12345": object()}  # 매칭된 primary
        result = _split_multi_room_reservations([res], existing_map=existing_map)
        assert len(result) == 1
        assert result[0]["booking_count"] == 2  # 손대지 않음

    def test_split_2_rooms_even_counts(self):
        res = _make_res(booking_count=2, total_price=200_000, gender="여", people_count=2)
        result = _split_multi_room_reservations([res], existing_map={})
        assert len(result) == 2
        primary, sibling = result[0], result[1]

        # primary 정규화
        assert primary["booking_count"] == 1
        assert primary["total_price"] == 100_000
        assert primary["external_id"] == "12345"
        assert primary["naver_booking_id"] == "12345"

        # sibling: 식별자 NULL + override
        assert sibling["external_id"] is None
        assert sibling["naver_booking_id"] is None
        assert sibling["_booking_source_override"] == "naver_split"
        assert sibling["booking_count"] == 1
        assert sibling["total_price"] == 100_000

        # 인원 합계 보존 (여 2명 → 1+1)
        assert primary["_split_male"] + sibling["_split_male"] == 0
        assert primary["_split_female"] + sibling["_split_female"] == 2

    def test_split_3_rooms_floor_remainder_to_primary(self):
        """3방 + 인원 5명(남5) → primary 가 나머지 흡수: floor(5/3)=1, primary=5-1*2=3, sibling=1, sibling=1"""
        res = _make_res(booking_count=3, total_price=300_000, gender="남", people_count=5)
        result = _split_multi_room_reservations([res], existing_map={})
        assert len(result) == 3

        male_total = sum(r["_split_male"] for r in result)
        female_total = sum(r["_split_female"] for r in result)
        price_total = sum(r["total_price"] for r in result)
        assert male_total == 5
        assert female_total == 0
        assert price_total == 300_000

        # primary 가 나머지 흡수
        assert result[0]["_split_male"] == 3
        assert result[1]["_split_male"] == 1
        assert result[2]["_split_male"] == 1

    def test_uneven_split_safe_when_people_less_than_rooms(self):
        """booking_count=2 + 1명 (남0여1) → primary=여1, sibling=여0 (합계 보존)"""
        res = _make_res(booking_count=2, total_price=100_000, gender="여", people_count=1)
        result = _split_multi_room_reservations([res], existing_map={})
        assert len(result) == 2
        # 합계 보존
        assert result[0]["_split_female"] + result[1]["_split_female"] == 1
        assert result[0]["_split_male"] + result[1]["_split_male"] == 0
        # 가격 합계 보존
        assert result[0]["total_price"] + result[1]["total_price"] == 100_000

    def test_multiple_reservations_independent_split(self):
        res_a = _make_res(external_id="A", naver_booking_id="A", booking_count=2, total_price=100_000)
        res_b = _make_res(external_id="B", naver_booking_id="B", booking_count=3, total_price=300_000)
        result = _split_multi_room_reservations([res_a, res_b], existing_map={})
        # A: 1 + 1 sibling, B: 1 + 2 sibling = 5
        assert len(result) == 5
        # primary 들은 in-place 변경됨
        assert res_a["booking_count"] == 1
        assert res_b["booking_count"] == 1
        # split-group P1: 그룹 키는 booking 별로 독립 (멤버 수까지 검증)
        a_count = sum(1 for r in result if r.get("_split_group_id") == "nsplit-A")
        b_count = sum(1 for r in result if r.get("_split_group_id") == "nsplit-B")
        assert a_count == 2  # primary + sibling 1
        assert b_count == 3  # primary + sibling 2

    # ── split-group P1: 영속 연결 키 ──

    def test_split_assigns_shared_group_key(self):
        """primary 와 sibling 모두 같은 'nsplit-{ext_id}' 키를 가짐 (dict 복사 상속)."""
        res = _make_res(booking_count=3)
        result = _split_multi_room_reservations([res], existing_map={})
        assert len(result) == 3
        assert all(r["_split_group_id"] == "nsplit-12345" for r in result)
        # sibling 식별자는 여전히 NULL (연결은 그룹 키 전담 — existing_map 오염 방지 불변)
        assert result[1]["external_id"] is None
        assert result[1]["naver_booking_id"] is None

    def test_no_group_key_when_no_split(self):
        """split 안 되는 4가지 경로(bc=1/도미토리/미매핑/재동기화)는 키 자체가 안 생김."""
        cases = [
            _make_res(booking_count=1),
            _make_res(booking_count=4, _is_dormitory=True),
            _make_res(booking_count=3, _has_room_link=False),
        ]
        for res in cases:
            result = _split_multi_room_reservations([res], existing_map={})
            assert "_split_group_id" not in result[0]

        existing = _make_res(booking_count=2)
        result = _split_multi_room_reservations([existing], existing_map={"12345": object()})
        assert "_split_group_id" not in result[0]

    def test_group_key_none_when_no_ext_id(self):
        """ext_id 없는 raw (이론상) — split 은 진행하되 키는 None (graceful, 기존 동작 동일)."""
        res = _make_res(external_id=None, naver_booking_id=None, booking_count=2)
        result = _split_multi_room_reservations([res], existing_map={})
        assert len(result) == 2
        assert result[0]["_split_group_id"] is None
        assert result[1]["_split_group_id"] is None

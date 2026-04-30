"""surcharge 템플릿 변수 계산 검증 — in-memory SQLite.

templates/variables.py 의 _inject_surcharge_vars / calculate_template_variables 를
직접 호출해 context dict 의 숫자를 확인한다.
"""
import pytest

from app.db.models import (
    Building, MessageTemplate, Reservation, ReservationStatus,
    Room, RoomAssignment, RoomBizItemLink, Tenant,
)
from app.services.surcharge import DOUBLE_ROOM_BIZ_ITEM_IDS
from app.templates.variables import calculate_template_variables, _calculate_stay_nights


DATE = "2026-04-15"
DOUBLE_BIZ_ID = next(iter(DOUBLE_ROOM_BIZ_ITEM_IDS))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_building(db, name="본관"):
    b = Building(tenant_id=1, name=name, is_active=True)
    db.add(b)
    db.flush()
    return b


def _make_room(db, building_id, base_capacity=2, is_dormitory=False, room_number="R101"):
    r = Room(
        tenant_id=1, room_number=room_number, room_type="더블",
        building_id=building_id, is_active=True,
        is_dormitory=is_dormitory, base_capacity=base_capacity,
    )
    db.add(r)
    db.flush()
    return r


def _link_double(db, room_id):
    link = RoomBizItemLink(tenant_id=1, room_id=room_id, biz_item_id=DOUBLE_BIZ_ID)
    db.add(link)
    db.flush()
    return link


def _make_reservation(db, check_in=DATE, check_out="2026-04-16",
                      party_size=None, male_count=None, female_count=None):
    res = Reservation(
        tenant_id=1, customer_name="테스트", phone="01012345678",
        check_in_date=check_in, check_in_time="15:00",
        check_out_date=check_out,
        status=ReservationStatus.CONFIRMED,
        party_size=party_size,
        male_count=male_count,
        female_count=female_count,
    )
    db.add(res)
    db.flush()
    return res


def _make_assignment(db, reservation_id, room_id, date=DATE):
    ra = RoomAssignment(
        tenant_id=1, reservation_id=reservation_id,
        room_id=room_id, date=date, assigned_by="auto",
    )
    db.add(ra)
    db.flush()
    return ra


def _vars(db, reservation, room_assignment, template_key):
    """calculate_template_variables 편의 래퍼."""
    return calculate_template_variables(
        reservation=reservation,
        db=db,
        date=DATE,
        room_assignment=room_assignment,
        template_key=template_key,
    )


# ---------------------------------------------------------------------------
# Tests — _calculate_stay_nights
# ---------------------------------------------------------------------------

class TestCalculateStayNights:
    def test_one_night_stay(self, db):
        """체크인 15일, 체크아웃 16일 → 1박."""
        res = _make_reservation(db, check_in="2026-04-15", check_out="2026-04-16")
        assert _calculate_stay_nights(res) == 1

    def test_three_night_stay(self, db):
        """체크인 15일, 체크아웃 18일 → 3박."""
        res = _make_reservation(db, check_in="2026-04-15", check_out="2026-04-18")
        assert _calculate_stay_nights(res) == 3

    def test_null_checkout_returns_one(self, db):
        """check_out_date = NULL → 1박 기본값."""
        res = _make_reservation(db, check_in="2026-04-15", check_out=None)
        assert _calculate_stay_nights(res) == 1


# ---------------------------------------------------------------------------
# Tests — surcharge variable injection via calculate_template_variables
# ---------------------------------------------------------------------------

class TestSurchargeVariables:
    def test_standard_room_excess_2_nights_1(self, db):
        """일반 객실 (base=2), guest=4, nights=1 → excess=2, per_night=4만원, total=4만원."""
        b = _make_building(db)
        room = _make_room(db, b.id, base_capacity=2)
        res = _make_reservation(db, party_size=4,
                                check_in="2026-04-15", check_out="2026-04-16")
        ra = _make_assignment(db, res.id, room.id)

        ctx = _vars(db, res, ra, template_key="add_standard")

        assert ctx["excess"] == 2
        assert ctx["nights"] == 1
        # unit_standard=20000, excess=2 → per_night=40000 → 만원=4
        assert ctx["surcharge_per_night"] == '4'
        assert ctx["total_surcharge"] == '4'

    def test_standard_room_excess_3_nights_3(self, db):
        """일반 객실 (base=2), guest=5, nights=3 → excess=3, per_night=6만원, total=18만원."""
        b = _make_building(db)
        room = _make_room(db, b.id, base_capacity=2)
        res = _make_reservation(db, party_size=5,
                                check_in="2026-04-15", check_out="2026-04-18")
        ra = _make_assignment(db, res.id, room.id)

        ctx = _vars(db, res, ra, template_key="add_standard")

        assert ctx["excess"] == 3
        assert ctx["nights"] == 3
        assert ctx["surcharge_per_night"] == '6'   # 20000*3 / 10000
        assert ctx["total_surcharge"] == '18'      # 60000*3 / 10000

    def test_double_room_excess_1_nights_1(self, db):
        """더블룸 (base=2), guest=3, nights=1 → excess=1
        per_night = 20000*1 + 5000 = 25000 → '2.5', total = 25000 → '2.5'."""
        b = _make_building(db)
        room = _make_room(db, b.id, base_capacity=2)
        _link_double(db, room.id)
        res = _make_reservation(db, party_size=3,
                                check_in="2026-04-15", check_out="2026-04-16")
        ra = _make_assignment(db, res.id, room.id)

        ctx = _vars(db, res, ra, template_key="add_double")

        assert ctx["excess"] == 1
        assert ctx["nights"] == 1
        assert ctx["surcharge_per_night"] == '2.5'   # (20000+5000) / 10000
        assert ctx["total_surcharge"] == '2.5'       # 25000*1 / 10000

    def test_double_room_excess_1_nights_2(self, db):
        """더블룸 (base=2), guest=3, nights=2 → excess=1
        per_night = 20000*1 + 5000 = 25000 → '2.5', total = 50000 → '5'."""
        b = _make_building(db)
        room = _make_room(db, b.id, base_capacity=2)
        _link_double(db, room.id)
        res = _make_reservation(db, party_size=3,
                                check_in="2026-04-15", check_out="2026-04-17")
        ra = _make_assignment(db, res.id, room.id)

        ctx = _vars(db, res, ra, template_key="add_double")

        assert ctx["excess"] == 1
        assert ctx["nights"] == 2
        assert ctx["surcharge_per_night"] == '2.5'   # (20000+5000) / 10000
        assert ctx["total_surcharge"] == '5'         # 25000*2 / 10000

    def test_double_room_excess_2_nights_3(self, db):
        """더블룸 (base=2), guest=4, nights=3 → excess=2
        per_night = 20000*2 + 5000 = 45000 → '4.5', total = 135000 → '13.5'."""
        b = _make_building(db)
        room = _make_room(db, b.id, base_capacity=2)
        _link_double(db, room.id)
        res = _make_reservation(db, party_size=4,
                                check_in="2026-04-15", check_out="2026-04-18")
        ra = _make_assignment(db, res.id, room.id)

        ctx = _vars(db, res, ra, template_key="add_double")

        assert ctx["excess"] == 2
        assert ctx["nights"] == 3
        assert ctx["surcharge_per_night"] == '4.5'   # (20000*2 + 5000) / 10000
        assert ctx["total_surcharge"] == '13.5'      # 45000*3 / 10000

    def test_custom_tenant_unit_prices_reflected(self, db):
        """Tenant 단가 커스텀 (unit_standard=30000, double_room_fee=8000) → 더블룸에서 양쪽 반영."""
        tenant = db.query(Tenant).filter(Tenant.id == 1).first()
        tenant.surcharge_unit_standard = 30000
        tenant.surcharge_double_room_fee = 8000
        db.flush()

        b = _make_building(db)
        room = _make_room(db, b.id, base_capacity=2)
        _link_double(db, room.id)
        res = _make_reservation(db, party_size=4,
                                check_in="2026-04-15", check_out="2026-04-16")
        ra = _make_assignment(db, res.id, room.id)

        ctx = _vars(db, res, ra, template_key="add_double")

        # excess=2, unit_standard=30000, double_room_fee=8000, nights=1
        # per_night = 30000*2 + 8000 = 68000 → '6.8'
        assert ctx["surcharge_per_night"] == '6.8'
        assert ctx["total_surcharge"] == '6.8'

    def test_null_checkout_date_treated_as_one_night(self, db):
        """check_out_date = NULL → nights=1 기본값 적용."""
        b = _make_building(db)
        room = _make_room(db, b.id, base_capacity=2)
        res = _make_reservation(db, party_size=3, check_out=None)
        ra = _make_assignment(db, res.id, room.id)

        ctx = _vars(db, res, ra, template_key="add_standard")

        assert ctx["nights"] == 1
        assert ctx["excess"] == 1

    def test_surcharge_vars_not_injected_for_other_template_keys(self, db):
        """template_key 가 add_standard/add_double 아니면 surcharge 변수 주입 안 됨."""
        b = _make_building(db)
        room = _make_room(db, b.id, base_capacity=2)
        res = _make_reservation(db, party_size=5)
        ra = _make_assignment(db, res.id, room.id)

        ctx = _vars(db, res, ra, template_key="checkin_info")

        assert "excess" not in ctx
        assert "surcharge_per_night" not in ctx
        assert "total_surcharge" not in ctx

    def test_no_excess_gives_zero(self, db):
        """guest_count == base_capacity → excess=0, per_night=0, total=0."""
        b = _make_building(db)
        room = _make_room(db, b.id, base_capacity=3)
        res = _make_reservation(db, party_size=3,
                                check_in="2026-04-15", check_out="2026-04-16")
        ra = _make_assignment(db, res.id, room.id)

        ctx = _vars(db, res, ra, template_key="add_standard")

        assert ctx["excess"] == 0
        assert ctx["surcharge_per_night"] == '0'
        assert ctx["total_surcharge"] == '0'

    def test_guest_count_falls_back_to_male_plus_female(self, db):
        """party_size=None 이면 male_count+female_count 합산 사용."""
        b = _make_building(db)
        room = _make_room(db, b.id, base_capacity=2)
        # party_size not set, use male=2 + female=2 = 4
        res = _make_reservation(db, party_size=None, male_count=2, female_count=2,
                                check_in="2026-04-15", check_out="2026-04-16")
        ra = _make_assignment(db, res.id, room.id)

        ctx = _vars(db, res, ra, template_key="add_standard")

        assert ctx["guest_count"] == 4
        assert ctx["excess"] == 2

    def test_double_room_add_standard_template_uses_double_room_fee(self, db):
        """방이 더블룸이면 template_key 와 무관하게 double_room_fee 가 추가된다.

        is_double 여부는 방 타입(_link_double) 기준이고, 단가 산출은
        unit_standard*excess + (is_double ? double_room_fee : 0) 로 통일.
        """
        b = _make_building(db)
        room = _make_room(db, b.id, base_capacity=2)
        _link_double(db, room.id)  # 더블룸
        res = _make_reservation(db, party_size=3,
                                check_in="2026-04-15", check_out="2026-04-16")
        ra = _make_assignment(db, res.id, room.id)

        ctx = _vars(db, res, ra, template_key="add_standard")

        # excess=1, is_double=True → 20000*1 + 5000 = 25000 → '2.5'
        assert ctx["excess"] == 1
        assert ctx["surcharge_per_night"] == '2.5'

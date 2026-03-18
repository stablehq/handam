"""
Consistency test: verify that room_assignment._reservation_matches_schedule (Python)
and template_scheduler.get_targets (SQL) produce identical results for all filter types.

Uses SQLite in-memory database to avoid external dependencies.
"""
import json
import pytest
from datetime import date, datetime
from collections import defaultdict

from sqlalchemy import create_engine, or_
from sqlalchemy.orm import sessionmaker, Session

from app.db.models import (
    Base,
    Reservation,
    ReservationStatus,
    Room,
    Building,
    RoomAssignment,
    TemplateSchedule,
    MessageTemplate,
    ReservationSmsAssignment,
)
from app.services.room_assignment import _reservation_matches_schedule
from app.scheduler.template_scheduler import FILTER_BUILDERS


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TODAY = date.today().strftime("%Y-%m-%d")


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


def _make_building(db: Session, name: str, id_: int) -> Building:
    b = Building(id=id_, name=name, is_active=True)
    db.add(b)
    db.flush()
    return b


def _make_room(db: Session, room_number: str, building_id: int, room_id: int = None) -> Room:
    r = Room(
        room_number=room_number,
        room_type="더블룸",
        building_id=building_id,
        is_active=True,
        is_dormitory=False,
    )
    if room_id:
        r.id = room_id
    db.add(r)
    db.flush()
    return r


def _make_reservation(
    db: Session,
    name: str,
    phone: str,
    tags: str = "",
    check_in: str = TODAY,
    naver_room_type: str = "",
) -> Reservation:
    r = Reservation(
        customer_name=name,
        phone=phone,
        check_in_date=check_in,
        check_in_time="15:00",
        status=ReservationStatus.CONFIRMED,
        tags=tags,
        naver_room_type=naver_room_type,
    )
    db.add(r)
    db.flush()
    return r


def _make_assignment(db: Session, reservation_id: int, room_number: str) -> RoomAssignment:
    a = RoomAssignment(
        reservation_id=reservation_id,
        date=TODAY,
        room_number=room_number,
        assigned_by="auto",
    )
    db.add(a)
    db.flush()
    return a


def _make_template(db: Session, key: str) -> MessageTemplate:
    t = MessageTemplate(
        template_key=key,
        name=key,
        content="테스트 템플릿",
        is_active=True,
    )
    db.add(t)
    db.flush()
    return t


def _make_schedule(db: Session, template_id: int, filters: list) -> TemplateSchedule:
    s = TemplateSchedule(
        template_id=template_id,
        schedule_name="테스트 스케줄",
        schedule_type="daily",
        filters=json.dumps(filters),
        is_active=True,
        exclude_sent=False,
    )
    db.add(s)
    db.flush()
    return s


# ---------------------------------------------------------------------------
# Helper: run SQL get_targets logic inline (mirrors TemplateScheduleExecutor.get_targets)
# ---------------------------------------------------------------------------

def _sql_get_targets(db: Session, schedule: TemplateSchedule) -> set:
    """Reproduce get_targets SQL logic and return set of reservation ids."""
    query = db.query(Reservation).filter(
        Reservation.status == ReservationStatus.CONFIRMED
    )

    filters = json.loads(schedule.filters) if schedule.filters else []

    target_date = TODAY
    ctx = {"db": db, "target_date": target_date}

    filter_groups: dict = defaultdict(list)
    for f in filters:
        filter_groups[f.get("type", "")].append(f.get("value", ""))

    for filter_type, values in filter_groups.items():
        builder = FILTER_BUILDERS.get(filter_type)
        if not builder:
            continue
        conditions = [c for c in (builder(v, ctx) for v in values) if c is not None]
        if len(conditions) == 1:
            query = query.filter(conditions[0])
        elif len(conditions) > 1:
            query = query.filter(or_(*conditions))

    return {r.id for r in query.all()}


def _python_matches(
    db: Session,
    reservation: Reservation,
    schedule: TemplateSchedule,
) -> bool:
    """Run the Python predicate for a single reservation."""
    room_assignment_row = db.query(RoomAssignment).filter(
        RoomAssignment.reservation_id == reservation.id,
        RoomAssignment.date == reservation.check_in_date,
    ).first()
    has_room = room_assignment_row is not None

    building_id = None
    if room_assignment_row:
        room = db.query(Room).filter(
            Room.room_number == room_assignment_row.room_number
        ).first()
        building_id = room.building_id if room else None

    return _reservation_matches_schedule(
        reservation, schedule, has_room, room_assignment_row, building_id
    )


def _python_get_targets(db: Session, schedule: TemplateSchedule, all_reservations) -> set:
    return {r.id for r in all_reservations if _python_matches(db, r, schedule)}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_building_filter_consistency(db: Session):
    """본관(building=1) 필터: 본관 배정 예약자만 포함, 별관 예약자 제외."""
    b1 = _make_building(db, "본관", 1)
    b2 = _make_building(db, "별관", 2)
    r1 = _make_room(db, "101", building_id=1)
    r2 = _make_room(db, "201", building_id=2)

    res_main = _make_reservation(db, "김철수", "010-1111-1111")
    res_annex = _make_reservation(db, "이영희", "010-2222-2222")
    res_none = _make_reservation(db, "박민준", "010-3333-3333")

    _make_assignment(db, res_main.id, "101")
    _make_assignment(db, res_annex.id, "201")
    # res_none: no assignment

    template = _make_template(db, "building_test")
    schedule = _make_schedule(db, template.id, [{"type": "building", "value": "1"}])

    db.commit()

    all_res = [res_main, res_annex, res_none]
    python_ids = _python_get_targets(db, schedule, all_res)
    sql_ids = _sql_get_targets(db, schedule)

    assert python_ids == sql_ids
    assert res_main.id in python_ids
    assert res_annex.id not in python_ids
    assert res_none.id not in python_ids


def test_assignment_room_filter_consistency(db: Session):
    """assignment=room 필터: 객실 배정된 예약자만 포함."""
    b1 = _make_building(db, "본관", 1)
    r1 = _make_room(db, "101", building_id=1)

    res_with_room = _make_reservation(db, "김철수", "010-1111-1111")
    res_no_room = _make_reservation(db, "이영희", "010-2222-2222")

    _make_assignment(db, res_with_room.id, "101")

    template = _make_template(db, "assignment_room_test")
    schedule = _make_schedule(db, template.id, [{"type": "assignment", "value": "room"}])

    db.commit()

    all_res = [res_with_room, res_no_room]
    python_ids = _python_get_targets(db, schedule, all_res)
    sql_ids = _sql_get_targets(db, schedule)

    assert python_ids == sql_ids
    assert res_with_room.id in python_ids
    assert res_no_room.id not in python_ids


def test_assignment_party_filter_consistency(db: Session):
    """assignment=party 필터: 파티만 태그 있고 미배정인 예약자만 포함."""
    b1 = _make_building(db, "본관", 1)
    r1 = _make_room(db, "101", building_id=1)

    res_party = _make_reservation(db, "김철수", "010-1111-1111", tags="파티만,객후")
    res_room = _make_reservation(db, "이영희", "010-2222-2222", tags="파티만")
    res_normal = _make_reservation(db, "박민준", "010-3333-3333")

    # res_room has room assignment despite having 파티만 tag → should NOT match party filter
    _make_assignment(db, res_room.id, "101")

    template = _make_template(db, "assignment_party_test")
    schedule = _make_schedule(db, template.id, [{"type": "assignment", "value": "party"}])

    db.commit()

    all_res = [res_party, res_room, res_normal]
    python_ids = _python_get_targets(db, schedule, all_res)
    sql_ids = _sql_get_targets(db, schedule)

    assert python_ids == sql_ids
    assert res_party.id in python_ids
    assert res_room.id not in python_ids
    assert res_normal.id not in python_ids


def test_tag_filter_consistency(db: Session):
    """tag=객후 필터: 태그에 '객후'가 있는 예약자만 포함."""
    res_tagged = _make_reservation(db, "김철수", "010-1111-1111", tags="객후,1초")
    res_other = _make_reservation(db, "이영희", "010-2222-2222", tags="2차만")
    res_none = _make_reservation(db, "박민준", "010-3333-3333")

    template = _make_template(db, "tag_test")
    schedule = _make_schedule(db, template.id, [{"type": "tag", "value": "객후"}])

    db.commit()

    all_res = [res_tagged, res_other, res_none]
    python_ids = _python_get_targets(db, schedule, all_res)
    sql_ids = _sql_get_targets(db, schedule)

    assert python_ids == sql_ids
    assert res_tagged.id in python_ids
    assert res_other.id not in python_ids
    assert res_none.id not in python_ids


def test_combined_filters_consistency(db: Session):
    """building=1 + assignment=room 복합 필터: 본관 배정 예약자만 포함."""
    b1 = _make_building(db, "본관", 1)
    b2 = _make_building(db, "별관", 2)
    r1 = _make_room(db, "101", building_id=1)
    r2 = _make_room(db, "201", building_id=2)

    res_main_assigned = _make_reservation(db, "김철수", "010-1111-1111")
    res_annex_assigned = _make_reservation(db, "이영희", "010-2222-2222")
    res_unassigned = _make_reservation(db, "박민준", "010-3333-3333")

    _make_assignment(db, res_main_assigned.id, "101")
    _make_assignment(db, res_annex_assigned.id, "201")

    template = _make_template(db, "combined_test")
    schedule = _make_schedule(db, template.id, [
        {"type": "building", "value": "1"},
        {"type": "assignment", "value": "room"},
    ])

    db.commit()

    all_res = [res_main_assigned, res_annex_assigned, res_unassigned]
    python_ids = _python_get_targets(db, schedule, all_res)
    sql_ids = _sql_get_targets(db, schedule)

    assert python_ids == sql_ids
    assert res_main_assigned.id in python_ids
    assert res_annex_assigned.id not in python_ids
    assert res_unassigned.id not in python_ids

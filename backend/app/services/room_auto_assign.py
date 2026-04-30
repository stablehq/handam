"""
Room auto-assignment service.
Runs daily to assign rooms for today and tomorrow.
Manual assignments (assigned_by='manual') are never overwritten.

Unified assignment logic (biz_item_id mapping + capacity check + gender lock):
- All rooms (regular and dormitory) use a single biz_item_id → rooms mapping.
- For each unassigned reservation, candidate rooms are looked up by biz_item_id.
- Regular rooms: one reservation per room (capacity check via check_capacity_all_dates).
- Dormitory rooms: multiple reservations per room up to bed_capacity; gender lock
  prevents mixing genders in the same room on the same date.
"""
from datetime import datetime, timedelta
from typing import List, Dict, Tuple
from app.config import KST
from sqlalchemy.orm import Session
import logging

from sqlalchemy import exists, and_
from sqlalchemy.orm import selectinload
from app.db.models import (
    Reservation, Room, RoomAssignment, ReservationStatus,
    TemplateSchedule, RoomBizItemLink, ReservationSmsAssignment,
)
from app.services import room_assignment
from app.db.tenant_context import get_session_tenant_id, is_session_bypass
from app.diag_logger import diag

logger = logging.getLogger(__name__)


def auto_assign_rooms(db: Session, target_date: str = None, created_by: str = "system"):
    """
    Auto-assign rooms for target_date (defaults to today).
    Uses a unified biz_item_id mapping for all room types.
    Never touches manual assignments.
    """
    if not target_date:
        target_date = datetime.now(KST).strftime("%Y-%m-%d")

    logger.info(f"Starting room auto-assignment for {target_date}")

    try:
        diag(
            "auto_assign.enter",
            level="verbose",
            target_date=target_date,
            created_by=created_by,
            bypass_active=is_session_bypass(db),
            tenant_ctx=get_session_tenant_id(db),
        )
    except Exception:
        pass

    # Get rooms with at least one biz_item linked (N:M via RoomBizItemLink)
    # exists().where() 는 SQLAlchemy Core 라 옵션 C 의 before_compile 자동
    # tenant 필터가 안 탄다. 명시 tenant_id 매칭 필수 (correlated subquery).
    rooms_with_biz = (
        db.query(Room)
        .filter(
            Room.is_active == True,
            exists().where(
                and_(
                    RoomBizItemLink.room_id == Room.id,
                    RoomBizItemLink.tenant_id == Room.tenant_id,
                )
            ),
        )
        .options(selectinload(Room.biz_item_links))
        .order_by(Room.sort_order)
        .all()
    )
    if not rooms_with_biz:
        logger.info("No rooms with biz_item_id found, skipping auto-assign")
        return {"target_date": target_date, "assigned": 0, "unassigned": 0}

    # Build biz_item_id -> rooms mapping for ALL rooms (regular + dormitory)
    biz_to_rooms: Dict[str, List[Room]] = {}
    for room in rooms_with_biz:
        for link in room.biz_item_links:
            biz_to_rooms.setdefault(link.biz_item_id, []).append(room)

    # Get all unassigned confirmed reservations for target_date
    unassigned = _get_unassigned_reservations(db, target_date)

    assigned_details, failed_details = _assign_all_rooms(db, unassigned, biz_to_rooms, target_date)

    assigned_count = len(assigned_details)
    assigned_reservation_ids = [d["reservation_id"] for d in assigned_details]

    # Flush then sync SMS tags in bulk
    db.flush()
    # Defense-in-depth: explicit tenant filter — bypass leak from a sibling task
    # would otherwise return cross-tenant schedules. Without this guard, HANDAM
    # schedules leaked into STABLE auto-assign chip-reconcile and produced
    # cross-tenant chips that the wrong tenant's sender then picked up.
    tid_for_schedules = get_session_tenant_id(db)
    if tid_for_schedules is None:
        raise RuntimeError("auto_assign_rooms requires tenant context")
    schedules = (
        db.query(TemplateSchedule)
        .filter(
            TemplateSchedule.tenant_id == tid_for_schedules,
            TemplateSchedule.is_active == True,
        )
        .all()
    )
    for res_id in assigned_reservation_ids:
        room_assignment.sync_sms_tags(db, res_id, schedules=schedules)

    # Surcharge batch reconcile (추가 인원 요금)
    try:
        from app.services.surcharge import reconcile_surcharge_batch
        reconcile_surcharge_batch(db, assigned_reservation_ids, target_date)
    except Exception as e:
        logger.warning(f"Surcharge batch reconcile failed: {e}")

    # Summary activity log (like template scheduler)
    if assigned_count > 0:
        from app.services.activity_logger import log_activity
        log_activity(
            db,
            type="room_assign",
            title="객실 자동 배정 : {} ({})".format(
                {
                    'scheduler': '10시 스케줄러',
                    'sync': '신규 예약자 자동 배정',
                    'reconcile': '예약 대사 후 배정',
                }.get(created_by, '수동 버튼'),
                target_date,
            ),
            detail={
                "target_date": target_date,
                "targets": assigned_details,
            },
            target_count=len(unassigned),
            success_count=assigned_count,
            created_by=created_by,
        )

    # Failure activity log + SSE + diag
    if failed_details:
        from app.services.activity_logger import log_activity
        log_activity(
            db,
            type="room_assign_failed",
            title=f"객실 자동 배정 실패 {len(failed_details)}건 ({target_date})",
            detail={
                "target_date": target_date,
                "failures": failed_details,
            },
            target_count=len(failed_details),
            failed_count=len(failed_details),
            status="failed",
            created_by=created_by,
        )

        # SSE event — frontend listens for room_assign_failed
        try:
            from app.services.event_bus import publish
            publish(
                "room_assign_failed",
                {
                    "target_date": target_date,
                    "count": len(failed_details),
                    "failures": failed_details[:10],  # first 10 only in payload
                },
                tenant_id=get_session_tenant_id(db),
            )
        except Exception as e:
            logger.warning(f"SSE publish failed: {e}")

        # Diagnostic log
        try:
            diag("auto_assign.failed", level="critical", target_date=target_date, count=len(failed_details))
        except Exception as e:
            logger.warning(f"diag log failed: {e}")

    result = {
        "target_date": target_date,
        "assigned": assigned_count,
        "unassigned": len(unassigned) - assigned_count,
    }
    logger.info(f"Room auto-assignment complete: {result}")

    try:
        diag(
            "auto_assign.exit",
            level="verbose",
            target_date=target_date,
            candidates=len(unassigned),
            assigned=assigned_count,
            failed=len(failed_details),
        )
    except Exception:
        pass

    return result


def _get_unassigned_reservations(db: Session, target_date: str) -> List[Reservation]:
    """Get confirmed reservations with no assignment for target_date."""
    tid = get_session_tenant_id(db)
    if tid is None:
        raise RuntimeError("_get_unassigned_reservations requires tenant context")

    # Defense-in-depth: explicit tenant filter — do not rely on the auto
    # before_compile filter alone. If bypass_tenant_filter were leaked True
    # from a sibling task, the implicit filter is skipped and cross-tenant
    # candidates would otherwise leak in. Cross-tenant candidates would then
    # collide on uq_room_assignment_res_date when assign_room INSERTs with
    # before_flush injecting the wrong tenant_id.
    unassigned = (
        db.query(Reservation)
        .filter(
            Reservation.tenant_id == tid,
            Reservation.naver_biz_item_id.isnot(None),
            Reservation.status == ReservationStatus.CONFIRMED,
            Reservation.section.notin_(['party', 'unstable']),
            Reservation.check_in_date <= target_date,
        )
        .filter(
            ~Reservation.id.in_(
                db.query(RoomAssignment.reservation_id).filter(
                    RoomAssignment.date == target_date,
                    RoomAssignment.tenant_id == tid,
                )
            )
        )
        .all()
    )
    # Filter to only those actually active on target_date
    return [
        r for r in unassigned
        if r.check_out_date is None or r.check_out_date > target_date or r.check_in_date == target_date
    ]


def _sort_candidate_rooms(rooms: List[Room], biz_item_id: str, gender: str) -> List[Room]:
    """Sort candidate rooms by gender-specific priority from RoomBizItemLink."""
    def get_priority(room: Room) -> tuple:
        for link in room.biz_item_links:
            if link.biz_item_id == biz_item_id:
                if gender == "여":
                    return (link.female_priority or 0, room.sort_order, room.id)
                elif gender == "남":
                    return (link.male_priority or 0, room.sort_order, room.id)
                break
        return (0, room.sort_order, room.id)
    return sorted(rooms, key=get_priority)


def _gender_sort_key(res: Reservation) -> int:
    """Sort key: females first (0), males second (1), unknown last (2)."""
    g = (res.gender or "").strip()
    if g == "여": return 0
    if g == "남": return 1
    return 2


def _assign_all_rooms(
    db: Session,
    candidates: List[Reservation],
    biz_to_rooms: Dict[str, List[Room]],
    target_date: str,
) -> Tuple[List[dict], List[dict]]:
    """
    Assign rooms based on biz_item_id mapping.
    For dormitory rooms: respects bed_capacity and gender lock.
    For regular rooms: one reservation per room.
    Gender lock: if a dormitory room already has occupants, only same-gender guests can be added.

    Returns (assigned_results, failed_results):
      assigned_results: [{"reservation_id", "customer_name", "room_number"}, ...]
      failed_results:   [{"reservation_id", "customer_name", "reason",
                          "biz_item_id", "target_date"}, ...]
    Failure reasons:
      - "no_candidate_rooms": no room maps to this biz_item_id
      - "capacity_full": every dorm candidate had no free beds
      - "gender_lock": every dorm candidate was locked by opposite gender
      - "all_rooms_occupied": no regular room had capacity
    """
    assigned_results = []
    failed_results: List[dict] = []

    # Sort candidates: females first, then males, then unknown gender
    candidates = sorted(candidates, key=_gender_sort_key)

    # Build preferred room maps for same-room continuity
    # 1) stay_group → room_id (복수 예약 연장자)
    # 2) reservation_id → room_id (단일 예약 연박자, stay_group_id 없음)
    stay_group_room_map: Dict[str, int] = {}
    long_stay_room_map: Dict[int, int] = {}

    try:
        prev_date = (datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    except ValueError:
        prev_date = None

    # 1) stay_group 기반 (기존 로직)
    group_ids = {r.stay_group_id for r in candidates if r.stay_group_id}
    if group_ids and prev_date:
        check_dates = [target_date, prev_date]
        group_members = (
            db.query(Reservation.stay_group_id, RoomAssignment.room_id)
            .join(RoomAssignment, and_(
                RoomAssignment.reservation_id == Reservation.id,
                RoomAssignment.tenant_id == Reservation.tenant_id,
            ))
            .filter(
                Reservation.stay_group_id.in_(group_ids),
                RoomAssignment.date.in_(check_dates),
            )
            .all()
        )
        for gid, rid in group_members:
            if gid and rid:
                stay_group_room_map[gid] = rid

    # 2) 단일 예약 연박자: stay_group_id 없지만 전날 배정이 있는 경우
    if prev_date:
        long_stay_candidates = [
            r for r in candidates
            if not r.stay_group_id and r.check_in_date < target_date
            and r.check_out_date and r.check_out_date > target_date
        ]
        if long_stay_candidates:
            prev_assignments = (
                db.query(RoomAssignment.reservation_id, RoomAssignment.room_id)
                .filter(
                    RoomAssignment.reservation_id.in_([r.id for r in long_stay_candidates]),
                    RoomAssignment.date == prev_date,
                )
                .all()
            )
            for res_id, room_id in prev_assignments:
                long_stay_room_map[res_id] = room_id

    for res in candidates:
        candidate_rooms = biz_to_rooms.get(res.naver_biz_item_id, [])
        # Sort rooms by gender-specific priority
        res_gender = (res.gender or "").strip()
        candidate_rooms = _sort_candidate_rooms(candidate_rooms, res.naver_biz_item_id, res_gender)

        # Same-room preference: stay_group (연장) or single long-stay (연박)
        preferred_room_id = None
        if res.stay_group_id and res.stay_group_id in stay_group_room_map:
            preferred_room_id = stay_group_room_map[res.stay_group_id]
        elif res.id in long_stay_room_map:
            preferred_room_id = long_stay_room_map[res.id]
        if preferred_room_id:
            preferred = [r for r in candidate_rooms if r.id == preferred_room_id]
            if preferred:
                candidate_rooms = preferred + [r for r in candidate_rooms if r.id != preferred_room_id]
        if not candidate_rooms:
            failed_results.append({
                "reservation_id": res.id,
                "customer_name": res.customer_name,
                "reason": "no_candidate_rooms",
                "biz_item_id": res.naver_biz_item_id,
                "target_date": target_date,
            })
            continue

        people_count = res.party_size or res.booking_count or 1

        assigned_this_res = False
        last_failure_reason: str = None  # tracks the most recent reason across dorm candidates

        for room in candidate_rooms:
            if room.is_dormitory:
                # Check capacity with actual party size
                if not room_assignment.check_capacity_all_dates(
                    db, room.id, target_date, res.check_out_date,
                    people_count=people_count, exclude_reservation_id=res.id
                ):
                    last_failure_reason = "capacity_full"
                    continue

                # Gender lock: check ALL existing occupants' gender across FULL stay range
                # (과거엔 target_date 1일만 봐서 연박 중간일 혼숙이 통과할 수 있었음 — 용량 검사와 범위 맞춤)
                gender_range_end = res.check_out_date or target_date
                existing_query = (
                    db.query(RoomAssignment)
                    .filter(RoomAssignment.room_id == room.id)
                )
                if res.check_out_date:
                    existing_query = existing_query.filter(
                        RoomAssignment.date >= target_date,
                        RoomAssignment.date < gender_range_end,
                    )
                else:
                    # NULL checkout 은 1박 예약 → target_date 하루만 검사
                    existing_query = existing_query.filter(
                        RoomAssignment.date == target_date
                    )
                existing = existing_query.all()
                if existing:
                    existing_reservations = db.query(Reservation).filter(
                        Reservation.id.in_([e.reservation_id for e in existing])
                    ).all()
                    res_gender = (res.gender or "").strip()
                    gender_conflict = False
                    for existing_res in existing_reservations:
                        existing_gender = (existing_res.gender or "").strip()
                        if existing_gender and res_gender and existing_gender != res_gender:
                            gender_conflict = True
                            break
                    if gender_conflict:
                        last_failure_reason = "gender_lock"
                        continue

                # Assign
                room_assignment.assign_room(
                    db, res.id, room.id, target_date, res.check_out_date,
                    assigned_by="auto", skip_sms_sync=True, skip_logging=True,
                )
                db.flush()
                assigned_results.append({"reservation_id": res.id, "customer_name": res.customer_name, "room_number": room.room_number})
                # Update group room map so next group member prefers same room
                if res.stay_group_id:
                    stay_group_room_map[res.stay_group_id] = room.id
                assigned_this_res = True
                break
            else:
                # Regular room: booking_count>1 은 naver_sync 단계에서 primary+sibling 으로
                # split 되어 모든 row 가 booking_count=1 로 정규화됨. 따라서 여기선 1방씩만 배정.
                for reg_room in candidate_rooms:
                    if reg_room.is_dormitory:
                        continue
                    if room_assignment.check_capacity_all_dates(
                        db, reg_room.id, target_date, res.check_out_date,
                        people_count=1, exclude_reservation_id=res.id
                    ):
                        room_assignment.assign_room(
                            db, res.id, reg_room.id, target_date, res.check_out_date,
                            assigned_by="auto", skip_sms_sync=True, skip_logging=True,
                        )
                        db.flush()
                        assigned_results.append({"reservation_id": res.id, "customer_name": res.customer_name, "room_number": reg_room.room_number})
                        if res.stay_group_id:
                            stay_group_room_map[res.stay_group_id] = reg_room.id
                        assigned_this_res = True
                        break
                else:
                    last_failure_reason = "all_rooms_occupied"
                break  # 일반실 분기 완료 — 다음 예약으로

        if not assigned_this_res:
            failed_results.append({
                "reservation_id": res.id,
                "customer_name": res.customer_name,
                "reason": last_failure_reason or "no_candidate_rooms",
                "biz_item_id": res.naver_biz_item_id,
                "target_date": target_date,
            })

    return assigned_results, failed_results


def reconcile_stale_chips(db: Session, target_date: str, lookahead_days: int = 1) -> int:
    """target_date 부터 lookahead_days 동안 칩 0건인 CONFIRMED 예약을 일괄 reconcile.

    auto_assign_rooms 는 신규 배정한 예약만 sync_sms_tags 를 호출하므로,
    옛 회귀로 칩이 빠진 채 이미 배정된 stale 예약(예: 객실은 있는데 칩 0건)은
    정상 흐름에서 영원히 복구되지 않는다. 이 함수가 매일 1회 그 갭을 메운다.

    reconcile_chips_for_reservation 은 idempotent — 정상 칩이 있으면 no-op.
    sync_denormalized_field 는 reservation.room_number 빈 값을 같이 채운다.
    """
    tid = get_session_tenant_id(db)
    if tid is None:
        raise RuntimeError("reconcile_stale_chips requires tenant context")

    end_date = (
        datetime.strptime(target_date, "%Y-%m-%d") + timedelta(days=lookahead_days)
    ).strftime("%Y-%m-%d")

    # NOT EXISTS 패턴 — outer join 을 쓰면 옵션 C 자동 필터의 froms fallback
    # (tenant_context.py) 가 ReservationSmsAssignment 에도 WHERE tenant_id=X 를
    # 추가해 LEFT JOIN 이 INNER JOIN 처럼 동작 → stale(칩 0건) 예약이 결과에서
    # 제거됨. NOT EXISTS 는 subquery 라서 froms 영향 없음 + 명시 tenant 필터로
    # cross-tenant chip 계수도 차단.
    stale_ids = [
        rid
        for (rid,) in db.query(Reservation.id)
        .filter(
            Reservation.tenant_id == tid,
            Reservation.status == ReservationStatus.CONFIRMED,
            Reservation.check_in_date >= target_date,
            Reservation.check_in_date <= end_date,
            ~exists().where(
                and_(
                    ReservationSmsAssignment.reservation_id == Reservation.id,
                    ReservationSmsAssignment.tenant_id == tid,
                )
            ),
        )
        .all()
    ]

    if not stale_ids:
        return 0

    from app.services.chip_reconciler import reconcile_chips_for_reservation

    schedules = (
        db.query(TemplateSchedule)
        .filter(
            TemplateSchedule.tenant_id == tid,
            TemplateSchedule.is_active == True,  # noqa: E712
        )
        .all()
    )

    repaired = 0
    for rid in stale_ids:
        try:
            reconcile_chips_for_reservation(db, rid, schedules=schedules)
            res = db.query(Reservation).filter(Reservation.id == rid).first()
            if res:
                room_assignment.sync_denormalized_field(db, res)
            repaired += 1
        except Exception as e:
            logger.warning(f"reconcile_stale_chips failed for res={rid}: {e}")

    db.commit()

    diag(
        "daily_chip_reconcile.stale_repair",
        level="critical",
        target_date=target_date,
        lookahead_days=lookahead_days,
        candidates=len(stale_ids),
        repaired=repaired,
    )
    return repaired


def daily_assign_rooms(db: Session):
    """
    Daily job: FILL-ONLY mode.
    미배정 예약만 채워넣기. 기존 배정(auto/manual 모두)은 건드리지 않음.

    엣지 케이스(예약/방 설정 변경)는 각 API에서 명시적으로 처리:
      - update_reservation 성별/인원 변경 → check_assignment_validity
      - update_room 설정 변경 → UI 경고 배너
    """
    today = datetime.now(KST).strftime("%Y-%m-%d")
    tomorrow = (datetime.now(KST) + timedelta(days=1)).strftime("%Y-%m-%d")

    logger.info(f"Running daily FILL-ONLY assignment for {today} and {tomorrow}")

    # FILL-ONLY: 미배정만 배정 (DELETE 없음)
    result_today = auto_assign_rooms(db, today, created_by="scheduler")
    result_tomorrow = auto_assign_rooms(db, tomorrow, created_by="scheduler")

    # 옛 회귀로 칩이 빠진 채 이미 배정된 stale 예약을 매일 1회 자동 복구.
    # 오늘 + 내일 체크인 예약만 대상 (lookahead_days=1).
    try:
        repaired = reconcile_stale_chips(db, today, lookahead_days=1)
        if repaired:
            logger.info(f"daily_chip_reconcile: repaired {repaired} stale reservations")
    except Exception as e:
        logger.warning(f"reconcile_stale_chips failed: {e}")

    # diag
    try:
        diag(
            "daily_assign.mode",
            level="verbose",
            mode="fill_only",
            today_assigned=result_today.get("assigned", 0),
            tomorrow_assigned=result_tomorrow.get("assigned", 0),
        )
    except Exception as e:
        logger.warning(f"diag log failed: {e}")

    return {
        "today": result_today,
        "tomorrow": result_tomorrow,
    }

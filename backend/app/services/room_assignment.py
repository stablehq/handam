"""
Centralized room assignment service.
All room assignment operations go through this module to maintain
consistency between room_assignments table and denormalized fields.
"""
from typing import Optional, List, Tuple, Dict
from datetime import datetime, timedelta
from collections import defaultdict
from sqlalchemy.orm import Session
from sqlalchemy import and_, func
import logging

from app.config import today_kst
from app.diag_logger import diag
from app.db.models import RoomAssignment, Reservation, Room
from app.db.tenant_context import get_session_tenant_id
from app.services.activity_logger import log_activity
from app.services.password_display import build_prefixed_password

logger = logging.getLogger(__name__)


def _resolve_prefixed_password(
    db: Session,
    room: Room,
    reservation_id: int,
    dates: List[str],
) -> str:
    """prefix 붙은 표시용 비밀번호를 결정한다 (base 는 단순 복사라 재사용 규칙 불필요).

    Reuse priority:
      1. 같은 room + 같은 날짜에 다른 예약자의 prefixed 값이 이미 저장됨 → 그 값 재사용
         (도미토리 공동 투숙, 수동 복수 배정 → 모든 팀이 같은 표시 번호)
      2. 같은 예약자 + 같은 방 다른 날짜에 prefixed 값이 있음 → 그 값 재사용
         (연박자 재발송 안전망)
      3. 둘 다 없음 → build_prefixed_password() 로 신규 생성
    """
    if not dates:
        return build_prefixed_password(room)

    # P1: 같은 room + 같은 날짜에 다른 예약자가 이미 배정됨
    other = (
        db.query(RoomAssignment)
        .filter(
            RoomAssignment.room_id == room.id,
            RoomAssignment.date.in_(dates),
            RoomAssignment.reservation_id != reservation_id,
            RoomAssignment.room_password_prefixed.isnot(None),
            RoomAssignment.room_password_prefixed != "",
        )
        .first()
    )
    if other and other.room_password_prefixed:
        return other.room_password_prefixed

    # P2: 같은 예약자 + 같은 방 기존 배정이 존재 (날짜 무관)
    # - 연박자 재발송 안전망
    # - 동일 (res, room, dates) 재호출 시 기존 prefix 유지 (연박 연장, 재drag 등)
    same_res = (
        db.query(RoomAssignment)
        .filter(
            RoomAssignment.reservation_id == reservation_id,
            RoomAssignment.room_id == room.id,
            RoomAssignment.room_password_prefixed.isnot(None),
            RoomAssignment.room_password_prefixed != "",
        )
        .first()
    )
    if same_res and same_res.room_password_prefixed:
        return same_res.room_password_prefixed

    # P3: 신규 생성
    return build_prefixed_password(room)


def _compact_bed_orders_in_cells(db: Session, cells) -> int:
    """삭제로 생긴 bed_order 갭을 메우기 위해 (room_id, date) 셀별로 1부터 재정렬.

    cells: iterable of (room_id, date_str) tuples — 방금 삭제된 RoomAssignment가
    속해 있던 셀들. 도미토리 방만 대상 (일반실은 무시).

    기존 점유자들의 **상대 순서는 유지**하고 (bed_order ASC, created_at ASC),
    번호만 1..N으로 다시 매긴다.

    반환: 변경된 레코드 수.
    """
    if not cells:
        return 0
    normalized = {(rid, d) for rid, d in cells if rid is not None and d}
    if not normalized:
        return 0

    room_ids = {rid for rid, _ in normalized}
    dorm_ids = {
        r.id for r in
        db.query(Room).filter(Room.id.in_(room_ids), Room.is_dormitory == True).all()
    }
    if not dorm_ids:
        return 0

    changed = 0
    for room_id, date_str in normalized:
        if room_id not in dorm_ids:
            continue

        remaining = (
            db.query(RoomAssignment)
            .filter(
                RoomAssignment.room_id == room_id,
                RoomAssignment.date == date_str,
                RoomAssignment.bed_order > 0,
            )
            .order_by(RoomAssignment.bed_order.asc(), RoomAssignment.created_at.asc())
            .all()
        )
        for idx, ra in enumerate(remaining, start=1):
            if ra.bed_order != idx:
                ra.bed_order = idx
                changed += 1

    if changed:
        try:
            diag(
                "compact_bed_orders",
                level="verbose",
                cells_count=len(normalized),
                changed=changed,
            )
        except Exception:
            pass

    return changed


def _compute_bed_order(db: Session, reservation_id: int, room_id: int, date_str: str, room_obj: Room) -> int:
    """도미토리 배정 시 bed_order를 계산한다.

    1. 전날 같은 방에 같은 reservation_id 배정 → 그 bed_order 재사용
    2. 전날 같은 방에 같은 stay_group_id 배정 → 그 bed_order 재사용
    3. 둘 다 없으면 → 해당 room+date의 기존 bed_order 중 빈 슬롯 (1부터)
    """
    if not room_obj.is_dormitory:
        return 0

    prev_date = (datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")

    # 1) 같은 reservation_id로 전날 같은 방 배정 확인 (2박+ 단일 예약)
    prev_same = db.query(RoomAssignment).filter(
        RoomAssignment.reservation_id == reservation_id,
        RoomAssignment.room_id == room_id,
        RoomAssignment.date == prev_date,
    ).first()
    if prev_same and prev_same.bed_order > 0:
        return prev_same.bed_order

    # 2) stay_group_id로 전날 같은 방 배정 확인 (연박 체인)
    reservation = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if reservation and reservation.stay_group_id:
        group_members = db.query(Reservation.id).filter(
            Reservation.stay_group_id == reservation.stay_group_id,
            Reservation.id != reservation_id,
        ).all()
        member_ids = [m.id for m in group_members]
        if member_ids:
            prev_group = db.query(RoomAssignment).filter(
                RoomAssignment.reservation_id.in_(member_ids),
                RoomAssignment.room_id == room_id,
                RoomAssignment.date == prev_date,
            ).first()
            if prev_group and prev_group.bed_order > 0:
                return prev_group.bed_order

    # 3) 빈 슬롯 찾기: 해당 room+date + 전날 연박자의 bed_order도 예약으로 간주
    taken = {
        row.bed_order for row in
        db.query(RoomAssignment.bed_order).filter(
            RoomAssignment.room_id == room_id,
            RoomAssignment.date == date_str,
            RoomAssignment.bed_order > 0,
        ).all()
    }
    # 전날 같은 방의 연박자 bed_order도 taken에 포함 (다음날 배정이 아직 안 만들어진 경우 대비)
    prev_assignments = db.query(RoomAssignment.bed_order, RoomAssignment.reservation_id).filter(
        RoomAssignment.room_id == room_id,
        RoomAssignment.date == prev_date,
        RoomAssignment.bed_order > 0,
    ).all()
    for pa in prev_assignments:
        prev_res = db.query(Reservation).filter(Reservation.id == pa.reservation_id).first()
        if prev_res and prev_res.check_out_date and prev_res.check_out_date > date_str:
            taken.add(pa.bed_order)
    order = 1
    while order in taken:
        order += 1
    return order


def sync_sms_tags(db: Session, reservation_id: int, schedules=None) -> None:
    """
    Reconcile SMS tags for a reservation based on active TemplateSchedules.
    Thin wrapper delegating to chip_reconciler for unified matching and sync logic.
    """
    from app.services.chip_reconciler import reconcile_chips_for_reservation
    reconcile_chips_for_reservation(db, reservation_id, schedules)


# _date_range moved to services/schedule_utils.py
# to break circular dependency. Re-export for backward compatibility.
from app.services.schedule_utils import date_range as _date_range



def assign_room(
    db: Session,
    reservation_id: int,
    room_id: int,
    from_date: str,
    end_date: Optional[str] = None,
    assigned_by: str = "auto",
    skip_sms_sync: bool = False,
    created_by: Optional[str] = None,
    skip_logging: bool = False,
) -> Tuple[List[RoomAssignment], List[Dict]]:
    """
    Assign a room for date range [from_date, end_date).
    Creates RoomAssignment records for each date.
    For non-dormitory rooms, uses SELECT FOR UPDATE to prevent double-booking.
    Does NOT overwrite records for dates before from_date.

    Returns (assignments, pushed_out) where pushed_out is a list of
    {reservation_id, customer_name, date, cause} entries for callers that
    want to surface user-facing warnings.
    """
    reservation = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not reservation:
        raise ValueError(f"Reservation {reservation_id} not found")

    room_obj = db.query(Room).filter(
        Room.id == room_id, Room.is_active == True, Room.is_hidden == False
    ).first()
    if not room_obj:
        raise ValueError("Room not found")

    dates = _date_range(from_date, end_date)
    is_dorm = room_obj.is_dormitory

    diag(
        "assign_room.enter",
        level="verbose",
        res_id=reservation_id,
        room_id=room_id,
        from_date=from_date,
        end_date=end_date,
        dates_count=len(dates),
        assigned_by=assigned_by,
        is_dorm=is_dorm,
    )

    # H-A: today_str은 함수 진입 시 1회 계산 (루프 내 TZ 재계산 방지)
    today_str = today_kst()

    # base 비밀번호: Room.door_password 단순 복사 (변형 없음)
    password = room_obj.door_password or ""
    # prefix 붙은 표시용 비밀번호: P1/P2/P3 재사용 규칙으로 결정
    #   도미토리/복수 배정 공유, 연박자 안전망, 신규 생성 분기
    password_prefixed = _resolve_prefixed_password(db, room_obj, reservation_id, dates)

    pushed_out: List[Dict] = []

    # Concurrency guard for non-dormitory rooms
    if not is_dorm:
        for d in dates:
            existing = (
                db.query(RoomAssignment)
                .filter(
                    RoomAssignment.date == d,
                    RoomAssignment.room_id == room_id,
                    RoomAssignment.reservation_id != reservation_id,
                )
                .with_for_update()
                .first()
            )
            if not existing:
                continue

            if assigned_by == "auto":
                raise ValueError(
                    f"Room {room_obj.room_number} is already occupied on {d} by reservation {existing.reservation_id}"
                )

            # 수동 배정은 오늘/미래 구분 없이 공동 점유 허용.
            # RoomAssignment unique 는 (reservation_id, date) 만이라 같은 (room_id, date) 에
            # 여러 reservation 안전. 자동 배정은 위에서 raise 처리됨.
            logger.info(
                f"Manual multi-assign: room {room_obj.room_number} on {d} "
                f"existing res={existing.reservation_id}, adding res={reservation_id}"
            )
            diag(
                "assign_room.manual_multi_assign",
                level="verbose",
                res_id=reservation_id,
                room_id=room_id,
                date=d,
                existing_res_id=existing.reservation_id,
            )

    # Dormitory manual-assignment hardline check (1-5)
    if is_dorm and assigned_by == "manual":
        new_gender = (reservation.gender or "").strip()
        new_count = reservation.party_size or reservation.booking_count or 1

        # C-B 배치 최적화: 미래 날짜들의 others를 한 번에 조회
        future_dates = [d for d in dates if d > today_str]
        if future_dates:
            all_others = db.query(RoomAssignment).filter(
                RoomAssignment.room_id == room_id,
                RoomAssignment.date.in_(future_dates),
                RoomAssignment.reservation_id != reservation_id,
            ).all()

            other_res_ids = {o.reservation_id for o in all_others}
            other_res_map: Dict[int, Reservation] = {}
            if other_res_ids:
                other_res_map = {
                    r.id: r for r in db.query(Reservation).filter(
                        Reservation.id.in_(other_res_ids)
                    ).all()
                }

            others_by_date: Dict[str, List[RoomAssignment]] = defaultdict(list)
            for o in all_others:
                others_by_date[o.date].append(o)

            all_pushed_res_ids: set = set()
            pushed_dates_for_surcharge: Dict[int, set] = defaultdict(set)

            for d in sorted(future_dates):
                others = others_by_date.get(d, [])
                if not others:
                    continue

                # 혼성 체크
                gender_conflict = False
                if new_gender:
                    for o_ra in others:
                        o_res = other_res_map.get(o_ra.reservation_id)
                        o_gender = (o_res.gender or "").strip() if o_res else ""
                        if o_gender and o_gender != new_gender:
                            gender_conflict = True
                            break

                # 용량 체크
                total_occupancy = 0
                for o_ra in others:
                    o_res = other_res_map.get(o_ra.reservation_id)
                    if o_res:
                        total_occupancy += (
                            o_res.party_size or o_res.booking_count or 1
                        )
                    else:
                        total_occupancy += 1
                capacity_exceeded = (
                    (total_occupancy + new_count) > (room_obj.bed_capacity or 1)
                )

                if not (gender_conflict or capacity_exceeded):
                    continue

                reason = "gender_mix" if gender_conflict else "capacity"
                pushed_res_ids_this_date = [o.reservation_id for o in others]

                # C-D: savepoint로 날짜별 격리
                savepoint = db.begin_nested()
                try:
                    for o_ra in others:
                        o_res = other_res_map.get(o_ra.reservation_id)
                        if o_res:
                            o_res.section = "unassigned"
                        db.delete(o_ra)
                        all_pushed_res_ids.add(o_ra.reservation_id)
                        pushed_dates_for_surcharge[o_ra.reservation_id].add(d)
                    db.flush()
                    # 잔여 점유자 bed_order 갭 제거 (새 예약 삽입 전에 선행)
                    _compact_bed_orders_in_cells(db, {(room_id, d)})
                    diag(
                        "assign_room.pushed_out_compact",
                        level="verbose",
                        room_id=room_id,
                        date=d,
                        pushed_count=len(others),
                        caused_by=reservation_id,
                    )
                    savepoint.commit()
                except Exception as e:
                    savepoint.rollback()
                    logger.error(
                        f"Dorm hardline savepoint failed for room={room_id} date={d}: {e}"
                    )
                    continue

                log_activity(
                    db, type="room_move",
                    title=f"도미토리 제약 충돌 — {len(others)}명 미배정 이동 ({d})",
                    detail={
                        "room_id": room_id,
                        "date": d,
                        "reason": reason,
                        "pushed_count": len(others),
                        "pushed_reservation_ids": pushed_res_ids_this_date,
                        "caused_by_reservation_id": reservation_id,
                        "caused_by_customer": reservation.customer_name,
                    },
                    created_by="system",
                )
                diag(
                    "dormitory.hardline",
                    level="critical",
                    room_id=room_id,
                    date=d,
                    reason=reason,
                    pushed_count=len(others),
                    caused_by=reservation_id,
                )

                for o_ra in others:
                    o_res = other_res_map.get(o_ra.reservation_id)
                    pushed_out.append({
                        "reservation_id": o_ra.reservation_id,
                        "customer_name": o_res.customer_name if o_res else "?",
                        "date": d,
                        "cause": reason,
                    })

            # C-B: unique reservation별 1회 sync_sms_tags (중복 제거)
            for p_id in all_pushed_res_ids:
                try:
                    sync_sms_tags(db, p_id)
                except Exception as e:
                    logger.warning(f"Dorm push-out sync_sms_tags failed for res={p_id}: {e}")

            # surcharge / room_upgrade_review 는 (res_id, date) 단위 — 각각 정리
            for p_id, p_dates in pushed_dates_for_surcharge.items():
                for p_date in p_dates:
                    try:
                        from app.services.surcharge import _delete_all_surcharge_chips
                        _delete_all_surcharge_chips(db, p_id, p_date)
                    except Exception as e:
                        logger.warning(
                            f"Dorm push-out surcharge cleanup failed for res={p_id} date={p_date}: {e}"
                        )
                    try:
                        from app.services.room_upgrade_review import _delete_all_room_upgrade_review_chips
                        from app.services.room_upgrade_promise import _delete_all_room_upgrade_promise_chips
                        _delete_all_room_upgrade_review_chips(db, p_id, p_date)
                        _delete_all_room_upgrade_promise_chips(db, p_id, p_date)
                    except Exception as e:
                        logger.warning(
                            f"Dorm push-out room_upgrade cleanup failed for res={p_id} date={p_date}: {e}"
                        )

    # Capture old room for move logging
    old_assignments = (
        db.query(RoomAssignment)
        .filter(
            RoomAssignment.reservation_id == reservation_id,
            RoomAssignment.date.in_(dates),
        )
        .all()
    )
    old_room_display = old_assignments[0].room.room_number if old_assignments and old_assignments[0].room else None

    # Delete existing assignments for this reservation in the date range (현재 테넌트만)
    tid = get_session_tenant_id(db)
    db.query(RoomAssignment).filter(
        RoomAssignment.reservation_id == reservation_id,
        RoomAssignment.date.in_(dates),
        RoomAssignment.tenant_id == tid,
    ).delete(synchronize_session="fetch")

    new_room_display = room_obj.room_number

    # Log room move/assignment (skip when caller will log in bulk)
    if not skip_logging:
        log_creator = created_by or ("system" if assigned_by == "auto" else assigned_by)
        if old_room_display and old_room_display != new_room_display:
            log_activity(
                db, type="room_move",
                title=f"[{reservation.customer_name}] 객실이동 {old_room_display} → {new_room_display}",
                detail={
                    "reservation_id": reservation_id,
                    "move_type": assigned_by,
                    "customer_name": reservation.customer_name,
                    "dates": dates,
                    "old_room": old_room_display,
                    "new_room": new_room_display,
                },
                created_by=log_creator,
            )
        elif not old_room_display:
            log_activity(
                db, type="room_move",
                title=f"[{reservation.customer_name}] 객실배정 {new_room_display}",
                detail={
                    "reservation_id": reservation_id,
                    "move_type": assigned_by,
                    "customer_name": reservation.customer_name,
                    "dates": dates,
                    "old_room": None,
                    "new_room": new_room_display,
                },
                created_by=log_creator,
            )

    # Create new assignments
    assignments = []
    for d in dates:
        bed_order = _compute_bed_order(db, reservation_id, room_id, d, room_obj)
        assignment = RoomAssignment(
            reservation_id=reservation_id,
            date=d,
            room_id=room_id,
            room_password=password,
            room_password_prefixed=password_prefixed,
            assigned_by=assigned_by,
            bed_order=bed_order,
        )
        db.add(assignment)
        db.flush()  # 다음 날짜 계산에서 이 레코드가 보이도록
        assignments.append(assignment)

    # Flush to persist all date records before any subsequent queries
    db.flush()
    logger.info(f"assign_room: res={reservation_id} room={room_id} dates={dates} created={len(assignments)} assigned_by={assigned_by}")

    # Update section field
    reservation.section = 'room'

    # ★ 칩 reconcile (2차): 방 배정 후 재실행
    # 이제 RoomAssignment 있으므로 building/room 필터 통과 → 칩 생성됨
    # skip_sms_sync=True이면 건너뜀 (일괄 처리 시 사용)
    if not skip_sms_sync:
        db.flush()
        from app.services.reconcile import reconcile_all_chips
        reconcile_all_chips(db, reservation_id, dates=dates, room_id=room_id)

    # ★ H-F 제거 (2026-04-21): push-out 후 즉시 재배정 트리거는 불필요.
    # 미래 날짜에만 push-out 발생 → 밀려난 예약자는 미배정 상태로 대기 →
    # 해당 날짜가 오늘/내일이 되면 10:01 daily_assign_rooms 스케줄러가 자동 재배정.
    # 즉시 재배정은 쿼리 폭증 + 복잡도 증가만 유발하여 제거.
    if pushed_out:
        affected_dates = sorted({p["date"] for p in pushed_out})
        diag(
            "pushed_out.awaiting_scheduler",
            level="critical",
            affected_dates=",".join(affected_dates),
            caused_by=reservation_id,
        )

    diag(
        "assign_room.exit",
        level="verbose",
        res_id=reservation_id,
        room_id=room_id,
        created=len(assignments),
        pushed_count=len(pushed_out),
    )

    return assignments, pushed_out


def unassign_room(
    db: Session,
    reservation_id: int,
    from_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> int:
    """
    Remove room assignments for a reservation.
    If from_date is None, clears ALL assignments.
    If from_date provided, clears [from_date, end_date) range.
    Returns count of deleted records.
    """
    reservation = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not reservation:
        return 0

    diag(
        "unassign_room.enter",
        level="verbose",
        res_id=reservation_id,
        from_date=from_date,
        end_date=end_date,
    )

    query = db.query(RoomAssignment).filter(
        RoomAssignment.reservation_id == reservation_id
    )

    if from_date:
        dates = _date_range(from_date, end_date)
        query = query.filter(RoomAssignment.date.in_(dates))

    # Capture old room for unassign logging
    old_assignments = query.all()
    if old_assignments:
        old_room_display = old_assignments[0].room.room_number if old_assignments[0].room else None
        old_assigned_by = old_assignments[0].assigned_by
        log_activity(
            db, type="room_move",
            title=f"[{reservation.customer_name}] 객실해제 {old_room_display}",
            detail={
                "reservation_id": reservation_id,
                "move_type": old_assigned_by,
                "customer_name": reservation.customer_name,
                "dates": [a.date for a in old_assignments],
                "old_room": old_room_display,
                "new_room": None,
            },
            created_by="system" if old_assigned_by == "auto" else old_assigned_by,
        )

    # Re-query since .all() consumed the query (현재 테넌트만)
    tid = get_session_tenant_id(db)
    query = db.query(RoomAssignment).filter(
        RoomAssignment.reservation_id == reservation_id,
        RoomAssignment.tenant_id == tid,
    )
    if from_date:
        query = query.filter(RoomAssignment.date.in_(dates))

    affected_cells = {(ra.room_id, ra.date) for ra in old_assignments if ra.room_id}
    count = query.delete(synchronize_session="fetch")
    if affected_cells:
        db.flush()
        compacted = _compact_bed_orders_in_cells(db, affected_cells)
        if compacted:
            diag(
                "unassign_room.compact",
                level="verbose",
                res_id=reservation_id,
                cells_count=len(affected_cells),
                changed=compacted,
            )

    # section과 SMS 태그는 호출자가 관리 (PUT endpoint → sync_sms_tags)

    # Surcharge / room_upgrade_promise / room_upgrade_review 칩 정리 (방 해제 시)
    try:
        from app.services.surcharge import _delete_all_surcharge_chips
        from app.services.room_upgrade_review import _delete_all_room_upgrade_review_chips
        from app.services.room_upgrade_promise import _delete_all_room_upgrade_promise_chips
        cleanup_dates = dates if from_date else _date_range(reservation.check_in_date, reservation.check_out_date)
        for d in cleanup_dates:
            _delete_all_surcharge_chips(db, reservation_id, d)
            _delete_all_room_upgrade_promise_chips(db, reservation_id, d)
            _delete_all_room_upgrade_review_chips(db, reservation_id, d)
    except Exception as e:
        logger.warning(f"Surcharge/room_upgrade cleanup failed for res={reservation_id}: {e}")

    diag(
        "unassign_room.exit",
        level="verbose",
        res_id=reservation_id,
        deleted=count,
    )

    return count


def unassign_dates(db: Session, reservation_id: int, dates: list[str]) -> int:
    """특정 날짜 목록의 RoomAssignment 삭제 + bed_order 재정렬 + 칩 cleanup.

    `unassign_room` (range 기반) 과 달리 비연속 날짜 list 를 받음.
    사용처 (lifecycle 마이그레이션 단계 #3, #4):
      - `_do_reduce_extension` 의 dates_to_remove
      - `naver_sync` cc1 의 affected_dates

    log_activity 는 호출자가 자체 diag/로깅 보유한다고 가정 — 중복 회피.
    """
    if not dates:
        return 0

    reservation = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not reservation:
        return 0

    diag(
        "unassign_dates.enter",
        level="verbose",
        res_id=reservation_id,
        dates_count=len(dates),
    )

    tid = get_session_tenant_id(db)
    query = db.query(RoomAssignment).filter(
        RoomAssignment.reservation_id == reservation_id,
        RoomAssignment.tenant_id == tid,
        RoomAssignment.date.in_(dates),
    )
    old_assignments = query.all()
    affected_cells = {(ra.room_id, ra.date) for ra in old_assignments if ra.room_id}

    count = query.delete(synchronize_session="fetch")
    if affected_cells:
        db.flush()
        compacted = _compact_bed_orders_in_cells(db, affected_cells)
        if compacted:
            diag(
                "unassign_dates.compact",
                level="verbose",
                res_id=reservation_id,
                cells_count=len(affected_cells),
                changed=compacted,
            )

    # Surcharge / room_upgrade_promise / room_upgrade_review 칩 정리 — unassign_room 과 동일 패턴
    try:
        from app.services.surcharge import _delete_all_surcharge_chips
        from app.services.room_upgrade_review import _delete_all_room_upgrade_review_chips
        from app.services.room_upgrade_promise import _delete_all_room_upgrade_promise_chips
        for d in dates:
            _delete_all_surcharge_chips(db, reservation_id, d)
            _delete_all_room_upgrade_promise_chips(db, reservation_id, d)
            _delete_all_room_upgrade_review_chips(db, reservation_id, d)
    except Exception as e:
        logger.warning(f"Surcharge/room_upgrade cleanup failed for res={reservation_id}: {e}")

    diag(
        "unassign_dates.exit",
        level="verbose",
        res_id=reservation_id,
        deleted=count,
    )

    return count


def clear_all_for_reservation(db: Session, reservation_id: int) -> int:
    """Delete ALL RoomAssignment records for a reservation and clear denormalized fields."""
    diag("clear_all_for_reservation.enter", level="verbose", res_id=reservation_id)
    reservation = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    tid = get_session_tenant_id(db)

    # 삭제 전에 (room_id, date) 수집 — 삭제 후 bed_order 재정렬에 사용
    to_delete = (
        db.query(RoomAssignment)
        .filter(RoomAssignment.reservation_id == reservation_id, RoomAssignment.tenant_id == tid)
        .all()
    )
    affected_cells = {(ra.room_id, ra.date) for ra in to_delete if ra.room_id}

    count = (
        db.query(RoomAssignment)
        .filter(RoomAssignment.reservation_id == reservation_id, RoomAssignment.tenant_id == tid)
        .delete(synchronize_session="fetch")
    )
    if reservation:
        reservation.room_number = None
        reservation.room_password = None

    if affected_cells:
        db.flush()
        compacted = _compact_bed_orders_in_cells(db, affected_cells)
        if compacted:
            diag(
                "clear_all_for_reservation.compact",
                level="verbose",
                res_id=reservation_id,
                cells_count=len(affected_cells),
                changed=compacted,
            )

    # section과 SMS 태그는 호출자가 관리

    diag("clear_all_for_reservation.exit", level="verbose", res_id=reservation_id, deleted=count)
    return count


def sync_denormalized_field(db: Session, reservation: Reservation):
    """DEPRECATED: Phase 3-1 이후 미사용. Reservation.room_number/password는
    clear_all_for_reservation의 cleanup 외에는 쓰지 않음. 호출 제거됨."""
    assignment = (
        db.query(RoomAssignment)
        .filter(
            RoomAssignment.reservation_id == reservation.id,
            RoomAssignment.date == reservation.check_in_date,
        )
        .first()
    )
    if assignment:
        room = db.query(Room).filter(Room.id == assignment.room_id).first()
        reservation.room_number = room.room_number if room else None
        reservation.room_password = assignment.room_password
    else:
        # Check if any assignment exists (for mid-stay changes)
        first_assignment = (
            db.query(RoomAssignment)
            .filter(RoomAssignment.reservation_id == reservation.id)
            .order_by(RoomAssignment.date)
            .first()
        )
        if first_assignment:
            room = db.query(Room).filter(Room.id == first_assignment.room_id).first()
            reservation.room_number = room.room_number if room else None
            reservation.room_password = first_assignment.room_password
        else:
            reservation.room_number = None
            reservation.room_password = None


def _shift_daily_records(
    db: Session,
    reservation: Reservation,
    old_check_in: Optional[str],
    old_check_out: Optional[str],
) -> dict:
    """예약 날짜 변경 시 ReservationDailyInfo / PartyCheckin 을 상대 인덱스로 평행이동.

    매핑: new_date = old_date + (new_check_in - old_check_in)
    새 [check_in, check_out) 범위 밖으로 떨어지는 레코드는 버린다.
    UNIQUE(reservation_id, date) 충돌을 피하려고 스냅샷 → 삭제 → 재삽입 순서.
    체크인이 없거나 파싱 불가능하면 no-op.
    """
    from app.db.models import ReservationDailyInfo, PartyCheckin

    new_check_in = reservation.check_in_date
    new_check_out = reservation.check_out_date
    if not (old_check_in and new_check_in and new_check_out):
        return {"shifted": 0, "dropped": 0}

    try:
        shift_days = (
            datetime.strptime(new_check_in, "%Y-%m-%d")
            - datetime.strptime(old_check_in, "%Y-%m-%d")
        ).days
    except Exception:
        return {"shifted": 0, "dropped": 0}

    valid_dates = set(_date_range(new_check_in, new_check_out))
    tid = get_session_tenant_id(db)

    summary = {"shifted": 0, "dropped": 0}
    excluded = {"id", "date", "created_at", "updated_at"}

    for Model in (ReservationDailyInfo, PartyCheckin):
        records = (
            db.query(Model)
            .filter(
                Model.reservation_id == reservation.id,
                Model.tenant_id == tid,
            )
            .all()
        )
        if not records:
            continue
        snapshots = []
        for r in records:
            try:
                new_date = (
                    datetime.strptime(r.date, "%Y-%m-%d")
                    + timedelta(days=shift_days)
                ).strftime("%Y-%m-%d")
            except Exception:
                continue
            if new_date in valid_dates:
                data = {
                    col.name: getattr(r, col.name)
                    for col in Model.__table__.columns
                    if col.name not in excluded
                }
                data["date"] = new_date
                snapshots.append(data)
                summary["shifted"] += 1
            else:
                summary["dropped"] += 1
            db.delete(r)
        db.flush()
        for data in snapshots:
            db.add(Model(**data))
        db.flush()

    if summary["shifted"] or summary["dropped"]:
        diag(
            "shift_daily_records",
            level="info",
            res_id=reservation.id,
            old_check_in=old_check_in,
            new_check_in=new_check_in,
            shift_days=shift_days,
            shifted=summary["shifted"],
            dropped=summary["dropped"],
        )
    return summary


def _reconcile_dates(db: Session, reservation: Reservation):
    """
    Called when reservation dates change.
    - Deletes assignments for dates no longer in [check_in, check_out) range.
    - NEW (Phase 1-1): For missing dates inside the valid range (extension),
      auto-creates RoomAssignment by copying the nearest existing assignment.
      Applies X3 push-out: future-date conflicts are evicted (long-stay priority).
      Recomputes bed_order and reconciles surcharge for the new dates.
    """
    valid_dates = set(_date_range(reservation.check_in_date, reservation.check_out_date))

    if not valid_dates:
        # check_in_date가 없는 비정상 데이터 — 삭제하지 않고 스킵
        logger.warning(f"reconcile_dates: reservation {reservation.id} has no valid dates, skipping")
        return

    today_str = today_kst()
    tid = get_session_tenant_id(db)

    diag(
        "reconcile_dates.enter",
        level="verbose",
        res_id=reservation.id,
        check_in=reservation.check_in_date,
        check_out=reservation.check_out_date,
    )

    # 1) 범위 밖 삭제 (기존 로직)
    orphaned = (
        db.query(RoomAssignment)
        .filter(
            RoomAssignment.reservation_id == reservation.id,
            RoomAssignment.tenant_id == tid,
            ~RoomAssignment.date.in_(valid_dates),
        )
        .all()
    )

    orphaned_cells = {(a.room_id, a.date) for a in orphaned if a.room_id}
    for assignment in orphaned:
        if assignment.date not in valid_dates:
            db.delete(assignment)
    if orphaned_cells:
        db.flush()
        compacted = _compact_bed_orders_in_cells(db, orphaned_cells)
        if compacted:
            diag(
                "reconcile_dates.orphan_compact",
                level="verbose",
                res_id=reservation.id,
                cells_count=len(orphaned_cells),
                changed=compacted,
            )

    # 2) 범위 내 누락 날짜 채우기 (Phase 1-1)
    existing = (
        db.query(RoomAssignment)
        .filter(
            RoomAssignment.reservation_id == reservation.id,
            RoomAssignment.tenant_id == tid,
            RoomAssignment.date.in_(valid_dates),
        )
        .all()
    )
    existing_dates = {a.date for a in existing}
    missing = valid_dates - existing_dates

    inserted_count = 0

    if missing and existing:
        # 같은 reservation의 가장 가까운 배정을 reference로 선택 (방 유지)
        try:
            reference = min(
                existing,
                key=lambda a: abs(
                    (datetime.strptime(a.date, "%Y-%m-%d")
                     - datetime.strptime(reservation.check_in_date, "%Y-%m-%d")).days
                ),
            )
        except Exception:
            reference = existing[0]

        ref_room = db.query(Room).filter(Room.id == reference.room_id).first()

        for d in sorted(missing):
            # X3 수정: 충돌 체크 — 일반실은 FOR UPDATE로 동시성 보호
            conflict_query = db.query(RoomAssignment).filter(
                RoomAssignment.room_id == reference.room_id,
                RoomAssignment.date == d,
                RoomAssignment.reservation_id != reservation.id,
            )
            if ref_room and not ref_room.is_dormitory:
                conflict_query = conflict_query.with_for_update()
            conflicts = conflict_query.all()

            if conflicts:
                # 공동 점유 — 연박 연장 시에도 기존자를 밀어내지 않음.
                # RoomAssignment unique 가 (reservation_id, date) 만이라 같은 셀에 공존 안전.
                logger.info(
                    f"reconcile_dates: co-occupy on {d} with "
                    f"{[c.reservation_id for c in conflicts]} for res={reservation.id}"
                )
                diag(
                    "reconcile_dates.co_occupy",
                    level="verbose",
                    res_id=reservation.id,
                    date=d,
                    existing_res_ids=[c.reservation_id for c in conflicts],
                    room_id=reference.room_id,
                )

            # 새 RoomAssignment INSERT (bed_order 재계산)
            bed_order = (
                _compute_bed_order(db, reservation.id, reference.room_id, d, ref_room)
                if ref_room else 0
            )
            new_ra = RoomAssignment(
                reservation_id=reservation.id,
                date=d,
                room_id=reference.room_id,
                room_password=reference.room_password,
                room_password_prefixed=reference.room_password_prefixed,
                assigned_by=reference.assigned_by,
                bed_order=bed_order,
            )
            db.add(new_ra)
            db.flush()
            inserted_count += 1

    if orphaned or missing:
        # 칩 통합 재계산 (일반 + surcharge + party3 MMS)
        try:
            from app.services.reconcile import reconcile_all_chips
            reconcile_all_chips(db, reservation.id)
        except Exception as e:
            logger.warning(f"reconcile_dates reconcile_all_chips failed for res={reservation.id}: {e}")
        logger.info(
            f"Reconciled dates for reservation {reservation.id}: "
            f"removed {len(orphaned)} orphaned, inserted {inserted_count} missing"
        )

    diag(
        "reconcile_dates.exit",
        level="verbose",
        res_id=reservation.id,
        deleted=len(orphaned),
        inserted=inserted_count,
    )


def check_capacity_all_dates(
    db: Session,
    room_id: int,
    from_date: str,
    end_date: Optional[str],
    people_count: int = 1,
    exclude_reservation_id: Optional[int] = None,
) -> bool:
    """
    Check if a room has capacity for ALL dates in [from_date, end_date).
    Used by auto-assign to ensure multi-night guests get the same room every night.
    Note: For non-dormitory rooms, capacity is hardcoded to 1 (auto-assign policy).
    Manual assignments bypass this check via assign_room()'s assigned_by guard.
    """
    room = db.query(Room).filter(
        Room.id == room_id, Room.is_active == True, Room.is_hidden == False
    ).first()
    if not room:
        return False

    dates = _date_range(from_date, end_date)
    is_dorm = room.is_dormitory
    capacity = room.bed_capacity if is_dorm else 1

    if is_dorm:
        # Batch: fetch occupancy for all dates in one JOIN + GROUP BY query
        agg_query = (
            db.query(
                RoomAssignment.date,
                func.coalesce(
                    func.sum(
                        func.coalesce(Reservation.party_size, Reservation.booking_count, 1)
                    ),
                    0,
                ).label("occupancy"),
            )
            .join(Reservation, and_(RoomAssignment.reservation_id == Reservation.id, RoomAssignment.tenant_id == Reservation.tenant_id))
            .filter(
                RoomAssignment.room_id == room_id,
                RoomAssignment.date.in_(dates),
            )
        )
        if exclude_reservation_id:
            agg_query = agg_query.filter(RoomAssignment.reservation_id != exclude_reservation_id)
        occupancy_map = {row.date: row.occupancy for row in agg_query.group_by(RoomAssignment.date).all()}

        for d in dates:
            current = occupancy_map.get(d, 0)
            if current + people_count > capacity:
                return False
    else:
        for d in dates:
            query = db.query(RoomAssignment).filter(
                RoomAssignment.date == d,
                RoomAssignment.room_id == room_id,
            )
            if exclude_reservation_id:
                query = query.filter(RoomAssignment.reservation_id != exclude_reservation_id)
            if query.count() >= capacity:
                return False

    return True

"""
Shared Naver reservation sync logic.
Used by both the API endpoint and the scheduler job.
"""
from datetime import datetime, timezone
from typing import Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
import logging

import re

from app.db.models import Reservation, ReservationStatus, ReservationSmsAssignment, NaverBizItem, RoomBizItemLink, Room
from app.services import room_assignment
from app.services.consecutive_stay import compute_is_long_stay
from app.services.room_auto_assign import auto_assign_rooms
from app.config import KST

logger = logging.getLogger(__name__)


def _parse_gender_from_custom_form(text: str, total: int = 0) -> tuple[int, int] | None:
    """Parse gender counts from free-form text like '남 24 여 25 남 21'.
    Returns (male_count, female_count) or None if unparseable.
    total > 0이면 파싱 결과 합이 total과 일치할 때만 반환 (보조 도구).
    '남자'를 '남'보다 먼저 매칭하여 중복 카운트 방지."""
    if not text or not text.strip():
        return None
    males = len(re.findall(r'남자|남', text))
    females = len(re.findall(r'여자|여', text))
    if males == 0 and females == 0:
        return None
    # total이 지정되면 파싱 결과와 일치할 때만 신뢰
    if total > 0 and males + females != total:
        return None
    return (males, females)


def _parse_datetime(value: str | None) -> datetime | None:
    """Parse ISO datetime string to datetime, returning None on failure."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        return None


async def sync_naver_to_db(reservation_provider, db: Session, target_date=None, from_date: str = None, reconcile_date: str = None, source: str = "stable") -> Dict[str, Any]:
    """
    [Phase 1~5 메인 함수] 네이버 예약 수신 → DB 저장 → 칩 생성 → 연박 감지 → 자동 배정.

    Phase 1: reservation_provider.get_reservations() — 네이버 API에서 예약 가져오기
    Phase 2: enrichment(biz_name/people_count/gender) + _create_reservation/_update_reservation
    Phase 3: reconcile_chips_for_reservation (1차) — 방 미배정 상태, building 칩 미생성
    Phase 4: detect_and_link_consecutive_stays — 연박 그룹 링크
    Phase 5: auto_assign_rooms → assign_room() → reconcile (2차) — building 칩 생성

    Args:
        from_date: Optional start date (YYYY-MM-DD) for historical sync.
        reconcile_date: Optional check-in date (YYYY-MM-DD) for reconciliation.
                        Uses STARTDATE filter instead of REGDATE.

    Returns summary dict with synced/added/updated counts.
    """
    if reconcile_date:
        logger.info(f"Starting Naver reconciliation for check-in date: {reconcile_date}")
        raw_reservations = await reservation_provider.fetch_by_checkin_date(reconcile_date)
    else:
        logger.info(f"Starting Naver reservation sync...{f' (from {from_date})' if from_date else ''}")
        raw_reservations = await reservation_provider.sync_reservations(target_date, from_date=from_date)

    # Build lookup maps from DB (NaverBizItem + Room)
    biz_items = db.query(NaverBizItem).all()
    biz_name_map = {b.biz_item_id: (b.display_name or b.name) for b in biz_items}
    biz_section_map = {b.biz_item_id: b.section_hint for b in biz_items}
    biz_capacity_map = {b.biz_item_id: b.default_capacity for b in biz_items if b.default_capacity}

    # Build dormitory map and capacity fallback from RoomBizItemLink → Room
    biz_dormitory_map: Dict[str, bool] = {}
    links = db.query(RoomBizItemLink).join(
        Room, and_(Room.id == RoomBizItemLink.room_id, Room.tenant_id == RoomBizItemLink.tenant_id)
    ).all()
    for link in links:
        if link.biz_item_id not in biz_capacity_map:
            biz_capacity_map[link.biz_item_id] = link.room.base_capacity
        if link.room.is_dormitory:
            biz_dormitory_map[link.biz_item_id] = True

    # Deduplicate by external_id (monthly chunks can overlap)
    seen_ids = {}
    for r in raw_reservations:
        ext_id = r.get("external_id") or r.get("naver_booking_id")
        if ext_id:
            seen_ids[ext_id] = r  # keep latest
        else:
            seen_ids[id(r)] = r
    reservations = list(seen_ids.values())
    if len(reservations) != len(raw_reservations):
        logger.info(f"Deduplicated: {len(raw_reservations)} → {len(reservations)}")

    # ── Phase 2: enrichment ──
    # 네이버 상품ID → DB 매핑(상품명, 도미토리 여부, 기준인원, 섹션 힌트)으로 변환
    for res_data in reservations:
        bid = res_data.get("naver_biz_item_id", "")

        if source == "unstable":
            # 언스테이블: NaverBizItem 매핑 없음 — 직접 설정
            name = res_data.get("biz_item_name") or bid
            res_data["room_type"] = name
            res_data["biz_item_name"] = name
            # 인원: bookingCount가 곧 인원수 (도미토리와 동일 방식)
            res_data["people_count"] = res_data.get("booking_count") or 1
            # section: 항상 unstable
            res_data["_section_hint"] = "unstable"
            # 성별: customFormInputJson 파싱 → fallback으로 기존 gender(userId API)
            total = res_data["people_count"]
            parsed = _parse_gender_from_custom_form(res_data.get("custom_form_input"), total)
            if parsed:
                # 파싱 성공 = 남+여 합계가 total과 일치
                res_data["_unstable_male"] = parsed[0]
                res_data["_unstable_female"] = parsed[1]
            else:
                # fallback: userId API 성별로 전체 인원 배정
                booker_gender = res_data.get("gender", "")
                if booker_gender == "남":
                    res_data["_unstable_male"] = total
                    res_data["_unstable_female"] = 0
                elif booker_gender == "여":
                    res_data["_unstable_male"] = 0
                    res_data["_unstable_female"] = total
                # else: None으로 남겨서 _init_gender_counts fallback
        else:
            # 스테이블: 기존 로직 그대로
            name = biz_name_map.get(bid, bid)
            res_data["room_type"] = name
            res_data["biz_item_name"] = name
            # 인원 enrichment: 도미토리 vs 일반실 분기
            if biz_dormitory_map.get(bid, False):
                # 도미토리: bookingCount = 인원 (인원수 옵션 무시)
                res_data["people_count"] = res_data.get("booking_count") or 1
                res_data["_is_dormitory"] = True
            else:
                # 일반실: 인원수 옵션 우선, 없으면 기준인원(base_capacity)
                pc = res_data.get("people_count")
                if not pc:
                    res_data["people_count"] = biz_capacity_map.get(bid, 1)
            # section_hint enrichment (res_data에 저장해서 _create_reservation에서 사용)
            res_data["_section_hint"] = biz_section_map.get(bid)

    # Bulk-fetch existing reservations by external_id/naver_booking_id in one query
    all_ext_ids = [
        r.get("external_id") or r.get("naver_booking_id")
        for r in reservations
        if r.get("external_id") or r.get("naver_booking_id")
    ]
    existing_map: Dict[str, Reservation] = {}
    if all_ext_ids:
        existing_rows = (
            db.query(Reservation)
            .filter(
                or_(
                    Reservation.external_id.in_(all_ext_ids),
                    Reservation.naver_booking_id.in_(all_ext_ids),
                )
            )
            .all()
        )
        for row in existing_rows:
            if row.external_id:
                existing_map[row.external_id] = row
            if row.naver_booking_id:
                existing_map[row.naver_booking_id] = row

    # ── Phase 2 계속: DB 저장 (신규 → _create_reservation, 기존 → _update_reservation) ──
    added_count = 0
    updated_count = 0
    new_reservation_ids = []  # 칩 생성 대상: 새 예약 ID
    date_changed_ids = []  # 칩 재계산 대상: 날짜 변경 예약 ID

    for res_data in reservations:
        external_id = res_data.get("external_id") or res_data.get("naver_booking_id")
        existing = existing_map.get(external_id) if external_id else None

        if existing:
            old_dates = (existing.check_in_date, existing.check_out_date)
            _update_reservation(db, existing, res_data)
            new_dates = (existing.check_in_date, existing.check_out_date)
            if old_dates != new_dates:
                date_changed_ids.append(existing.id)
            updated_count += 1
        else:
            new_res = _create_reservation(res_data)
            db.add(new_res)
            db.flush()  # ID 즉시 할당 (commit 후 N+1 lazy reload 방지)
            new_reservation_ids.append(new_res.id)
            added_count += 1

    db.commit()

    # ── Phase 3: 칩 reconcile은 Phase 5(자동배정) 이후 1회로 통합 ──
    # 이전에는 여기서 1차 reconcile 했으나, RoomAssignment 없는 상태에서
    # building 필터 칩이 생성 안 되고 Phase 5에서 다시 돌려야 해서 2중 실행이었음.
    # 이제 Phase 5 이후 칩 reconcile 1회로 통합하여 연산 50% 감소.
    chip_target_ids = new_reservation_ids + date_changed_ids

    # ── Phase 4: 연박 감지 (같은 이름+전화의 연속 날짜 예약 → stay_group으로 링크) ──
    if added_count > 0 or updated_count > 0:
        try:
            from app.services.consecutive_stay import detect_and_link_consecutive_stays
            stay_result = detect_and_link_consecutive_stays(db)
            db.commit()
            if stay_result["linked"] > 0 or stay_result["unlinked"] > 0:
                logger.info(f"Consecutive stay detection after sync: {stay_result}")
            # ── Phase 4-b: 연박 그룹 bed_order 정합성 체크 ──
            # 새로 연결된 그룹에서 같은 방인데 bed_order가 다른 경우 통일
            if stay_result["linked"] > 0:
                _align_bed_orders_for_groups(db)
                db.flush()
        except Exception as e:
            logger.error(f"Consecutive stay detection failed: {e}")
            db.rollback()

    # ── Phase 5: 자동 객실 배정 ──
    # auto_assign_rooms → assign_room() → ★ 칩 reconcile (2차)
    # 이번에는 RoomAssignment 있으므로 building 필터 통과 → 칩 생성됨
    # reconcile 경로: 오늘 포함 / 일반 sync 경로: 내일 이후만 (오늘은 수동 배정 유지)
    if added_count > 0:
        try:
            today = datetime.now(KST).strftime("%Y-%m-%d")
            dates = set()
            for res_data in reservations:
                d = res_data.get("date")
                if reconcile_date:
                    if d and d >= today:  # reconcile: 오늘 포함
                        dates.add(d)
                else:
                    if d and d > today:   # 일반 sync: 오늘 제외
                        dates.add(d)
            assigned_total = 0
            for d in sorted(dates):
                result = auto_assign_rooms(db, d, created_by="reconcile" if reconcile_date else "sync")
                assigned_total += result.get("assigned", 0)
            if dates:
                logger.info(f"Auto-assigned {assigned_total} rooms after {'reconcile' if reconcile_date else 'sync'} (dates: {sorted(dates)})")
                db.commit()
        except Exception as e:
            logger.error(f"Auto-assign after sync failed: {e}")
            db.rollback()

    # ── Phase 5 이후: ★ 칩 reconcile (통합 1회) ──
    # Phase 5 자동배정 완료 후 RoomAssignment가 확정된 상태에서 칩 생성.
    # building/room 필터 포함 모든 스케줄 칩이 한 번에 정확하게 생성됨.
    # 자동배정 실패 예약도 여기서 building 무관 칩(hook, 후기 등)이 생성됨.
    if chip_target_ids:
        try:
            from app.services.chip_reconciler import reconcile_chips_for_reservation
            from app.db.models import TemplateSchedule
            active_schedules = db.query(TemplateSchedule).filter(TemplateSchedule.is_active == True).all()
            for res_id in chip_target_ids:
                reconcile_chips_for_reservation(db, res_id, schedules=active_schedules)
            db.commit()
        except Exception as e:
            logger.error(f"Chip reconciliation after sync failed: {e}")
            db.rollback()

    logger.info(f"Naver sync completed: {added_count} added, {updated_count} updated")

    return {
        "success": True,
        "synced": len(reservations),
        "added": added_count,
        "updated": updated_count,
        "message": f"{len(reservations)}건 조회, {added_count}건 추가, {updated_count}건 갱신",
    }


def _align_bed_orders_for_groups(db: Session):
    """연박 그룹 내 같은 방 배정의 bed_order를 통일한다.

    그룹 내 먼저 배정된 멤버의 bed_order를 기준으로,
    같은 방에 배정된 다른 멤버의 bed_order를 맞춘다.
    """
    from app.db.models import RoomAssignment, Room
    from sqlalchemy import and_

    # stay_group이 있는 예약 중 도미토리 배정이 있는 것만
    grouped = (
        db.query(Reservation)
        .filter(Reservation.stay_group_id.isnot(None))
        .all()
    )
    if not grouped:
        return

    # 그룹별로 묶기
    groups: Dict[str, list] = {}
    for res in grouped:
        groups.setdefault(res.stay_group_id, []).append(res)

    updated = 0
    for group_id, members in groups.items():
        member_ids = [m.id for m in members]

        # 이 그룹의 모든 RoomAssignment (도미토리만)
        assignments = (
            db.query(RoomAssignment)
            .join(Room, and_(Room.id == RoomAssignment.room_id, Room.tenant_id == RoomAssignment.tenant_id))
            .filter(
                RoomAssignment.reservation_id.in_(member_ids),
                Room.is_dormitory == True,
            )
            .all()
        )
        if not assignments:
            continue

        # room_id별로 그룹 내 bed_order 수집
        room_orders: Dict[int, int] = {}  # room_id → 기준 bed_order
        for a in assignments:
            if a.room_id not in room_orders and a.bed_order and a.bed_order > 0:
                room_orders[a.room_id] = a.bed_order

        # 같은 방인데 bed_order가 다른 경우 통일
        for a in assignments:
            ref = room_orders.get(a.room_id)
            if ref and a.bed_order != ref:
                a.bed_order = ref
                updated += 1

    if updated > 0:
        logger.info(f"Aligned {updated} bed_orders for stay groups")


def _init_gender_counts(res_data: Dict[str, Any]) -> tuple:
    """성별 인원 계산: gender="남" → (people_count, 0), "여" → (0, people_count), 그 외 → (None, None)."""
    # 언스테이블: customFormInputJson 파싱 결과 우선
    if "_unstable_male" in res_data:
        return (res_data["_unstable_male"], res_data["_unstable_female"])

    gender = res_data.get("gender", "")
    people = res_data.get("people_count", 1) or 1
    if gender == "남":
        return (people, 0)
    elif gender == "여":
        return (0, people)
    else:
        return (None, None)


def _create_reservation(res_data: Dict[str, Any]) -> Reservation:
    """Create a new Reservation from Naver API data."""
    try:
        status_enum = ReservationStatus(res_data.get("status", "pending"))
    except ValueError:
        status_enum = ReservationStatus.CONFIRMED

    male_count, female_count = _init_gender_counts(res_data)

    naver_room_type = res_data.get("room_type", "")
    section_hint = res_data.get("_section_hint")
    section = section_hint if section_hint in ('party', 'room', 'unstable') else 'unassigned'

    reservation = Reservation(
        external_id=res_data.get("external_id"),
        naver_booking_id=res_data.get("naver_booking_id"),
        naver_biz_item_id=res_data.get("naver_biz_item_id"),
        customer_name=res_data.get("customer_name", ""),
        phone=res_data.get("phone", ""),
        visitor_name=res_data.get("visitor_name"),
        visitor_phone=res_data.get("visitor_phone"),
        check_in_date=res_data.get("date", ""),
        check_in_time=res_data.get("time", ""),
        status=status_enum,
        booking_source="naver",
        naver_room_type=naver_room_type,
        party_size=res_data.get("people_count") or 1,
        male_count=male_count,
        female_count=female_count,
        check_out_date=res_data.get("end_date"),
        biz_item_name=res_data.get("biz_item_name"),
        booking_count=res_data.get("booking_count", 1),
        booking_options=res_data.get("booking_options"),
        special_requests=res_data.get("custom_form_input"),
        total_price=res_data.get("total_price"),
        confirmed_at=_parse_datetime(res_data.get("confirmed_at")),
        cancelled_at=_parse_datetime(res_data.get("cancelled_at")),
        gender=res_data.get("gender"),
        section=section,
    )
    reservation.is_long_stay = compute_is_long_stay(reservation)
    return reservation


def _update_reservation(db: Session, existing: Reservation, res_data: Dict[str, Any]):
    """[Phase 2] 기존 예약 갱신. 성별 인원은 gender_manual=False일 때만 재계산."""
    # Only update fields that come from Naver (don't overwrite local edits like room_number)
    existing.customer_name = res_data.get("customer_name", existing.customer_name)
    existing.phone = res_data.get("phone", existing.phone)
    existing.visitor_name = res_data.get("visitor_name", existing.visitor_name)
    existing.visitor_phone = res_data.get("visitor_phone", existing.visitor_phone)
    existing.naver_biz_item_id = res_data.get("naver_biz_item_id", existing.naver_biz_item_id)
    existing.naver_room_type = res_data.get("room_type", existing.naver_room_type)
    existing.party_size = res_data.get("people_count", existing.party_size)
    old_date = existing.check_in_date
    old_end_date = existing.check_out_date
    existing.check_in_date = res_data.get("date", existing.check_in_date)
    existing.check_in_time = res_data.get("time", existing.check_in_time)
    existing.check_out_date = res_data.get("end_date", existing.check_out_date)
    existing.biz_item_name = res_data.get("biz_item_name", existing.biz_item_name)
    existing.booking_count = res_data.get("booking_count", existing.booking_count)
    existing.booking_options = res_data.get("booking_options", existing.booking_options)
    existing.special_requests = res_data.get("custom_form_input", existing.special_requests)
    existing.total_price = res_data.get("total_price", existing.total_price)
    existing.confirmed_at = _parse_datetime(res_data.get("confirmed_at")) if res_data.get("confirmed_at") is not None else existing.confirmed_at
    existing.cancelled_at = _parse_datetime(res_data.get("cancelled_at")) if res_data.get("cancelled_at") is not None else existing.cancelled_at
    if res_data.get("gender"):
        existing.gender = res_data["gender"]
    # 성별 인원 재계산: 도미토리는 매 동기화마다, 일반실은 초기화 시에만
    if not existing.gender_manual:
        is_dormitory = res_data.get("_is_dormitory", False)
        if is_dormitory:
            # 도미토리: booking_count + gender로 항상 재계산
            male_count, female_count = _init_gender_counts(res_data)
            existing.male_count = male_count
            existing.female_count = female_count
        elif existing.male_count is None and existing.female_count is None:
            # 일반실: 최초 세팅 시에만
            male_count, female_count = _init_gender_counts(res_data)
            existing.male_count = male_count
            existing.female_count = female_count

    # Update status based on Naver status
    naver_status = res_data.get("status", "confirmed")
    if naver_status == "confirmed":
        existing.status = ReservationStatus.CONFIRMED
    elif naver_status == "cancelled":
        existing.status = ReservationStatus.CANCELLED
        # Auto-unassign room on cancellation
        room_assignment.clear_all_for_reservation(db, existing.id)
        # Delete unsent chips on cancellation
        db.query(ReservationSmsAssignment).filter(
            ReservationSmsAssignment.reservation_id == existing.id,
            ReservationSmsAssignment.sent_at.is_(None),
        ).delete(synchronize_session='fetch')
        # Remove from consecutive stay group on cancellation
        if existing.stay_group_id:
            from app.services.consecutive_stay import unlink_from_group
            unlink_from_group(db, existing.id)

    # Reconcile room assignments if dates changed
    if existing.check_in_date != old_date or existing.check_out_date != old_end_date:
        room_assignment.reconcile_dates(db, existing)

    # Recompute is_long_stay (stay_group_id may be set later by detect_and_link)
    existing.is_long_stay = compute_is_long_stay(existing)

    existing.updated_at = datetime.now(timezone.utc)

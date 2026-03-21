"""
Shared Naver reservation sync logic.
Used by both the API endpoint and the scheduler job.
"""
from datetime import datetime, timezone
from typing import Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy import or_
import logging

from app.db.models import Reservation, ReservationStatus, NaverBizItem, RoomBizItemLink, Room
from app.services import room_assignment
from app.scheduler.room_auto_assign import auto_assign_rooms

logger = logging.getLogger(__name__)


def _parse_datetime(value: str | None) -> datetime | None:
    """Parse ISO datetime string to datetime, returning None on failure."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        return None


async def sync_naver_to_db(reservation_provider, db: Session, target_date=None, from_date: str = None, reconcile_date: str = None) -> Dict[str, Any]:
    """
    Fetch reservations from Naver and upsert into DB.

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

    # Fallback: capacity from Room.base_capacity via RoomBizItemLink
    if not biz_capacity_map:
        links = db.query(RoomBizItemLink).join(Room).all()
        for link in links:
            if link.biz_item_id not in biz_capacity_map:
                biz_capacity_map[link.biz_item_id] = link.room.base_capacity

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

    # Enrich res_data with DB-based names and capacity
    for res_data in reservations:
        bid = res_data.get("naver_biz_item_id", "")
        # 이름 enrichment (DB에 없으면 biz_item_id 그대로)
        name = biz_name_map.get(bid, bid)
        res_data["room_type"] = name
        res_data["biz_item_name"] = name
        # 인원 enrichment (None이거나 1 이하일 때 DB capacity로 보정)
        pc = res_data.get("people_count") or 0
        if pc <= 1:
            cap = biz_capacity_map.get(bid, 1)
            if cap and cap > pc:
                res_data["people_count"] = cap
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

    added_count = 0
    updated_count = 0

    for res_data in reservations:
        external_id = res_data.get("external_id") or res_data.get("naver_booking_id")
        existing = existing_map.get(external_id) if external_id else None

        if existing:
            _update_reservation(db, existing, res_data)
            updated_count += 1
        else:
            new_res = _create_reservation(res_data)
            db.add(new_res)
            added_count += 1

    db.commit()

    # 연박 감지: 새/갱신 예약에 대해 연속 투숙 링크
    if added_count > 0 or updated_count > 0:
        try:
            from app.services.consecutive_stay import detect_and_link_consecutive_stays
            stay_result = detect_and_link_consecutive_stays(db)
            db.commit()
            if stay_result["linked"] > 0 or stay_result["unlinked"] > 0:
                logger.info(f"Consecutive stay detection after sync: {stay_result}")
        except Exception as e:
            logger.error(f"Consecutive stay detection failed: {e}")
            db.rollback()

    # 새 예약이 추가되었으면 자동 배정 실행
    # reconcile 경로: 오늘 포함 (reconciliation은 오늘 체크인 누락분 보완 목적)
    # 일반 sync 경로: 내일 이후만 (오늘은 수동 배정 유지)
    if added_count > 0:
        try:
            from zoneinfo import ZoneInfo
            today = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
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
        except Exception as e:
            logger.error(f"Auto-assign after sync failed: {e}")

    logger.info(f"Naver sync completed: {added_count} added, {updated_count} updated")

    return {
        "success": True,
        "synced": len(reservations),
        "added": added_count,
        "updated": updated_count,
        "message": f"{len(reservations)}건 조회, {added_count}건 추가, {updated_count}건 갱신",
    }


def _init_gender_counts(res_data: Dict[str, Any]) -> tuple:
    """Derive initial male_count/female_count from Naver gender + people_count."""
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
    section = section_hint if section_hint in ('party', 'room') else 'unassigned'

    return Reservation(
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


def _update_reservation(db: Session, existing: Reservation, res_data: Dict[str, Any]):
    """Update an existing Reservation with fresh Naver API data."""
    # Only update fields that come from Naver (don't overwrite local edits like room_number)
    existing.customer_name = res_data.get("customer_name", existing.customer_name)
    existing.phone = res_data.get("phone", existing.phone)
    existing.visitor_name = res_data.get("visitor_name")
    existing.visitor_phone = res_data.get("visitor_phone")
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
    # Only set male_count/female_count if not already manually edited
    if existing.male_count is None and existing.female_count is None:
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
        # Remove from consecutive stay group on cancellation
        if existing.stay_group_id:
            from app.services.consecutive_stay import unlink_from_group
            unlink_from_group(db, existing.id)

    # Reconcile room assignments if dates changed
    if existing.check_in_date != old_date or existing.check_out_date != old_end_date:
        room_assignment.reconcile_dates(db, existing)

    existing.updated_at = datetime.now(timezone.utc)



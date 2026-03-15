"""
Shared Naver reservation sync logic.
Used by both the API endpoint and the scheduler job.
"""
from datetime import datetime
from typing import Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy import or_
import logging

from app.db.models import Reservation, ReservationStatus
from app.services import room_assignment
from app.scheduler.room_reassign import auto_assign_rooms

logger = logging.getLogger(__name__)


async def sync_naver_to_db(reservation_provider, db: Session, target_date=None) -> Dict[str, Any]:
    """
    Fetch reservations from Naver and upsert into DB.

    Returns summary dict with synced/added/updated counts.
    """
    logger.info("Starting Naver reservation sync...")

    reservations = await reservation_provider.sync_reservations(target_date)

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

    # 새 예약이 추가되었으면 자동 배정 실행 (미배정 예약자만 대상)
    if added_count > 0:
        try:
            # 모든 미배정 예약자에 대해 자동 배정 (날짜 제한 없음)
            dates = set()
            for res_data in reservations:
                d = res_data.get("date")
                if d:
                    dates.add(d)
            assigned_total = 0
            for d in sorted(dates):
                result = auto_assign_rooms(db, d)
                assigned_total += result.get("assigned", 0)
            logger.info(f"Auto-assigned {assigned_total} rooms after sync")
        except Exception as e:
            logger.error(f"Auto-assign after sync failed: {e}")

    logger.info(f"Naver sync completed: {added_count} added, {updated_count} updated")

    return {
        "status": "success",
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

    return Reservation(
        external_id=res_data.get("external_id"),
        naver_booking_id=res_data.get("naver_booking_id"),
        naver_biz_item_id=res_data.get("naver_biz_item_id"),
        customer_name=res_data.get("customer_name", ""),
        phone=res_data.get("phone", ""),
        visitor_name=res_data.get("visitor_name"),
        visitor_phone=res_data.get("visitor_phone"),
        date=res_data.get("date", ""),
        time=res_data.get("time", ""),
        status=status_enum,
        source="naver",
        room_info=res_data.get("room_type", ""),
        party_participants=res_data.get("people_count", 1),
        male_count=male_count,
        female_count=female_count,
        end_date=res_data.get("end_date"),
        biz_item_name=res_data.get("biz_item_name"),
        booking_count=res_data.get("booking_count", 1),
        booking_options=res_data.get("booking_options"),
        custom_form_input=res_data.get("custom_form_input"),
        total_price=res_data.get("total_price"),
        confirmed_datetime=res_data.get("confirmed_datetime"),
        cancelled_datetime=res_data.get("cancelled_datetime"),
        gender=res_data.get("gender"),
    )


def _update_reservation(db: Session, existing: Reservation, res_data: Dict[str, Any]):
    """Update an existing Reservation with fresh Naver API data."""
    # Only update fields that come from Naver (don't overwrite local edits like room_number)
    existing.customer_name = res_data.get("customer_name", existing.customer_name)
    existing.phone = res_data.get("phone", existing.phone)
    existing.visitor_name = res_data.get("visitor_name")
    existing.visitor_phone = res_data.get("visitor_phone")
    existing.naver_biz_item_id = res_data.get("naver_biz_item_id", existing.naver_biz_item_id)
    existing.room_info = res_data.get("room_type", existing.room_info)
    existing.party_participants = res_data.get("people_count", existing.party_participants)
    old_date = existing.date
    old_end_date = existing.end_date
    existing.date = res_data.get("date", existing.date)
    existing.time = res_data.get("time", existing.time)
    existing.end_date = res_data.get("end_date", existing.end_date)
    existing.biz_item_name = res_data.get("biz_item_name", existing.biz_item_name)
    existing.booking_count = res_data.get("booking_count", existing.booking_count)
    existing.booking_options = res_data.get("booking_options", existing.booking_options)
    existing.custom_form_input = res_data.get("custom_form_input", existing.custom_form_input)
    existing.total_price = res_data.get("total_price", existing.total_price)
    existing.confirmed_datetime = res_data.get("confirmed_datetime", existing.confirmed_datetime)
    existing.cancelled_datetime = res_data.get("cancelled_datetime", existing.cancelled_datetime)
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

    # Reconcile room assignments if dates changed
    if existing.date != old_date or existing.end_date != old_end_date:
        room_assignment.reconcile_dates(db, existing)

    existing.updated_at = datetime.utcnow()



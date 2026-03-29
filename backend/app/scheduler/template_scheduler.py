"""
Template-based schedule execution engine
"""
import logging
from typing import List, Dict, Any
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, func

from app.db.models import TemplateSchedule, Reservation, RoomAssignment, ReservationSmsAssignment, Room, ReservationStatus
from app.services.filters import (
    apply_structural_filters as _standalone_structural_filters,
)
from app.factory import get_sms_provider_for_tenant
from app.services.sms_tracking import record_sms_sent
from app.services.activity_logger import log_activity
from app.services.event_bus import publish as publish_event
from app.db.tenant_context import current_tenant_id
from app.services.sms_sender import send_single_sms
from app.config import today_kst, today_kst_date

logger = logging.getLogger(__name__)



class TemplateScheduleExecutor:
    """Execute template-based scheduled messages"""

    def __init__(self, db: Session, tenant=None):
        self.db = db
        self.sms_provider = get_sms_provider_for_tenant(tenant)

    async def execute_schedule(self, schedule_id: int, manual: bool = False) -> Dict[str, Any]:
        """
        Execute a template schedule

        Steps:
        1. Load TemplateSchedule
        2. Filter targets based on configuration
        3. Render template for each target
        4. Send SMS (bulk)
        5. Update tracking flags
        6. Log campaign

        Returns:
            Dict with execution results
        """
        logger.info(f"Executing template schedule #{schedule_id}")

        # Load schedule
        schedule = self.db.query(TemplateSchedule).filter(
            TemplateSchedule.id == schedule_id,
            TemplateSchedule.is_active == True
        ).first()

        if not schedule:
            logger.warning(f"Schedule #{schedule_id} not found or inactive")
            return {"success": False, "error": "Schedule not found or inactive"}

        if not schedule.template or not schedule.template.is_active:
            logger.warning(f"Template for schedule #{schedule_id} not found or inactive")
            return {"success": False, "error": "Template not found or inactive"}

        try:
            # Send condition check (표준 스케줄 전용)
            if schedule.send_condition_date and schedule.send_condition_ratio is not None:
                condition_met = self._check_send_condition(schedule)
                if not condition_met:
                    schedule.last_run_at = datetime.now(timezone.utc)
                    self.db.commit()
                    logger.info(f"Schedule #{schedule_id}: send condition not met, skipping")
                    return {"success": True, "sent_count": 0, "message": "Send condition not met, skipped"}

            # Get targets
            targets = self.get_targets(schedule)
            logger.info(f"Found {len(targets)} targets for schedule #{schedule_id}")

            if not targets:
                # Update last_run even if no targets
                schedule.last_run_at = datetime.now(timezone.utc)
                self.db.commit()
                return {"success": True, "sent_count": 0, "message": "No targets found"}

            # Send messages
            sent_count = 0
            failed_count = 0
            send_results = []

            # 이벤트 스케줄: target_date를 오늘로 고정
            if (schedule.schedule_category or 'standard') == 'event':
                target_date = today_kst()
                date_target_val = None
            else:
                date_target_val = schedule.date_target
                target_date = self._resolve_date_target(date_target_val) if date_target_val else None

            # Build reservation_id -> building+room display map for log
            # Use RoomAssignment for target_date (not denormalized field)
            target_res_ids = [r.id for r in targets]
            room_building_map = {}  # reservation_id -> display string
            if target_res_ids and target_date:
                assignments = self.db.query(RoomAssignment).filter(
                    RoomAssignment.reservation_id.in_(target_res_ids),
                    RoomAssignment.date == target_date,
                ).all()
                assign_room_id_map = {ra.reservation_id: ra.room_id for ra in assignments}
                room_ids = set(assign_room_id_map.values())
                room_name_map = {}
                if room_ids:
                    rooms_with_building = self.db.query(Room).filter(Room.id.in_(room_ids)).all()
                    for rm in rooms_with_building:
                        building_name = rm.building.name if rm.building else ""
                        rn = rm.room_number or ""
                        # room_number에 이미 건물명이나 '호'가 포함된 경우 그대로 사용
                        if building_name and building_name in rn:
                            room_name_map[rm.id] = rn
                        elif building_name:
                            suffix = rn if rn.endswith("호") else f"{rn}호"
                            room_name_map[rm.id] = f"{building_name} {suffix}"
                        else:
                            room_name_map[rm.id] = rn if rn.endswith("호") else f"{rn}호"
                for res_id, rid in assign_room_id_map.items():
                    room_building_map[res_id] = room_name_map.get(rid, str(rid))

            template_key = schedule.template.template_key

            schedule_custom_vars = schedule.template.get_buffer_vars()

            for reservation in targets:
                try:
                    result = await send_single_sms(
                        db=self.db,
                        sms_provider=self.sms_provider,
                        reservation=reservation,
                        template_key=template_key,
                        date=target_date,
                        created_by="system",
                        skip_activity_log=True,
                        skip_commit=True,
                        custom_vars=schedule_custom_vars,
                    )

                    if result.get('success'):
                        sent_count += 1

                        record_sms_sent(
                            self.db,
                            reservation.id,
                            template_key,
                            schedule.template.category,
                            assigned_by='schedule',
                            date=target_date or '',
                        )

                        self.db.flush()
                        logger.info(f"Sent SMS to {reservation.customer_name} ({reservation.phone})")
                        send_results.append({
                            "customer_name": reservation.customer_name,
                            "phone": reservation.phone,
                            "template_key": template_key,
                            "template_detail": room_building_map.get(reservation.id, ""),
                            "status": "success",
                            "message_id": result.get("message_id"),
                            "message": result.get("message", ""),
                        })
                    else:
                        failed_count += 1
                        error_msg = result.get('error', 'unknown')
                        logger.error(f"Failed to send SMS to {reservation.phone}: {error_msg}")
                        send_results.append({
                            "customer_name": reservation.customer_name,
                            "phone": reservation.phone,
                            "template_key": template_key,
                            "template_detail": room_building_map.get(reservation.id, ""),
                            "status": "failed",
                            "error": error_msg,
                        })

                except Exception as e:
                    failed_count += 1
                    logger.error(f"Error sending SMS to reservation #{reservation.id}: {str(e)}")
                    send_results.append({
                        "customer_name": reservation.customer_name,
                        "phone": reservation.phone,
                        "template_key": template_key,
                        "template_detail": "",
                        "status": "error",
                        "error": str(e),
                    })

            # Update schedule
            schedule.last_run_at = datetime.now(timezone.utc)

            # 활동 로그 기록 (대상자 상세 포함)
            log_activity(
                self.db,
                type="sms_send",
                title=f"SMS 발송 : {'스케줄 수동 발송' if manual else '스케줄 자동 발송'}",
                detail={
                    "schedule_id": schedule.id,
                    "template_key": schedule.template.template_key,
                    "targets": send_results,
                    "message": next((r["message"] for r in send_results if r.get("status") == "success" and r.get("message")), schedule.template.content),
                },
                target_count=len(targets),
                success_count=sent_count,
                failed_count=failed_count,
                status="success" if failed_count == 0 else ("partial" if sent_count > 0 else "failed"),
                created_by="system",
            )

            self.db.commit()

            logger.info(f"Schedule #{schedule_id} execution completed: {sent_count} sent, {failed_count} failed")

            if sent_count > 0:
                publish_event("schedule_complete", {
                    "schedule_id": schedule_id,
                    "sent_count": sent_count,
                    "failed_count": failed_count,
                }, tenant_id=current_tenant_id.get())

            return {
                "success": True,
                "sent_count": sent_count,
                "failed_count": failed_count,
                "target_count": len(targets)
            }

        except Exception as e:
            logger.error(f"Error executing schedule #{schedule_id}: {str(e)}")
            self.db.rollback()
            return {"success": False, "error": str(e)}

    def get_targets(self, schedule: TemplateSchedule, exclude_sent: bool = True) -> List[Reservation]:
        """
        Filter targets based on schedule configuration (dispatcher).

        Routes to _get_targets_standard() or _get_targets_event() based on schedule_category.

        Args:
            schedule: TemplateSchedule instance
            exclude_sent: When True (default), exclude reservations already sent via this template.

        Returns:
            List of Reservation instances
        """
        if (schedule.schedule_category or 'standard') == 'event':
            return self._get_targets_event(schedule, exclude_sent=exclude_sent)
        return self._get_targets_standard(schedule, exclude_sent=exclude_sent)

    def _apply_structural_filters(self, query, schedule: TemplateSchedule, target_date: str):
        """Apply structural filters — delegates to standalone function in filters.py."""
        return _standalone_structural_filters(self.db, query, schedule, target_date)

    def _check_send_condition(self, schedule: TemplateSchedule) -> bool:
        """Check if send condition (gender ratio) is met."""
        # 기준 날짜 결정
        if schedule.send_condition_date == 'tomorrow':
            target = (today_kst_date() + timedelta(days=1)).strftime('%Y-%m-%d')
        else:
            target = today_kst()

        # 해당 날짜 체크인 예약자의 male_count, female_count 합계
        row = self.db.query(
            func.coalesce(func.sum(Reservation.male_count), 0).label("male"),
            func.coalesce(func.sum(Reservation.female_count), 0).label("female"),
        ).filter(
            Reservation.status == ReservationStatus.CONFIRMED,
            Reservation.check_in_date == target,
        ).first()

        total_male = int(row.male)
        total_female = int(row.female)

        # female이 0이면 비율 계산 불가
        if total_female == 0:
            # male이 있으면 비율 무한대 → gte는 항상 참, lte는 항상 거짓
            if total_male == 0:
                return False  # 데이터 없으면 스킵
            ratio = float('inf')
        else:
            ratio = total_male / total_female

        threshold = schedule.send_condition_ratio
        operator = schedule.send_condition_operator or 'gte'

        if operator == 'gte':
            return ratio >= threshold
        elif operator == 'lte':
            return ratio <= threshold
        return True  # 알 수 없는 operator면 발송

    def _get_targets_standard(self, schedule: TemplateSchedule, exclude_sent: bool = True) -> List[Reservation]:
        """Standard schedule targeting — existing logic, unchanged."""
        query = self.db.query(Reservation).filter(
            Reservation.status == ReservationStatus.CONFIRMED
        )

        date_target_val = schedule.date_target

        # Safety guard: never send to reservations more than 1 day out
        max_date = (today_kst_date() + timedelta(days=1)).strftime('%Y-%m-%d')
        if date_target_val and date_target_val.endswith('_checkout'):
            query = query.filter(
                Reservation.check_out_date.isnot(None),
                Reservation.check_out_date <= max_date,
            )
        else:
            query = query.filter(Reservation.check_in_date <= max_date)

        # Apply date_target filter
        target_date = None
        if date_target_val:
            target_date = self._resolve_date_target(date_target_val)
            if date_target_val.endswith('_checkout'):
                query = query.filter(
                    Reservation.check_out_date.isnot(None),
                    Reservation.check_out_date == target_date,
                )
            else:
                if schedule.target_mode in ('daily', 'last_day'):
                    query = query.filter(
                        or_(
                            and_(
                                Reservation.check_in_date <= target_date,
                                Reservation.check_out_date > target_date,
                            ),
                            and_(
                                Reservation.check_in_date == target_date,
                                Reservation.check_out_date.is_(None),
                            ),
                        )
                    )
                else:
                    query = query.filter(Reservation.check_in_date == target_date)
        # Default target_date for filters that need it
        if not target_date:
            target_date = today_kst()

        # Apply structural filters (building/assignment/room/column_match)
        query = self._apply_structural_filters(query, schedule, target_date)

        # Apply exclude_sent filter via join table
        if exclude_sent and schedule.exclude_sent:
            from sqlalchemy import exists
            sent_conditions = (
                (ReservationSmsAssignment.reservation_id == Reservation.id) &
                (ReservationSmsAssignment.template_key == schedule.template.template_key) &
                (ReservationSmsAssignment.sent_at.isnot(None))
            )
            if target_date:
                sent_conditions = sent_conditions & (ReservationSmsAssignment.date == target_date)
            query = query.filter(~exists().where(sent_conditions))

        results = query.all()

        # last_day: keep only reservations on their group's last calendar day
        if schedule.target_mode == 'last_day' and results and target_date:
            results = self._filter_last_day(results, target_date)

        # once_per_stay: 연박/연장 그룹 내 가장 빠른 체크인 예약에만 발송
        if schedule.once_per_stay and results:
            from sqlalchemy import exists as sa_exists
            filtered = []
            seen_groups: set[str] = set()
            # Sort by check_in_date to ensure earliest first
            results.sort(key=lambda r: r.check_in_date)
            for res in results:
                if res.is_long_stay:
                    if res.stay_group_id:
                        # 연장자: 그룹 내 중복 방지
                        if res.stay_group_id in seen_groups:
                            continue  # Skip: group already has a target
                        # Check if an earlier group member already received this template
                        earlier_sent = self.db.query(sa_exists().where(
                            (ReservationSmsAssignment.template_key == schedule.template.template_key) &
                            (ReservationSmsAssignment.sent_at.isnot(None)) &
                            (ReservationSmsAssignment.reservation_id.in_(
                                self.db.query(Reservation.id).filter(
                                    Reservation.stay_group_id == res.stay_group_id,
                                    Reservation.id != res.id,
                                )
                            ))
                        )).scalar()
                        if earlier_sent:
                            seen_groups.add(res.stay_group_id)
                            continue  # Skip: another group member already sent
                        seen_groups.add(res.stay_group_id)
                    else:
                        # 연박자(stay_group_id=None): reservation_id로 기발송 체크
                        already_sent = self.db.query(sa_exists().where(
                            (ReservationSmsAssignment.template_key == schedule.template.template_key) &
                            (ReservationSmsAssignment.sent_at.isnot(None)) &
                            (ReservationSmsAssignment.reservation_id == res.id)
                        )).scalar()
                        if already_sent:
                            continue
                filtered.append(res)
            results = filtered

        # Stay filter
        if schedule.stay_filter == 'exclude':
            results = [r for r in results if not r.is_long_stay]

        return results

    def _get_targets_event(self, schedule: TemplateSchedule, exclude_sent: bool = True) -> List[Reservation]:
        """Event schedule targeting — confirmed_at 기반 필터링."""
        query = self.db.query(Reservation).filter(
            Reservation.status == ReservationStatus.CONFIRMED
        )

        # No safety guard — max_checkin_days provides its own range limit
        today_str = today_kst()

        # 1) N일 이내 체크인
        if schedule.max_checkin_days:
            max_date_str = (today_kst_date() + timedelta(days=schedule.max_checkin_days)).strftime('%Y-%m-%d')
            query = query.filter(
                Reservation.check_in_date >= today_str,
                Reservation.check_in_date <= max_date_str,
            )

        # 2) 성별 필터 — 예약자 본인 기준 (Reservation.gender)
        if schedule.gender_filter == 'male':
            query = query.filter(Reservation.gender == '남')
        elif schedule.gender_filter == 'female':
            query = query.filter(Reservation.gender == '여')

        # 이벤트는 structural filters (건물/배정/객실) 미적용 — 대상이 아직 미배정인 경우가 대부분

        # 4) confirmed_at N시간 이내 — Python datetime 파싱 방식
        results = query.all()

        if schedule.hours_since_booking:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=schedule.hours_since_booking)
            filtered = []
            for res in results:
                if not res.confirmed_at:
                    continue  # 수동 예약 (confirmed_at=NULL) 제외
                try:
                    confirmed = datetime.fromisoformat(str(res.confirmed_at))
                    if confirmed >= cutoff:
                        filtered.append(res)
                except (ValueError, TypeError):
                    continue  # 파싱 실패 시 안전하게 제외
            results = filtered

        # 5) 연박 필터 (stay_filter)
        if schedule.stay_filter == 'exclude':
            results = [r for r in results if not r.is_long_stay]

        # 6) exclude_sent — 이벤트 전용 (날짜 무관)
        if exclude_sent and schedule.exclude_sent:
            already_sent_ids = {
                row.reservation_id for row in
                self.db.query(ReservationSmsAssignment.reservation_id).filter(
                    ReservationSmsAssignment.template_key == schedule.template.template_key,
                    ReservationSmsAssignment.sent_at.isnot(None),
                ).all()
            }
            results = [r for r in results if r.id not in already_sent_ids]

        return results

    def auto_assign_for_schedule(self, schedule: TemplateSchedule) -> int:
        """
        Auto-assign ReservationSmsAssignment records for a schedule's targets.
        Delegates to chip_reconciler for unified create+delete logic.

        Returns:
            Number of new assignments created
        """
        from app.services.chip_reconciler import reconcile_chips_for_schedule
        return reconcile_chips_for_schedule(self.db, schedule)

    def preview_targets(self, schedule: TemplateSchedule) -> List[Dict[str, Any]]:
        """
        Preview targets without sending messages

        Returns:
            List of target information dicts
        """
        targets = self.get_targets(schedule)

        # Batch lookup room assignments from RoomAssignment table (source of truth)
        date_target_val = schedule.date_target
        target_date = self._resolve_date_target(date_target_val) if date_target_val else today_kst()
        res_ids = [r.id for r in targets]
        from app.services.room_lookup import batch_room_number_map
        room_map: dict[int, str] = batch_room_number_map(self.db, res_ids, target_date) if res_ids else {}

        return [
            {
                "id": r.id,
                "customer_name": r.customer_name,
                "phone": r.phone,
                "check_in_date": r.check_in_date,
                "check_in_time": r.check_in_time,
                "room_number": room_map.get(r.id) or r.room_number,
            }
            for r in targets
        ]

    @staticmethod
    def _resolve_date_target(date_target_val: str) -> str:
        """Convert a date_target enum value to a concrete YYYY-MM-DD date string.

        Args:
            date_target_val: One of 'today', 'tomorrow', 'today_checkout', 'tomorrow_checkout'

        Returns:
            Date string for today or tomorrow, regardless of checkout suffix.
        """
        if date_target_val.startswith('tomorrow'):
            return (today_kst_date() + timedelta(days=1)).strftime('%Y-%m-%d')
        return today_kst()

    def _filter_last_day(self, results: List[Reservation], target_date: str) -> List[Reservation]:
        """Keep only reservations whose stay group's last checkout date - 1 == target_date.
        For standalone guests: checkout_date - 1 == target_date.
        Reservations with NULL check_out_date are excluded.
        """
        from datetime import datetime as dt

        target_dt = dt.strptime(target_date, "%Y-%m-%d").date()
        filtered = []

        # Batch-query max checkout per group
        group_ids = {r.stay_group_id for r in results if r.stay_group_id}
        group_max_checkout: dict[str, str] = {}

        if group_ids:
            rows = self.db.query(
                Reservation.stay_group_id,
                func.max(Reservation.check_out_date)
            ).filter(
                Reservation.stay_group_id.in_(group_ids),
                Reservation.check_out_date.isnot(None),
            ).group_by(Reservation.stay_group_id).all()
            group_max_checkout = {gid: max_co for gid, max_co in rows}

        for res in results:
            if res.check_out_date is None:
                continue  # NULL checkout → exclude

            if res.stay_group_id:
                max_co = group_max_checkout.get(res.stay_group_id)
                if not max_co:
                    continue
                last_day = dt.strptime(max_co, "%Y-%m-%d").date() - timedelta(days=1)
            else:
                # Standalone: use own checkout
                last_day = dt.strptime(res.check_out_date, "%Y-%m-%d").date() - timedelta(days=1)

            if last_day == target_dt:
                filtered.append(res)

        return filtered



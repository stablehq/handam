"""
Template-based schedule execution engine
"""
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from sqlalchemy import or_, func

from app.db.models import TemplateSchedule, Reservation, RoomAssignment, ReservationSmsAssignment, Room, ReservationStatus
from app.diag_logger import diag
from app.services.filters import (
    apply_structural_filters as _standalone_structural_filters,
)
from app.factory import get_sms_provider_for_tenant
from app.services.sms_tracking import record_sms_sent
from app.services.activity_logger import log_activity
from app.services.event_bus import publish as publish_event
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
        diag(
            "schedule.execute.enter",
            level="verbose",
            schedule_id=schedule_id,
            manual=manual,
        )

        # Load schedule
        schedule = self.db.query(TemplateSchedule).filter(
            TemplateSchedule.id == schedule_id,
            TemplateSchedule.is_active == True
        ).first()

        if not schedule:
            logger.warning(f"Schedule #{schedule_id} not found or inactive")
            diag(
                "schedule.execute.exit",
                level="verbose",
                schedule_id=schedule_id,
                outcome="schedule_not_found",
                sent=0,
                failed=0,
                targets=0,
            )
            return {"success": False, "error": "Schedule not found or inactive"}

        if not schedule.template or not schedule.template.is_active:
            logger.warning(f"Template for schedule #{schedule_id} not found or inactive")
            diag(
                "schedule.execute.exit",
                level="verbose",
                schedule_id=schedule_id,
                outcome="template_not_found",
                sent=0,
                failed=0,
                targets=0,
            )
            return {"success": False, "error": "Template not found or inactive"}

        try:
            # Send condition check (표준 스케줄 전용 — event/custom 에는 무관)
            is_custom = (schedule.schedule_category or 'standard') == 'custom_schedule'
            if (
                not is_custom
                and schedule.send_condition_date
                and schedule.send_condition_ratio is not None
            ):
                condition_met = self._check_send_condition(schedule)
                if not condition_met:
                    schedule.last_run_at = datetime.now(timezone.utc)
                    self.db.commit()
                    logger.info(f"Schedule #{schedule_id}: send condition not met, skipping")
                    diag(
                        "schedule.execute.exit",
                        level="verbose",
                        schedule_id=schedule_id,
                        outcome="send_condition_not_met",
                        sent=0,
                        failed=0,
                        targets=0,
                    )
                    return {"success": True, "sent_count": 0, "message": "Send condition not met, skipped"}

            # Get targets
            targets = self.get_targets(schedule)
            logger.info(f"Found {len(targets)} targets for schedule #{schedule_id}")
            diag(
                "schedule.execute.targets",
                level="verbose",
                schedule_id=schedule_id,
                target_count=len(targets),
            )

            if not targets:
                # Update last_run even if no targets
                schedule.last_run_at = datetime.now(timezone.utc)
                self.db.commit()
                diag(
                    "schedule.execute.exit",
                    level="verbose",
                    schedule_id=schedule_id,
                    outcome="no_targets",
                    sent=0,
                    failed=0,
                    targets=0,
                )
                return {"success": True, "sent_count": 0, "message": "No targets found"}

            # Send messages
            sent_count = 0
            failed_count = 0
            send_results = []

            # 이벤트 스케줄: target_date를 오늘로 고정
            category = schedule.schedule_category or 'standard'
            if category == 'event':
                target_date = today_kst()
                date_target_val = None
            else:
                # custom_schedule defaults to 'today' when date_target is unset —
                # matches the coercion applied inside _get_targets_standard.
                date_target_val = schedule.date_target or ('today' if category == 'custom_schedule' else None)
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

                        from app.services.sms_tracking import record_sms_failed
                        record_sms_failed(
                            self.db, reservation.id, template_key,
                            error=error_msg, date=target_date or '',
                        )
                        self.db.flush()

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
            if (schedule.schedule_category or 'standard') == 'custom_schedule':
                schedule_label = f"커스텀({schedule.custom_type or '미지정'})"
            else:
                schedule_label = '스케줄 수동 발송' if manual else '스케줄 자동 발송'
            log_activity(
                self.db,
                type="sms_send",
                title=f"SMS 발송 : {schedule_label}",
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
                }, tenant_id=schedule.tenant_id)

            diag(
                "schedule.execute.exit",
                level="verbose",
                schedule_id=schedule_id,
                outcome="completed",
                sent=sent_count,
                failed=failed_count,
                targets=len(targets),
            )

            return {
                "success": True,
                "sent_count": sent_count,
                "failed_count": failed_count,
                "target_count": len(targets)
            }

        except Exception as e:
            logger.error(f"Error executing schedule #{schedule_id}: {str(e)}")
            try:
                import sentry_sdk
                sentry_sdk.capture_exception(e)
            except ImportError:
                pass
            self.db.rollback()
            diag(
                "schedule.execute.exit",
                level="critical",
                schedule_id=schedule_id,
                outcome="exception",
                error=type(e).__name__,
                msg=str(e)[:200],
            )
            return {"success": False, "error": str(e)}

    def get_targets(
        self,
        schedule: TemplateSchedule,
        exclude_sent: bool = True,
        for_preview: bool = False,
    ) -> List[Reservation]:
        """
        Filter targets based on schedule configuration (dispatcher).

        - event:           dedicated path (_get_targets_event)
        - custom_schedule: standard path + chip-based eligibility prefilter
        - standard:        standard path

        Args:
            schedule: TemplateSchedule instance
            exclude_sent: When True (default), exclude reservations already sent via this template.
            for_preview: When True, skip side-effectful reconcile steps
                (e.g. pre-send chip refresh for custom schedules). UI preview
                endpoints should pass True so that viewing targets does not
                mutate chip state.

        Returns:
            List of Reservation instances
        """
        if (schedule.schedule_category or 'standard') == 'event':
            return self._get_targets_event(schedule, exclude_sent=exclude_sent)
        return self._get_targets_standard(schedule, exclude_sent=exclude_sent, for_preview=for_preview)

    def _apply_structural_filters(self, query, schedule: TemplateSchedule, target_date: str):
        """Apply structural filters — delegates to standalone function in filters.py."""
        return _standalone_structural_filters(self.db, query, schedule, target_date)

    def _refresh_custom_chips(self, schedule: TemplateSchedule, target_date: str) -> None:
        """Run the custom_type's reconcile handler right before send.

        Keeps chip state in sync with the current DB even when live trigger
        paths (assignment change, naver sync, etc.) missed an update. Missing
        handler or runtime error is logged but never blocks the send.
        """
        from app.services.custom_schedule_registry import get_pre_send_refresh_handler

        handler = get_pre_send_refresh_handler(schedule.custom_type)
        if handler is None:
            return
        try:
            handler(self.db, target_date)
            self.db.flush()
        except Exception:
            logger.exception(
                "custom refresh failed (schedule_id=%s, custom_type=%s, date=%s)",
                schedule.id, schedule.custom_type, target_date,
            )

    def _check_send_condition(self, schedule: TemplateSchedule) -> bool:
        """Check if send condition (gender ratio) is met."""
        from app.services.filters import stay_coverage_filter

        # 기준 날짜 결정
        if schedule.send_condition_date == 'tomorrow':
            target = (today_kst_date() + timedelta(days=1)).strftime('%Y-%m-%d')
        else:
            target = today_kst()

        # target 날에 투숙/방문 중인 예약 인원 합계 (연박 중간일 + NULL/당일 포함)
        row = self.db.query(
            func.coalesce(func.sum(Reservation.male_count), 0).label("male"),
            func.coalesce(func.sum(Reservation.female_count), 0).label("female"),
        ).filter(
            Reservation.status == ReservationStatus.CONFIRMED,
            stay_coverage_filter(target),
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

    def _get_targets_standard(
        self,
        schedule: TemplateSchedule,
        exclude_sent: bool = True,
        for_preview: bool = False,
    ) -> List[Reservation]:
        """Standard schedule targeting.

        Also serves custom_schedule via a pre-filter that narrows candidates to
        reservations holding a pending chip for this schedule on target_date.
        For custom_schedule, NULL fields are coerced to safe defaults so every
        downstream guard (safety, date_target, exclude_sent)
        applies identically.

        for_preview=True suppresses side-effectful steps (chip refresh) so that
        preview endpoints can inspect targets without mutating state.
        """
        is_custom = (schedule.schedule_category or 'standard') == 'custom_schedule'

        # Custom-only default coercion — leaves standard behavior untouched.
        date_target_val = schedule.date_target or ('today' if is_custom else None)
        effective_target_mode = schedule.target_mode  # custom default 도 None (기본)
        from app.services.filters import extract_stay_filter
        effective_stay_filter = extract_stay_filter(schedule)
        effective_exclude_sent_flag = True if is_custom else bool(schedule.exclude_sent)

        # Defense-in-depth: explicit tenant filter against schedule's owner.
        # If bypass_tenant_filter is leaked True from a sibling task (e.g. naver
        # sync looping tenants in the same coroutine context), the implicit
        # before_compile filter is skipped and cross-tenant reservations would
        # otherwise enter the targets list — causing wrong-tenant SMS deliveries.
        query = self.db.query(Reservation).filter(
            Reservation.tenant_id == schedule.tenant_id,
            Reservation.status == ReservationStatus.CONFIRMED,
        )

        # ── Custom eligibility prefilter ──
        # Restrict candidates to reservations with a pending chip bound to this
        # schedule on the schedule's target_date. Chips act as eligibility
        # markers set by custom generators (e.g. reconcile_surcharge); the
        # standard filter chain below then decides whether to actually send.
        if is_custom:
            target_date_for_chips = self._resolve_date_target(date_target_val)

            # Pre-send refresh: reconcile chips against the current DB state so
            # missed trigger paths or stale chips cannot leak into this send.
            # Skipped in preview mode — previews must not mutate chip state.
            if not for_preview:
                self._refresh_custom_chips(schedule, target_date_for_chips)

            # 같은 template_key 를 쓰는 칩이면 어느 스케줄이 만들었든 대상으로 인정.
            # → 같은 custom_type 으로 여러 시간대 스케줄을 두어도 retry 가능 (10시 실패 시
            #   15시가 동일 칩을 픽업). 중복 발송은 아래 exclude_sent + unique 제약이 방어.
            eligible_ids = self.db.query(ReservationSmsAssignment.reservation_id).filter(
                ReservationSmsAssignment.template_key == schedule.template.template_key,
                ReservationSmsAssignment.sent_at.is_(None),
                ReservationSmsAssignment.date == target_date_for_chips,
                or_(
                    ReservationSmsAssignment.send_status.is_(None),
                    ReservationSmsAssignment.send_status != 'failed',
                ),
            )
            query = query.filter(Reservation.id.in_(eligible_ids))

        # Safety guard: target_date 는 오늘 ±N일 내여야 함
        min_date = (today_kst_date() - timedelta(days=7)).strftime('%Y-%m-%d')
        max_date = (today_kst_date() + timedelta(days=1)).strftime('%Y-%m-%d')
        query = query.filter(
            Reservation.check_in_date >= min_date,
            Reservation.check_in_date <= max_date,
        )

        # Apply date_target filter
        target_date = None
        if date_target_val:
            target_date = self._resolve_date_target(date_target_val)
            # 기본: stay-coverage (그 날 투숙/방문중 — 연박 중간일 + NULL/당일 포함)
            from app.services.filters import stay_coverage_filter
            query = query.filter(stay_coverage_filter(target_date))
            # first_night narrow
            if effective_target_mode == 'first_night':
                query = query.filter(Reservation.check_in_date == target_date)
            # last_night: post-filter in _filter_last_day 에서 처리
        if not target_date:
            target_date = today_kst()

        # Apply v2 structural filters (assignment nested + column_match)
        query = self._apply_structural_filters(query, schedule, target_date)

        # Apply exclude_sent filter via join table (sent 또는 failed 모두 제외)
        if exclude_sent and effective_exclude_sent_flag:
            from sqlalchemy import exists
            done_conditions = (
                (ReservationSmsAssignment.reservation_id == Reservation.id) &
                (ReservationSmsAssignment.template_key == schedule.template.template_key) &
                (or_(
                    ReservationSmsAssignment.sent_at.isnot(None),
                    ReservationSmsAssignment.send_status == 'failed',
                ))
            )
            # custom_schedule: 기본은 날짜 무관 중복 차단 (once_per_stay 대체)
            # 단, PER_DATE_DEDUP_CUSTOM_TYPES (party3 등) 은 날짜별 개별 발송 허용
            # standard: 항상 당일 date 로 한정
            from app.services.custom_schedule_registry import is_per_date_dedup
            use_date_filter = (not is_custom) or is_per_date_dedup(schedule.custom_type)
            if target_date and use_date_filter:
                done_conditions = done_conditions & (ReservationSmsAssignment.date == target_date)
            query = query.filter(~exists().where(done_conditions))

        results = query.all()

        # last_night: keep only reservations on their group's last calendar day
        if effective_target_mode == 'last_night' and results and target_date:
            results = self._filter_last_day(results, target_date)

        # Stay filter
        if effective_stay_filter == 'exclude':
            results = [r for r in results if not r.is_long_stay]

        return results

    def _get_targets_event(
        self,
        schedule: TemplateSchedule,
        exclude_sent: bool = True,
        restrict_to_ids: Optional[List[int]] = None,
    ) -> List[Reservation]:
        """Event schedule targeting — confirmed_at 기반 필터링.

        restrict_to_ids: 주어지면 해당 reservation_id 들로만 좁힘 (naver_sync 훅 등에서 사용).
        """
        # Defense-in-depth: see _get_targets_standard for rationale.
        query = self.db.query(Reservation).filter(
            Reservation.tenant_id == schedule.tenant_id,
            Reservation.status == ReservationStatus.CONFIRMED,
        )

        if restrict_to_ids:
            query = query.filter(Reservation.id.in_(restrict_to_ids))

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
            # confirmed_at 은 TIMESTAMP WITHOUT TIME ZONE (naive) 이므로
            # cutoff 도 naive 로 만들어야 비교 가능. UTC 기준은 유지.
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=schedule.hours_since_booking)).replace(tzinfo=None)
            filtered = []
            for res in results:
                if not res.confirmed_at:
                    continue  # 수동 예약 (confirmed_at=NULL) 제외
                if res.confirmed_at >= cutoff:
                    filtered.append(res)
            results = filtered

        # 5) 연박 필터 — filters JSON 안의 room assignment 우선 (v2),
        # 없으면 legacy schedule.stay_filter 컬럼 fallback. extract_stay_filter() 가 둘 다 처리.
        from app.services.filters import extract_stay_filter
        if extract_stay_filter(schedule) == 'exclude':
            results = [r for r in results if not r.is_long_stay]

        # 6) exclude_sent — 이벤트 전용 (날짜 무관, sent 또는 failed 모두 제외)
        if exclude_sent and schedule.exclude_sent:
            already_done_ids = {
                row.reservation_id for row in
                self.db.query(ReservationSmsAssignment.reservation_id).filter(
                    ReservationSmsAssignment.template_key == schedule.template.template_key,
                    or_(
                        ReservationSmsAssignment.sent_at.isnot(None),
                        ReservationSmsAssignment.send_status == 'failed',
                    ),
                ).all()
            }
            results = [r for r in results if r.id not in already_done_ids]

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
        targets = self.get_targets(schedule, for_preview=True)

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
        from app.services.schedule_utils import resolve_target_date
        return resolve_target_date(date_target_val)

    def _filter_last_day(self, results: List[Reservation], target_date: str) -> List[Reservation]:
        """Keep only reservations whose stay group's last checkout date - 1 == target_date.
        For standalone guests: checkout_date - 1 == target_date.
        For reservations with NULL check_out_date (당일 예약, 파티만 이동 케이스):
            check_in_date == target_date 이면 마지막 투숙일로 간주.
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
                # 당일 예약: check_in 이 곧 마지막 투숙일
                if res.check_in_date == target_date:
                    filtered.append(res)
                continue

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



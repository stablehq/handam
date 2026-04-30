"""신규 예약에 대한 event SMS 즉시 발송 훅.

naver_sync 가 새 예약을 감지했을 때 호출되어, 활성 event 스케줄
(gender_filter / max_checkin_days / hours_since_booking 조건) 을 만족하는
신규 예약에 즉시 SMS 를 발송한다.

설계 원칙 (모두 호출자 보호용):
1. 호출자 흐름은 절대 차단/예외 전파 안 함 → fire-and-forget
2. 별도 DB 세션 사용 → naver_sync 트랜잭션과 무관
3. 활성 event 스케줄 0개면 즉시 no-op
4. 스케줄 단위 try/except → 한 스케줄 실패해도 다른 스케줄 진행
5. 발송 단위 try/except → 한 명 실패해도 다른 사람 진행
6. tenant 컨텍스트 명시적 주입/복원
7. SMS provider 획득 실패 시 그 테넌트 훅만 포기 (sync 자체엔 영향 없음)
"""
from __future__ import annotations

import asyncio
import logging
from typing import Iterable, Optional


from app.diag_logger import diag

logger = logging.getLogger(__name__)


def schedule_event_sms_hook(reservation_ids: Iterable[int], tenant_id: int) -> None:
    """신규 예약 ID 리스트에 대해 event SMS 발송을 백그라운드로 시작.

    naver_sync 등 호출자에서 사용. 어떤 상황에서도 예외를 raise 하지 않으며,
    호출자 코드 흐름은 즉시 반환된다 (실제 발송은 background task).

    옵션 C (Phase 6): tenant_id 인자 명시 필수.
    """
    try:
        ids = [int(i) for i in reservation_ids if i]
        if not ids:
            return
        if tenant_id is None:
            diag("event_sms_hook.no_tenant_ctx", level="critical",
                 reservation_count=len(ids))
            return

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # 동기 컨텍스트 (테스트 / sync 호출) — 훅 스킵, 메인 흐름은 계속
            diag("event_sms_hook.no_event_loop", level="critical",
                 reservation_count=len(ids), tenant_id=tenant_id)
            return

        task = loop.create_task(_run_event_hook(ids, tenant_id))
        task.add_done_callback(_log_task_result)
        diag("event_sms_hook.scheduled", level="verbose",
             reservation_count=len(ids), tenant_id=tenant_id)
    except Exception as e:
        # 절대 호출자에 전파 금지
        logger.exception(f"schedule_event_sms_hook failed (suppressed): {e}")


def _log_task_result(task: "asyncio.Task") -> None:
    """백그라운드 task crash 시 로그만 남기고 무시."""
    try:
        exc = task.exception()
        if exc is not None:
            logger.error(
                "event_sms_hook background task crashed: %s",
                exc, exc_info=exc,
            )
    except (asyncio.CancelledError, asyncio.InvalidStateError):
        pass
    except Exception:
        pass


async def _run_event_hook(reservation_ids: list[int], tenant_id: int) -> None:
    """실제 발송 본체 — 별도 DB 세션 + 격리된 tenant 컨텍스트로 동작.

    옵션 C (Phase 3): session_for_tenant(tenant_id) 사용. ContextVar 도 set/reset (legacy 호환).
    """
    from app.db.database import session_for_tenant
    from app.db.models import TemplateSchedule, Tenant
    from app.factory import get_sms_provider_for_tenant
    from app.scheduler.template_scheduler import TemplateScheduleExecutor

    db = session_for_tenant(tenant_id)
    sent_total = 0
    failed_total = 0
    eligible_total = 0

    try:
        # 1) 활성 event 스케줄 조회 — 0개면 빠른 종료
        try:
            schedules = db.query(TemplateSchedule).filter(
                TemplateSchedule.is_active == True,  # noqa: E712
                TemplateSchedule.schedule_category == 'event',
            ).all()
        except Exception as e:
            logger.exception(f"event_sms_hook: schedule fetch failed: {e}")
            return

        if not schedules:
            diag("event_sms_hook.no_schedules", level="verbose",
                 tenant_id=tenant_id)
            return

        diag("event_sms_hook.enter", level="critical",
             tenant_id=tenant_id,
             reservation_count=len(reservation_ids),
             schedule_count=len(schedules))

        # 2) SMS provider 1회 획득 — 실패 시 이번 훅 포기 (sync 영향 없음)
        try:
            tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
            if tenant is None:
                logger.warning(f"event_sms_hook: tenant {tenant_id} not found")
                return
            sms_provider = get_sms_provider_for_tenant(tenant)
        except Exception as e:
            logger.exception(f"event_sms_hook: provider unavailable: {e}")
            return

        # 3) 스케줄 단위 격리
        executor = TemplateScheduleExecutor(db)
        for sched in schedules:
            try:
                targets = executor._get_targets_event(
                    sched,
                    exclude_sent=True,
                    restrict_to_ids=reservation_ids,
                )
            except Exception as e:
                logger.exception(
                    f"event_sms_hook: target eval failed sched={sched.id}: {e}"
                )
                continue

            if not targets:
                continue

            eligible_total += len(targets)

            # 4) 발송 단위 격리
            for res in targets:
                try:
                    ok = await _send_one(db, sms_provider, sched, res)
                    if ok:
                        sent_total += 1
                    else:
                        failed_total += 1
                except Exception as e:
                    failed_total += 1
                    logger.exception(
                        f"event_sms_hook: send failed "
                        f"res={res.id} sched={sched.id}: {e}"
                    )

        diag("event_sms_hook.exit", level="critical",
             tenant_id=tenant_id,
             eligible=eligible_total, sent=sent_total, failed=failed_total)

    finally:
        try:
            db.close()
        except Exception:
            pass



async def _send_one(db, sms_provider, schedule, reservation) -> bool:
    """단건 발송. 예외는 상위에서 잡도록 그대로 raise."""
    from app.services.sms_sender import send_single_sms

    template = schedule.template
    if template is None or not template.template_key:
        return False

    custom_vars: Optional[dict] = None
    try:
        custom_vars = template.get_buffer_vars()
    except Exception:
        custom_vars = None

    result = await send_single_sms(
        db=db,
        sms_provider=sms_provider,
        reservation=reservation,
        template_key=template.template_key,
        date=None,  # 이벤트는 특정 date 무관
        created_by=f"event_hook:sched_{schedule.id}",
        custom_vars=custom_vars,
    )
    return bool(result.get("success"))

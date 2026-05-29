"""
Reservations API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from typing import Optional
from app.api.deps import get_tenant_scoped_db, get_current_tenant
from app.db.models import Reservation, ReservationStatus, User, Tenant, RoomAssignment, ReservationDailyInfo
from app.factory import get_reservation_provider_for_tenant
from app.auth.dependencies import get_current_user
from app.rate_limit import limiter
from app.services.activity_logger import log_activity
from app.api.shared_schemas import ActionResponse
import logging
from app.diag_logger import diag

from app.api.reservations_shared import (
    ReservationCreate,
    ReservationUpdate,
    ReservationResponse,
    _to_response,
)

router = APIRouter(prefix="/api/reservations", tags=["reservations"])
logger = logging.getLogger(__name__)


@router.get("")
async def get_reservations(
    skip: int = 0,
    limit: int = 50,
    status: Optional[str] = None,
    date: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    search: Optional[str] = None,
    source: Optional[str] = None,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
):
    """Get reservations with pagination and filtering"""
    query = db.query(Reservation)

    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        if len(statuses) == 1:
            query = query.filter(Reservation.status == statuses[0])
        else:
            query = query.filter(Reservation.status.in_(statuses))

    if search:
        query = query.filter(
            or_(
                Reservation.customer_name.contains(search),
                Reservation.phone.contains(search),
            )
        )

    if source:
        sources = [s.strip() for s in source.split(",") if s.strip()]
        if len(sources) == 1:
            query = query.filter(Reservation.booking_source == sources[0])
        else:
            query = query.filter(Reservation.booking_source.in_(sources))

    if date:
        # Single date: check-in <= date < check-out, OR check-in == date (covers same-day checkout & NULL end_date)
        query = query.filter(
            or_(
                and_(
                    Reservation.check_in_date <= date,
                    Reservation.check_out_date > date,
                ),
                Reservation.check_in_date == date,
            )
        )
    elif date_from or date_to:
        # Date range: reservations overlapping with [date_from, date_to]
        if date_from:
            query = query.filter(
                or_(
                    Reservation.check_out_date >= date_from,
                    Reservation.check_out_date.is_(None),
                )
            )
        if date_to:
            query = query.filter(Reservation.check_in_date <= date_to)

    # Total count before pagination (for server-side pagination)
    total_count = query.count()

    # Order by most recent confirmation or cancellation datetime
    from sqlalchemy.orm import selectinload
    reservations = query.options(
        selectinload(Reservation.sms_assignments)
    ).order_by(
        Reservation.confirmed_at.desc().nullslast(),
    ).offset(skip).limit(limit).all()

    # 항상 RoomAssignment에서 객실 정보 조회 (소스 오브 트루스) — 배치 조회로 N+1 제거
    res_ids = [r.id for r in reservations]
    if res_ids:
        # date 파라미터가 있으면 해당 날짜로 일괄 조회, 없으면 각 예약의 date를 키로 사용
        if date:
            from app.services.room_lookup import batch_room_lookup
            _rl = batch_room_lookup(db, res_ids, date)
            room_map = {res_id: (info["room_id"], info["room_number"] or '', info["room_password"], info["assigned_by"], info.get("bed_order", 0)) for res_id, info in _rl.items()}

            # Batch-query daily info for the target date
            daily_infos = (
                db.query(ReservationDailyInfo)
                .filter(
                    ReservationDailyInfo.reservation_id.in_(res_ids),
                    ReservationDailyInfo.date == date,
                )
                .all()
            )
            daily_party_map = {di.reservation_id: di.party_type for di in daily_infos}
            daily_notes_map = {di.reservation_id: di.notes for di in daily_infos if di.notes is not None}
            daily_unstable_map = {di.reservation_id: di.unstable_party for di in daily_infos if di.unstable_party}
        else:
            # date 없음: 각 예약의 check-in date 기준으로 조회
            # (reservation_id, date) 쌍을 한 번에 가져온 뒤 매핑
            res_date_map = {r.id: r.check_in_date for r in reservations}
            room_assignments = (
                db.query(RoomAssignment)
                .filter(RoomAssignment.reservation_id.in_(res_ids))
                .all()
            )
            from app.services.room_lookup import batch_room_lookup
            # Collect only assignments matching each reservation's check-in date
            matching_ids = [ra.reservation_id for ra in room_assignments if ra.date == res_date_map.get(ra.reservation_id)]
            _rl = batch_room_lookup(db, matching_ids) if matching_ids else {}
            # Merge with per-date filter: only keep if the assignment date matches check-in
            room_map = {}
            for ra in room_assignments:
                if ra.date == res_date_map.get(ra.reservation_id) and ra.reservation_id in _rl:
                    info = _rl[ra.reservation_id]
                    room_map[ra.reservation_id] = (info["room_id"], info["room_number"] or '', info["room_password"], info["assigned_by"], info.get("bed_order", 0))
            daily_party_map = {}
            daily_notes_map = {}
            daily_unstable_map = {}
    else:
        room_map = {}
        daily_party_map = {}
        daily_notes_map = {}

    # daily_keys를 한 번만 조회 (N+1 방지)
    _daily_keys = None
    if date:
        from app.db.models import TemplateSchedule
        _daily_keys = {
            s.template.template_key
            for s in db.query(TemplateSchedule).filter(TemplateSchedule.is_active == True, TemplateSchedule.target_mode.is_(None)).all()
            if s.template
        }

    # 언스테이블 예약 전화번호 매칭: 같은 날짜에 숙박 중인 스테이블 예약자 중 언스테이블도 예약한 사람 감지
    unstable_phone_set: set = set()
    if date:
        unstable_phones = [r.phone for r in reservations if r.section == 'unstable' and r.phone]
        unstable_phone_set = set(unstable_phones)

    results = []
    for res in reservations:
        if res.id in room_map:
            override_room_id, override_room, override_password, override_assigned_by, override_bed_order = room_map[res.id]
        elif date:
            # 해당 날짜에 배정 없음 — denormalized field 무시하고 빈 값 반환
            override_room_id, override_room, override_password, override_assigned_by, override_bed_order = None, '', '', None, 0
        else:
            override_room_id, override_room, override_password, override_assigned_by, override_bed_order = None, None, None, None, 0

        # Resolve per-date party_type: daily info overrides reservation-level value when date is provided
        if date and res.id in daily_party_map:
            override_party_type = daily_party_map[res.id]
        else:
            override_party_type = None  # Fall back to reservation.party_type in _to_response

        # Resolve per-date notes
        if date and res.id in daily_notes_map:
            override_notes = daily_notes_map[res.id]
        else:
            override_notes = None

        # Resolve per-date unstable_party
        override_unstable = daily_unstable_map.get(res.id) if date else None

        # 언스테이블 예약 매칭 (스테이블 예약자 중 언스테이블도 예약한 사람)
        has_unstable = res.section != 'unstable' and bool(res.phone) and res.phone in unstable_phone_set

        results.append(_to_response(res, override_room=override_room, override_password=override_password, override_assigned_by=override_assigned_by, override_party_type=override_party_type, override_room_id=override_room_id, override_bed_order=override_bed_order, db=db, filter_date=date, daily_keys=_daily_keys, override_notes=override_notes, override_unstable_party=override_unstable, override_has_unstable_booking=has_unstable))
    return {"items": results, "total": total_count}


@router.post("", response_model=ReservationResponse)
async def create_reservation(reservation: ReservationCreate, db: Session = Depends(get_tenant_scoped_db), current_user: User = Depends(get_current_user)):
    """Create a new reservation"""
    # Convert status string to enum
    try:
        status_enum = ReservationStatus(reservation.status)
    except ValueError:
        diag("reservation.invalid_status", level="critical",
             endpoint="create", raw_status=str(reservation.status)[:40])
        raise HTTPException(status_code=400, detail="유효하지 않은 상태입니다")

    db_reservation = Reservation(
        customer_name=reservation.customer_name,
        phone=reservation.phone,
        check_in_date=reservation.check_in_date,
        check_in_time=reservation.check_in_time,
        status=status_enum,
        notes=reservation.notes,
        booking_source=reservation.booking_source,
        gender=reservation.gender,
        male_count=reservation.male_count,
        female_count=reservation.female_count,
        party_size=reservation.party_size,
        party_type=reservation.party_type,
        check_out_date=reservation.check_out_date,
        naver_room_type=reservation.naver_room_type,  # Original reservation room type
        section=reservation.section or 'unassigned',
        # 수동 생성 경로(POST /api/reservations)는 visit_count/age_group 메타데이터를 채우지
        # 않아 게스트 이름 옆 (N회/20남) suffix가 노출되지 않게 한다. 네이버 sync / 연박추가
        # 경로는 별도 흐름이라 영향 없음.
        visit_count=None,
    )

    db.add(db_reservation)
    db.flush()

    # Compute is_long_stay for manual reservations
    from app.services.consecutive_stay import compute_is_long_stay
    db_reservation.is_long_stay = compute_is_long_stay(db_reservation)

    db.flush()
    # Auto-generate chips for new reservation (3종 칩 통합)
    from app.services.reconcile import reconcile_all_chips
    reconcile_all_chips(db, db_reservation.id)

    db.commit()
    db.refresh(db_reservation)

    diag(
        "reservation.created",
        level="critical",
        reservation_id=db_reservation.id,
        actor=current_user.username if current_user else None,
        section=db_reservation.section,
        check_in_date=db_reservation.check_in_date,
        check_out_date=db_reservation.check_out_date,
    )

    return _to_response(db_reservation, db=db)


@router.put("/{reservation_id}", response_model=ReservationResponse)
async def update_reservation(
    reservation_id: int, reservation: ReservationUpdate, db: Session = Depends(get_tenant_scoped_db), current_user: User = Depends(get_current_user)
):
    """Update a reservation"""
    db_reservation = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not db_reservation:
        raise HTTPException(status_code=404, detail="예약을 찾을 수 없습니다")

    update_data = reservation.dict(exclude_unset=True)

    # Convert status string to enum if provided
    if "status" in update_data:
        try:
            update_data["status"] = ReservationStatus(update_data["status"])
        except ValueError:
            diag("reservation.invalid_status", level="critical",
                 endpoint="update", reservation_id=reservation_id,
                 raw_status=str(update_data["status"])[:40])
            raise HTTPException(status_code=400, detail="유효하지 않은 상태입니다")

    section_changed = "section" in update_data and update_data["section"] != db_reservation.section
    # column_match 필터 대상 필드 변경 감지
    _SMS_TAG_FIELDS = {"section", "party_type", "gender", "naver_room_type", "notes", "check_in_date", "check_out_date"}
    sms_fields_changed = section_changed or bool(_SMS_TAG_FIELDS & update_data.keys())

    # 성별/인원 변경 감지 (invariant 재검증 대상 필드)
    _CONSTRAINT_FIELDS = {"gender", "male_count", "female_count", "party_size", "gender_manual"}
    constraint_changed = bool(_CONSTRAINT_FIELDS & set(update_data.keys()))

    # Log section change for debugging (room_move 로그와 연계)
    if section_changed:
        old_section = db_reservation.section or "unassigned"
        new_section = update_data["section"]
        section_labels = {"room": "객실", "unassigned": "미배정", "party": "파티만", "unstable": "언스테이블"}
        log_activity(
            db, type="room_move",
            title=f"[{db_reservation.customer_name}] 섹션이동 {section_labels.get(old_section, old_section)} → {section_labels.get(new_section, new_section)}",
            detail={
                "reservation_id": reservation_id,
                "customer_name": db_reservation.customer_name,
                "old_section": old_section,
                "new_section": new_section,
                "move_type": "manual",
            },
            created_by=current_user.username,
        )

    # 수동으로 성별 인원 편집 시 gender_manual 플래그 자동 세팅
    # (명시적으로 gender_manual을 전달한 경우는 그 값을 존중)
    if ("male_count" in update_data or "female_count" in update_data) and "gender_manual" not in update_data:
        update_data["gender_manual"] = True

    # 날짜 변경 감지 (orphan RoomAssignment 정리용)
    old_dates = (db_reservation.check_in_date, db_reservation.check_out_date)

    # Reservation 업데이트 추적용 diag
    # (성별/인원 invariant 깨짐 원인 추적 — gender 단독 업데이트 등 식별)
    try:
        _watched = {"gender", "male_count", "female_count", "party_size", "gender_manual"}
        diag(
            "reservation.updated",
            level="verbose",
            reservation_id=reservation_id,
            actor=current_user.username if current_user else None,
            changed_fields=sorted(update_data.keys()),
            gender_before=db_reservation.gender,
            male_before=db_reservation.male_count,
            female_before=db_reservation.female_count,
            party_size_before=db_reservation.party_size,
            gender_manual_before=db_reservation.gender_manual,
            watched_changes={k: update_data[k] for k in _watched & update_data.keys()},
        )
    except Exception:
        pass

    from app.services.reservation_mutator import ReservationMutator, ChangeSource
    ReservationMutator.apply_changes(db, db_reservation, ChangeSource.MANUAL, update_data)

    # CANCELLED → CONFIRMED 복구 경로 — 운영자가 "삭제 취소" 액션 실행.
    # delete_reservation soft-cancel 이 박은 mef["status"]=True 핀을 여기서 해제.
    # 안 풀면 다음 naver_sync 가 영원히 status 갱신 못 함 (silent data drift).
    # UI 메뉴 우회 (자동화 / 외부 API) 경로 안전 — 백엔드에서 정합성 책임.
    #
    # ⚠️ 순서 의존성 (변경 금지): 이 블록은 반드시 위 apply_changes(L335) **직후** 위치해야 함.
    #    status 가 NAVER=guarded 라, MANUAL PATCH status=CONFIRMED 가 mutator 를 통과하면
    #    auto-mark 규칙(reservation_mutator.py:170-173)이 mef["status"]=timestamp 를 다시 stamp 함.
    #    이 블록이 그 직후 del 로 되돌리므로 net 결과가 "핀 해제"가 됨.
    #    블록을 apply_changes 앞으로 옮기면 핀이 안 풀려 또 고아 핀 발생.
    # 설계 문서: docs/plans/delete-soft-cancel-design.md, docs/plans/delete-soft-cancel-followup-234.md
    if (
        "status" in update_data
        and update_data["status"] == ReservationStatus.CONFIRMED
    ):
        mef = dict(db_reservation.manually_edited_fields or {})
        if "status" in mef:
            del mef["status"]
            db_reservation.manually_edited_fields = mef
            diag(
                "reservation.status_pin_released",
                level="critical",
                reservation_id=reservation_id,
                actor=current_user.username if current_user else None,
            )
        # cancelled_at 도 클리어 — paired-state invariant (CANCELLED ⇔ cancelled_at NOT NULL) 유지.
        if db_reservation.cancelled_at:
            db_reservation.cancelled_at = None

    # status 가 CANCELLED 로 바뀌면 stay_group 자동 해제 (naver_sync 와 동일 정책)
    # — 취소된 예약이 그룹에 stay_group_id 로 남아있으면 이후 extend_stay 등이 stale 데이터로 실패함
    # S4 fix: 취소 시 manually_extended_until 클리어 — 재활성 시 stale flag로
    # naver_sync 영구 차단되는 silent data drift 방지
    if (
        "status" in update_data
        and update_data["status"] == ReservationStatus.CANCELLED
        and db_reservation.manually_extended_until
    ):
        db_reservation.manually_extended_until = None
        # PR1-fix: pin 컬럼 + 방명록 dict 둘 다 클리어 (재활성 시 naver_sync 정상화)
        from app.services.reservation_mutator import ReservationMutator as _RM
        _RM.release_manual_pin(db_reservation, "check_out_date")

    if (
        "status" in update_data
        and update_data["status"] == ReservationStatus.CANCELLED
        and db_reservation.stay_group_id
    ):
        from app.services.consecutive_stay import unlink_from_group
        # unlink 가 남은 그룹 멤버의 is_long_stay/stay_group_order 도 갱신하므로
        # 그 멤버들의 SMS 칩도 재동기화해야 함 (stay_filter='exclude' 등 영향)
        peer_ids = [
            r.id for r in db.query(Reservation).filter(
                Reservation.stay_group_id == db_reservation.stay_group_id,
                Reservation.id != reservation_id,
            ).all()
        ]
        unlink_from_group(db, reservation_id)
        if peer_ids:
            db.flush()
            # 5종 칩 통합 reconcile — unlink 후 peer 의 4종 칩 stale 방지
            # (sync-sms-tags PR2).
            from app.services.reconcile import reconcile_all_chips
            for peer_id in peer_ids:
                try:
                    reconcile_all_chips(db, peer_id)
                except Exception as e:
                    logger.warning(f"peer reconcile_all_chips after unlink failed: res={peer_id} err={e}")

    # 날짜 변경 시 orphan RoomAssignment 정리 (네이버 동기화와 동일)
    new_dates = (db_reservation.check_in_date, db_reservation.check_out_date)
    if old_dates != new_dates:
        from app.services.consecutive_stay import compute_is_long_stay
        db_reservation.is_long_stay = compute_is_long_stay(db_reservation)
        # manually_extended_until consistency: clear if it now exceeds new check_out_date
        # (e.g., user manually changed checkout date, breaking the original extension semantics)
        if (db_reservation.manually_extended_until
                and db_reservation.check_out_date
                and db_reservation.manually_extended_until > db_reservation.check_out_date):
            # NOTE: 중복 local import 제거 (Python 3.12 UnboundLocalError 회피) — top-level L16 의 diag 사용.
            diag(
                "update_reservation.cleared_stale_extension_flag",
                level="critical",
                reservation_id=reservation_id,
                old_extended_until=db_reservation.manually_extended_until,
                new_check_out=db_reservation.check_out_date,
            )
            db_reservation.manually_extended_until = None
        db.flush()
        from app.services.reservation_lifecycle import on_dates_changed
        on_dates_changed(db, db_reservation, old_dates[0], old_dates[1])

    # Phase 2-5a: 성별/인원 변경 시 invariant 재검증 (lifecycle 단계 #11)
    if constraint_changed:
        from app.services.reservation_lifecycle import on_constraints_changed
        on_constraints_changed(
            db, db_reservation,
            _CONSTRAINT_FIELDS & set(update_data.keys()),
            actor=current_user.username if current_user else "system",
        )

    # 통합 칩 재계산: 칩에 영향 주는 변경이 있었으면 한 번에 처리.
    # 날짜 변경 시 reconcile_dates 가 내부에서 wrapper 를 호출하지만, orphaned/missing
    # 이 없을 때는 호출하지 않으므로 (e.g. check_out 단축 + 그날 배정 없음 + party_size 변경)
    # 항상 한 번 더 호출. wrapper 가 멱등이라 중복 호출은 안전.
    _SURCHARGE_FIELDS = {"male_count", "female_count", "party_size"}
    chip_affecting = (
        sms_fields_changed
        or constraint_changed
        or bool(_SURCHARGE_FIELDS & set(update_data.keys()))
    )
    if chip_affecting:
        db.flush()
        try:
            from app.services.reconcile import reconcile_all_chips
            reconcile_all_chips(db, reservation_id)
        except Exception as e:
            logger.warning(f"reconcile_all_chips failed for res={reservation_id}: {e}")

    db.commit()
    db.refresh(db_reservation)

    return _to_response(db_reservation, db=db)


@router.delete("/{reservation_id}", response_model=ActionResponse)
async def delete_reservation(reservation_id: int, db: Session = Depends(get_tenant_scoped_db), current_user: User = Depends(get_current_user)):
    """Delete a reservation.

    네이버 예약 (naver_booking_id 있음): soft cancel — row 잔존.
      - status=CANCELLED + cancelled_at=now + mef["status"]=True 핀
      - on_status_cancelled 로 RA 정리 (sent 칩은 protect_sent=True 로 보존)
      - naver_sync 가 5분 후 confirmed 로 부활시키지 못하게 차단
    수동 예약 (naver_booking_id 없음): 기존 hard delete (cascade 전체 삭제).

    설계 문서: docs/plans/delete-soft-cancel-design.md
    """
    from datetime import datetime
    from app.config import KST, today_kst
    from app.db.models import ReservationStatus
    from app.services.reservation_lifecycle import on_status_cancelled, on_reservation_deleted

    db_reservation = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not db_reservation:
        raise HTTPException(status_code=404, detail="예약을 찾을 수 없습니다")

    is_soft_cancel = bool(db_reservation.naver_booking_id)

    # 연박 그룹 정리 (양 경로 공통 — unlink 후 peer 의 is_long_stay 복원).
    peer_ids: list[int] = []
    if db_reservation.stay_group_id:
        from app.services.consecutive_stay import unlink_from_group
        peer_ids = [
            r.id for r in db.query(Reservation).filter(
                Reservation.stay_group_id == db_reservation.stay_group_id,
                Reservation.id != reservation_id,
            ).all()
        ]
        unlink_from_group(db, reservation_id)

    if is_soft_cancel:
        # 네이버 예약: row 살려두고 cancelled 마킹 + RA/미발송 칩 정리.
        today_str = today_kst()
        check_in_str = str(db_reservation.check_in_date) if db_reservation.check_in_date else ""
        is_same_day = (check_in_str == today_str)

        # status/cancelled_at/핀 을 먼저 확정한 뒤 lifecycle 후처리 호출 (naver_sync 와 순서 통일).
        # status 핀 — 다음 naver_sync 가 네이버 confirmed 응답으로 되살리지 못하게 차단.
        # 해제는 update_reservation PATCH status=confirmed 경로에서 자동 처리.
        # 현재 on_status_cancelled 는 reservation.status 를 읽지 않아 순서 무관하나,
        # 미래에 status 분기가 추가돼도 안전하도록 방어적 정렬 (naver_sync L771→798 과 동일).
        mef = dict(db_reservation.manually_edited_fields or {})
        mef["status"] = True
        db_reservation.manually_edited_fields = mef
        db_reservation.status = ReservationStatus.CANCELLED
        db_reservation.cancelled_at = datetime.now(KST).replace(tzinfo=None)

        on_status_cancelled(db, db_reservation, same_day=is_same_day)
    else:
        # 수동 예약: 기존 cascade 삭제 (lifecycle 단계 #12).
        on_reservation_deleted(db, reservation_id)
        db.delete(db_reservation)

    # peer 칩 재동기화 (양 경로 공통 — unlink 로 peer 의 is_long_stay/stay_group_order 갱신됨).
    if peer_ids:
        db.flush()
        from app.services.reconcile import reconcile_all_chips
        for peer_id in peer_ids:
            try:
                reconcile_all_chips(db, peer_id)
            except Exception as e:
                logger.warning(f"peer reconcile_all_chips after delete failed: res={peer_id} err={e}")

    db.commit()

    diag(
        "reservation.deleted",
        level="critical",
        reservation_id=reservation_id,
        actor=current_user.username if current_user else None,
        customer_name=db_reservation.customer_name,
        soft_cancel=is_soft_cancel,
    )

    return {
        "success": True,
        "message": "예약이 취소 처리되었습니다" if is_soft_cancel else "예약이 삭제되었습니다",
    }


@router.post("/sync/naver")
@limiter.limit("5/minute")
async def sync_from_naver(request: Request, from_date: Optional[str] = None, reconcile_date: Optional[str] = None, db: Session = Depends(get_tenant_scoped_db), current_user: User = Depends(get_current_user), tenant: Tenant = Depends(get_current_tenant)):
    """Sync reservations from Naver Smart Place API.

    Args:
        from_date: Optional start date (YYYY-MM-DD) for historical sync.
        reconcile_date: Optional check-in date (YYYY-MM-DD) for STARTDATE-based reconciliation.
    """
    from app.services.naver_sync import sync_naver_to_db

    reservation_provider = get_reservation_provider_for_tenant(tenant)
    result = await sync_naver_to_db(reservation_provider, db, from_date=from_date, reconcile_date=reconcile_date)

    log_activity(
        db,
        type="naver_sync",
        title=f"[스테이블] 네이버 예약 동기화 : 수동 실행{f' ({from_date}~)' if from_date else ''}",
        detail=result,
        target_count=result.get("total", 0),
        success_count=result.get("synced", 0),
        created_by=current_user.username,
    )

    # 언스테이블 동기화도 같이 실행
    unstable_result = None
    if tenant.unstable_business_id and tenant.unstable_cookie:
        from app.real.reservation import RealReservationProvider
        unstable_provider = RealReservationProvider(
            business_id=tenant.unstable_business_id,
            cookie=tenant.unstable_cookie,
        )
        try:
            unstable_result = await sync_naver_to_db(unstable_provider, db, from_date=from_date, source="unstable")
            log_activity(
                db,
                type="naver_sync",
                title=f"[언스테이블] 네이버 예약 동기화 : 수동 실행{f' ({from_date}~)' if from_date else ''}",
                detail=unstable_result,
                target_count=unstable_result.get("total", 0),
                success_count=unstable_result.get("synced", 0),
                created_by=current_user.username,
            )
        except Exception as e:
            logger.warning(f"Unstable sync failed during manual sync: {e}")

    db.commit()

    # 응답에 언스테이블 결과도 포함
    if unstable_result:
        result["unstable"] = unstable_result
    return result


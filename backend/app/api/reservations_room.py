"""
Reservations API — room assignment & per-date daily-info endpoints
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone

from app.api.deps import get_tenant_scoped_db
from app.db.models import Reservation, User, ReservationDailyInfo
from app.auth.dependencies import get_current_user
from app.services import room_assignment
from app.diag_logger import diag

from app.api.reservations_shared import (
    ReservationResponse,
    _to_response,
)

router = APIRouter(prefix="/api/reservations", tags=["reservations"])


class RoomAssignRequest(BaseModel):
    room_id: Optional[int] = None
    date: Optional[str] = None
    apply_subsequent: bool = True  # Apply to subsequent dates for multi-night stays
    apply_group: bool = False  # Apply to all reservations in the same stay_group


class PushedOutEntry(BaseModel):
    """밀어내기(push-out)된 예약 정보 — undo 복원에 사용"""
    reservation_id: int
    customer_name: Optional[str] = None
    date: str


class RoomAssignResponse(BaseModel):
    reservation: ReservationResponse
    warnings: Optional[List[str]] = None
    pushed_out: List[PushedOutEntry] = []  # ★ undo 복원용 구조화된 정보


@router.put("/{reservation_id}/room", response_model=RoomAssignResponse)
async def assign_room(
    reservation_id: int, request: RoomAssignRequest, db: Session = Depends(get_tenant_scoped_db), current_user: User = Depends(get_current_user)
):
    """Assign or unassign a room to a reservation"""
    db_reservation = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not db_reservation:
        raise HTTPException(status_code=404, detail="예약을 찾을 수 없습니다")

    room_id = request.room_id
    req_date = request.date
    apply_subsequent = request.apply_subsequent
    warnings: List[str] = []
    pushed_out_list: List[Dict[str, Any]] = []  # undo 복원용

    if room_id is None:
        # Unassign room
        end_date = db_reservation.check_out_date if (req_date and apply_subsequent) else None
        room_assignment.unassign_room(
            db,
            reservation_id,
            req_date,
            end_date,
        )
        # Reconcile chips after unassign (building/room filter changes)
        room_assignment.sync_sms_tags(db, reservation_id)
    else:
        # Manual assignment from UI
        from app.config import KST
        today_str = datetime.now(KST).strftime("%Y-%m-%d")
        from_date = req_date or db_reservation.check_in_date

        end_date = db_reservation.check_out_date if apply_subsequent else None

        # 과거 보호는 오직 "연박자 + 모달에서 '오늘 이후 전체' 선택" 조합에서만 적용.
        # 모달 라벨이 today~이후만 변경을 약속하므로 동작 일치 보장.
        # 그 외(단박자 / "이 날만" / 완전 종료된 예약)는 과거 편집 자유.
        if (
            db_reservation.is_long_stay
            and apply_subsequent
            and from_date < today_str
            and end_date
            and end_date > today_str
        ):
            diag(
                "cascade.clamped_to_today",
                level="critical",
                reservation_id=reservation_id,
                original_from=from_date,
                clamped_to=today_str,
            )
            from_date = today_str

        _result = room_assignment.assign_room(
            db,
            reservation_id,
            room_id,
            from_date,
            end_date,
            assigned_by="manual",
            created_by=current_user.username,
        )
        if isinstance(_result, tuple):
            _, pushed_out_raw = _result
            for p in pushed_out_raw:
                warnings.append(f"{p['customer_name']} ({p['date']})가 미배정으로 이동됨")
                pushed_out_list.append({
                    "reservation_id": p["reservation_id"],
                    "customer_name": p.get("customer_name"),
                    "date": p["date"],
                })

        # 연장자 그룹 일괄 이동: 같은 stay_group의 다른 예약도 같은 방으로 배정
        if request.apply_group and db_reservation.stay_group_id:
            group_members = db.query(Reservation).filter(
                Reservation.stay_group_id == db_reservation.stay_group_id,
                Reservation.id != reservation_id,
            ).all()
            for member in group_members:
                member_from = member.check_in_date
                member_end = member.check_out_date
                try:
                    room_assignment.assign_room(
                        db,
                        member.id,
                        room_id,
                        member_from,
                        member_end,
                        assigned_by="manual",
                        created_by=current_user.username,
                        skip_logging=True,  # 그룹 이동은 대표 로그 1건만
                    )
                except ValueError as e:
                    warnings.append(f"{member.customer_name}: {e}")

    db.commit()
    db.refresh(db_reservation)

    return RoomAssignResponse(
        reservation=_to_response(db_reservation, db=db),
        warnings=warnings if warnings else None,
        pushed_out=[PushedOutEntry(**p) for p in pushed_out_list],
    )


class DailyInfoUpdate(BaseModel):
    date: str  # YYYY-MM-DD
    party_type: Optional[str] = None
    notes: Optional[str] = None
    unstable_party: Optional[bool] = None


@router.put("/{reservation_id}/daily-info", response_model=ReservationResponse)
async def update_daily_info(
    reservation_id: int,
    request: DailyInfoUpdate,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
):
    """Upsert per-date party_type for a reservation via ReservationDailyInfo."""
    db_reservation = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not db_reservation:
        raise HTTPException(status_code=404, detail="예약을 찾을 수 없습니다")

    # section="unstable" 예약에 unstable_party 설정 방지 (이미 언스테이블이므로 복사 불필요)
    sent_fields_check = request.dict(exclude_unset=True)
    if "unstable_party" in sent_fields_check and sent_fields_check["unstable_party"] and db_reservation.section == "unstable":
        raise HTTPException(status_code=400, detail="언스테이블 예약에는 unstable_party를 설정할 수 없습니다")

    existing = db.query(ReservationDailyInfo).filter(
        ReservationDailyInfo.reservation_id == reservation_id,
        ReservationDailyInfo.date == request.date,
    ).first()

    sent_fields = request.dict(exclude_unset=True)
    if existing:
        if "party_type" in sent_fields:
            existing.party_type = request.party_type
        if "notes" in sent_fields:
            existing.notes = request.notes
        if "unstable_party" in sent_fields:
            existing.unstable_party = request.unstable_party
        existing.updated_at = datetime.now(timezone.utc)
    else:
        db.add(ReservationDailyInfo(
            reservation_id=reservation_id,
            date=request.date,
            party_type=request.party_type,
            notes=request.notes,
            unstable_party=request.unstable_party or False,
        ))

    db.flush()

    # party_type 또는 notes 변경 시 통합 칩 재계산
    # (notes 는 surcharge test marker, party_type 은 party3 MMS 에 직결)
    if "party_type" in sent_fields or "notes" in sent_fields:
        from app.services.reconcile import reconcile_all_chips
        reconcile_all_chips(db, reservation_id, dates=[request.date])
    db.commit()

    db.refresh(db_reservation)

    # Return with the daily override applied
    override_party_type = request.party_type if "party_type" in sent_fields else None
    override_notes = request.notes if "notes" in sent_fields else None
    return _to_response(db_reservation, override_party_type=override_party_type, override_notes=override_notes, db=db)

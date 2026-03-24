"""
Party check-in API endpoints
스태프가 파티 참여 예약자의 입장을 체크인/체크아웃하는 API
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from typing import List, Optional
from datetime import datetime, timezone
from pydantic import BaseModel

from app.api.deps import get_tenant_scoped_db
from app.db.models import Reservation, ReservationStatus, PartyCheckin, RoomAssignment, ReservationDailyInfo
from app.auth.dependencies import require_any_role

router = APIRouter(prefix="/api/party-checkin", tags=["party-checkin"])


class PartyCheckinItem(BaseModel):
    id: int
    customer_name: str
    phone: str
    gender: Optional[str]
    male_count: Optional[int]
    female_count: Optional[int]
    party_type: Optional[str]
    checked_in: bool
    checked_in_at: Optional[str]
    room_number: Optional[str]
    stay_group_id: Optional[str] = None
    stay_group_order: Optional[int] = None
    is_long_stay: bool = False

    class Config:
        from_attributes = True


class ToggleResponse(BaseModel):
    success: bool
    checked_in: bool
    checked_in_at: Optional[str]


PARTY_TYPE_VALUES = {'1', '2', '2차만'}


@router.get("", response_model=List[PartyCheckinItem])
async def get_party_checkin_list(
    date: str,
    db: Session = Depends(get_tenant_scoped_db),
    current_user=Depends(require_any_role),
):
    """해당 날짜의 파티 참여 예약자 목록 조회 (가나다순)

    파티 참여자: party_type이 '1', '2', '2차만' 중 하나인 예약자
    """
    # 해당 날짜에 숙박 중인 예약 조회 (연박 포함)
    reservations = (
        db.query(Reservation)
        .filter(
            and_(
                Reservation.status == ReservationStatus.CONFIRMED,
                or_(
                    # 연박: 체크인 <= 오늘 < 체크아웃
                    and_(Reservation.check_in_date <= date, Reservation.check_out_date > date),
                    # 1박(check_out 없음): 체크인 당일만
                    and_(Reservation.check_in_date == date, Reservation.check_out_date.is_(None)),
                ),
            )
        )
        .all()
    )

    # party_type 필터: ReservationDailyInfo 우선, Reservation.party_type 폴백
    daily_infos = {
        di.reservation_id: di.party_type
        for di in db.query(ReservationDailyInfo).filter(
            ReservationDailyInfo.reservation_id.in_([r.id for r in reservations]),
            ReservationDailyInfo.date == date,
        ).all()
    } if reservations else {}

    party_reservations = [
        r for r in reservations
        if (daily_infos.get(r.id) or r.party_type) in PARTY_TYPE_VALUES
    ]

    # 가나다순 정렬
    party_reservations.sort(key=lambda r: r.customer_name or "")

    # 체크인 상태 조회
    reservation_ids = [r.id for r in party_reservations]
    checkin_map: dict[int, PartyCheckin] = {}
    room_map: dict[int, str] = {}
    if reservation_ids:
        checkins = (
            db.query(PartyCheckin)
            .filter(
                and_(
                    PartyCheckin.reservation_id.in_(reservation_ids),
                    PartyCheckin.date == date,
                )
            )
            .all()
        )
        checkin_map = {c.reservation_id: c for c in checkins}

        room_assignments = (
            db.query(RoomAssignment)
            .filter(
                and_(
                    RoomAssignment.reservation_id.in_(reservation_ids),
                    RoomAssignment.date == date,
                )
            )
            .all()
        )
        # Batch-fetch Room objects to resolve room_number display strings
        _ra_room_ids = {ra.room_id for ra in room_assignments}
        _room_lookup: dict = {}
        if _ra_room_ids:
            from app.db.models import Room as _Room
            _rooms = db.query(_Room).filter(_Room.id.in_(_ra_room_ids)).all()
            _room_lookup = {rm.id: rm.room_number for rm in _rooms}
        room_map = {ra.reservation_id: _room_lookup.get(ra.room_id, '') for ra in room_assignments}

    result = []
    for res in party_reservations:
        checkin = checkin_map.get(res.id)
        result.append(
            PartyCheckinItem(
                id=res.id,
                customer_name=res.customer_name,
                phone=res.phone,
                gender=res.gender,
                male_count=res.male_count,
                female_count=res.female_count,
                party_type=daily_infos.get(res.id) or res.party_type,
                checked_in=checkin is not None and checkin.checked_in_at is not None,
                checked_in_at=(
                    checkin.checked_in_at.isoformat() if checkin and checkin.checked_in_at else None
                ),
                room_number=room_map.get(res.id),
                stay_group_id=res.stay_group_id,
                stay_group_order=res.stay_group_order,
                is_long_stay=bool(res.is_long_stay),
            )
        )

    return result


@router.patch("/{reservation_id}/toggle", response_model=ToggleResponse)
async def toggle_party_checkin(
    reservation_id: int,
    date: str,
    db: Session = Depends(get_tenant_scoped_db),
    current_user=Depends(require_any_role),
):
    """파티 체크인/체크아웃 토글"""
    # 예약 존재 확인
    reservation = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not reservation:
        raise HTTPException(status_code=404, detail="예약을 찾을 수 없습니다")

    # 기존 체크인 레코드 조회
    checkin = (
        db.query(PartyCheckin)
        .filter(
            and_(
                PartyCheckin.reservation_id == reservation_id,
                PartyCheckin.date == date,
            )
        )
        .first()
    )

    if checkin and checkin.checked_in_at is not None:
        # 체크인 상태 → 체크아웃 (checked_in_at을 None으로)
        checkin.checked_in_at = None
        db.commit()
        db.refresh(checkin)
        return ToggleResponse(success=True, checked_in=False, checked_in_at=None)
    elif checkin:
        # 레코드는 있지만 미체크인 → 체크인
        checkin.checked_in_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(checkin)
        return ToggleResponse(
            success=True,
            checked_in=True,
            checked_in_at=checkin.checked_in_at.isoformat(),
        )
    else:
        # 새 체크인 레코드 생성
        new_checkin = PartyCheckin(
            reservation_id=reservation_id,
            date=date,
            checked_in_at=datetime.now(timezone.utc),
        )
        db.add(new_checkin)
        db.commit()
        db.refresh(new_checkin)
        return ToggleResponse(
            success=True,
            checked_in=True,
            checked_in_at=new_checkin.checked_in_at.isoformat(),
        )

"""
Clean crew API endpoints.

CLEANCREW 역할 전용 — 오늘 청소를 건너뛸 객실(=오늘 체크아웃 안 하는 객실).
SUPERADMIN 도 디버깅 목적으로 URL 직접 접근 가능 (sidebar 미노출).

판단 기준:
  같은 (reservation_id, room_id) 의 RoomAssignment 가 어제와 오늘 모두 존재 →
  어제부터 머물던 게스트가 오늘도 같은 방에 머무름 → 체크아웃 청소 불필요.

도미토리(공유 객실)는 동일 룸에 여러 예약이 들어갈 수 있으므로 (연박 인원 / 최대 인원)
형태로 별도 표기. 사설(개실)은 인원 표기 생략.
"""
from datetime import timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session, aliased

from app.api.deps import get_tenant_scoped_db
from app.auth.dependencies import require_role
from app.config import today_kst_date
from app.db.models import Reservation, ReservationStatus, Room, RoomAssignment, UserRole

router = APIRouter(prefix="/api/clean", tags=["clean"])

require_cleancrew_or_superadmin = require_role(UserRole.CLEANCREW, UserRole.SUPERADMIN)


class CleanSkipRoom(BaseModel):
    room_number: str
    is_dormitory: bool
    stayover_count: Optional[int] = None  # 도미토리만 채움
    capacity: Optional[int] = None        # 도미토리만 채움 (max_capacity)


@router.get(
    "",
    response_model=List[CleanSkipRoom],
    dependencies=[Depends(require_cleancrew_or_superadmin)],
)
async def list_today_stayover_rooms(
    db: Session = Depends(get_tenant_scoped_db),
) -> List[CleanSkipRoom]:
    """오늘 체크아웃 하지 않는 객실(=어제·오늘 같은 방 연속 점유) 목록.

    "연속 점유" 판정은 어제·오늘의 RoomAssignment 가 **같은 방(room_id)** 에서
    이어지는지로 보되, "같은 손님" 을 두 경로로 인정한다:
      - 경로 A: 같은 reservation_id (한 예약이 여러 날 — stay_group 없음)
      - 경로 B: 같은 stay_group_id (1박 예약들이 연박묶음으로 연결됨 → 예약번호는 날마다 다름)
    객실배정 화면의 (N/M) 연박 칩과 동일한 연박 정의를 따른다.

    어제 매칭은 EXISTS 상관 서브쿼리로 처리해 ra_today 1행당 1행을 보장한다
    (도미토리 stayover_count 합산 시 fan-out 중복집계 방지).
    취소(CANCELLED) 예약은 어제·오늘 양쪽 모두 제외한다.

    도미토리: stayover_count / capacity 표기.
    개실: 인원 표기 없음.
    """
    today_d = today_kst_date()
    today = today_d.strftime("%Y-%m-%d")
    yesterday = (today_d - timedelta(days=1)).strftime("%Y-%m-%d")

    ra_today = aliased(RoomAssignment)
    ra_yest = aliased(RoomAssignment)
    res_yest = aliased(Reservation)

    guest_count = (
        func.coalesce(Reservation.male_count, 0)
        + func.coalesce(Reservation.female_count, 0)
    )

    # 어제, 같은 방에서, 같은 손님(경로 A: 같은 예약 / 경로 B: 같은 연박묶음)이
    # 점유했는지를 묻는 상관 서브쿼리. 빈 stay_group_id(NULL)끼리는 매칭되지 않도록 가드.
    yest_continuation = (
        db.query(ra_yest.id)
        .join(res_yest, res_yest.id == ra_yest.reservation_id)
        .filter(
            ra_yest.date == yesterday,
            ra_yest.room_id == ra_today.room_id,
            res_yest.status != ReservationStatus.CANCELLED,
            or_(
                ra_yest.reservation_id == ra_today.reservation_id,
                and_(
                    Reservation.stay_group_id.isnot(None),
                    res_yest.stay_group_id == Reservation.stay_group_id,
                ),
            ),
        )
        .exists()
    )

    rows = (
        db.query(
            Room.room_number,
            Room.is_dormitory,
            Room.max_capacity,
            func.coalesce(func.sum(guest_count), 0).label("stayover_count"),
        )
        .join(ra_today, ra_today.room_id == Room.id)
        .join(Reservation, Reservation.id == ra_today.reservation_id)
        .filter(
            ra_today.date == today,
            Reservation.status != ReservationStatus.CANCELLED,
            yest_continuation,
        )
        .group_by(Room.id, Room.room_number, Room.is_dormitory, Room.max_capacity)
        .all()
    )

    result: List[CleanSkipRoom] = []
    for room_number, is_dorm, max_cap, count in rows:
        if not room_number:
            continue
        if is_dorm:
            result.append(CleanSkipRoom(
                room_number=room_number,
                is_dormitory=True,
                stayover_count=int(count or 0),
                capacity=int(max_cap or 0),
            ))
        else:
            result.append(CleanSkipRoom(
                room_number=room_number,
                is_dormitory=False,
            ))
    result.sort(key=lambda r: r.room_number)
    return result

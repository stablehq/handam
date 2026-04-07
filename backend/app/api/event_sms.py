"""
Event SMS API - 조건 필터링 후 대량 문자 발송
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from app.api.deps import get_tenant_scoped_db, get_current_tenant
from app.auth.dependencies import get_current_user
from app.db.models import Reservation, ReservationStatus, User
from app.factory import get_sms_provider_for_tenant
from app.services.activity_logger import log_activity
from datetime import datetime

router = APIRouter(prefix="/api/event-sms", tags=["event-sms"])


class EventSmsSearchRequest(BaseModel):
    date_from: str  # YYYY-MM-DD
    date_to: str    # YYYY-MM-DD
    gender: Optional[str] = None  # '남' | '여' | None(전체)
    min_nights: Optional[int] = None
    max_nights: Optional[int] = None
    min_visits: Optional[int] = None
    max_visits: Optional[int] = None
    exclude_age_groups: Optional[List[str]] = None  # ['20', '30', '40'] — 제외할 연령대


class EventSmsSendRequest(BaseModel):
    phones: List[str]
    message: str
    title: Optional[str] = None  # LMS 제목


class CustomerResult(BaseModel):
    phone: str
    customer_name: str
    gender: Optional[str] = None
    age_group: Optional[str] = None
    visit_count: Optional[int] = None
    total_nights: int
    reservation_count: int
    last_check_in: str


@router.post("/search", response_model=List[CustomerResult])
async def search_reservations(
    req: EventSmsSearchRequest,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
):
    """조건에 맞는 예약을 필터링하여 중복 제거된 고객 목록을 반환합니다."""
    query = db.query(Reservation).filter(
        Reservation.status == ReservationStatus.CONFIRMED,
        Reservation.check_in_date >= req.date_from,
        Reservation.check_in_date <= req.date_to,
        Reservation.phone.isnot(None),
        Reservation.phone != '',
    )

    if req.gender:
        query = query.filter(Reservation.gender == req.gender)

    if req.exclude_age_groups:
        query = query.filter(
            ~Reservation.age_group.in_(req.exclude_age_groups) | Reservation.age_group.is_(None)
        )

    if req.min_visits is not None:
        query = query.filter(Reservation.visit_count >= req.min_visits)
    if req.max_visits is not None:
        query = query.filter(Reservation.visit_count <= req.max_visits)

    reservations = query.all()

    # 박수 계산 후 전화번호 기준으로 중복 제거
    customers = {}
    for r in reservations:
        nights = 1
        if r.check_in_date and r.check_out_date:
            try:
                ci = datetime.strptime(r.check_in_date, "%Y-%m-%d")
                co = datetime.strptime(r.check_out_date, "%Y-%m-%d")
                nights = max((co - ci).days, 1)
            except ValueError:
                nights = 1

        # 박수 필터 적용
        if req.min_nights is not None and nights < req.min_nights:
            continue
        if req.max_nights is not None and nights > req.max_nights:
            continue

        phone = r.phone.strip()
        if phone in customers:
            c = customers[phone]
            c["total_nights"] += nights
            c["reservation_count"] += 1
            if r.check_in_date > c["last_check_in"]:
                c["last_check_in"] = r.check_in_date
                c["customer_name"] = r.customer_name  # 가장 최근 이름 사용
        else:
            customers[phone] = {
                "phone": phone,
                "customer_name": r.customer_name,
                "gender": r.gender,
                "age_group": r.age_group,
                "visit_count": r.visit_count,
                "total_nights": nights,
                "reservation_count": 1,
                "last_check_in": r.check_in_date,
            }

    # 최근 체크인 기준 내림차순 정렬
    result = sorted(customers.values(), key=lambda x: x["last_check_in"], reverse=True)
    return result


@router.post("/send")
async def send_event_sms(
    req: EventSmsSendRequest,
    db: Session = Depends(get_tenant_scoped_db),
    tenant=Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """선택된 전화번호로 대량 문자를 발송합니다."""
    if not req.phones:
        return {"success": False, "error": "발송 대상이 없습니다"}
    if not req.message.strip():
        return {"success": False, "error": "메시지 내용을 입력하세요"}

    sms_provider = get_sms_provider_for_tenant(tenant)

    messages = [{"to": phone, "message": req.message} for phone in req.phones]

    kwargs = {}
    if req.title:
        kwargs["title"] = req.title

    result = await sms_provider.send_bulk(messages=messages, **kwargs)

    log_activity(
        db,
        type="sms_event",
        title=f"이벤트 문자 발송 ({len(req.phones)}명)",
        detail={
            "message": req.message[:200],
            "target_count": len(req.phones),
            "sent": result.get("sent", 0),
            "failed": result.get("failed", 0),
        },
        target_count=len(req.phones),
        success_count=result.get("sent", 0),
        failed_count=result.get("failed", 0),
        created_by=current_user.username,
    )
    db.commit()

    return {
        "success": result.get("success", False),
        "sent_count": result.get("sent", 0),
        "failed_count": result.get("failed", 0),
        "total": len(req.phones),
    }

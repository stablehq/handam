"""
Sales Report API - 진행자별 매출 분석 + 날짜별 상세
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_
from pydantic import BaseModel
from typing import Optional, List
from app.api.deps import get_tenant_scoped_db
from app.auth.dependencies import get_current_user
from app.db.models import (
    Reservation, ReservationStatus, ReservationDailyInfo,
    OnsiteSale, DailyHost, OnsiteAuction, User,
)

router = APIRouter(prefix="/api/sales-report", tags=["sales-report"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class SalesItemDetail(BaseModel):
    item_name: str
    amount: int
    created_at: Optional[str] = None

class DateDetail(BaseModel):
    date: str
    participants: int
    sales_total: int
    auction_amount: Optional[int] = None
    items: List[SalesItemDetail]

class HostSummary(BaseModel):
    host_username: str
    days_count: int
    total_sales: int          # 현장판매 합계
    total_auction: int        # 경매 합계
    total_revenue: int        # 판매 + 경매
    total_participants: int
    avg_per_person: float     # total_revenue / total_participants
    daily_avg: float          # total_revenue / days_count
    dates: List[DateDetail]

class SalesReportResponse(BaseModel):
    hosts: List[HostSummary]
    grand_total_revenue: int
    grand_total_participants: int


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.get("", response_model=SalesReportResponse)
async def get_sales_report(
    date_from: str = Query(..., description="시작일 YYYY-MM-DD"),
    date_to: str = Query(..., description="종료일 YYYY-MM-DD"),
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
):
    # 1. 진행자 목록 (기간 내)
    hosts = db.query(DailyHost).filter(
        DailyHost.date >= date_from, DailyHost.date <= date_to,
    ).all()
    host_map: dict[str, list[str]] = {}  # username -> [dates]
    for h in hosts:
        host_map.setdefault(h.host_username, []).append(h.date)

    # 2. 현장판매 (기간 내)
    sales = db.query(OnsiteSale).filter(
        OnsiteSale.date >= date_from, OnsiteSale.date <= date_to,
    ).order_by(OnsiteSale.created_at.desc()).all()
    sales_by_date: dict[str, list] = {}
    for s in sales:
        sales_by_date.setdefault(s.date, []).append(s)

    # 3. 경매 (기간 내)
    auctions = db.query(OnsiteAuction).filter(
        OnsiteAuction.date >= date_from, OnsiteAuction.date <= date_to,
    ).all()
    auction_map = {a.date: a.final_amount for a in auctions}

    # 4. 파티 참여 인원 (전체 파티 예약자의 male+female 합계 — 체크인 여부 무관)
    # party_checkin.py와 동일한 로직: 해당 날짜에 숙박 중인 confirmed 예약 중 party_type 매칭
    PARTY_TYPE_VALUES = {'1', '2', '2차만'}

    # 기간 내 모든 날짜를 순회해서 인원 계산
    from datetime import datetime, timedelta
    dt_from = datetime.strptime(date_from, "%Y-%m-%d")
    dt_to = datetime.strptime(date_to, "%Y-%m-%d")
    participants_by_date: dict[str, int] = {}

    # 기간 내 confirmed 예약 한번에 조회
    all_reservations = db.query(Reservation).filter(
        Reservation.status == ReservationStatus.CONFIRMED,
        Reservation.check_in_date <= date_to,
        or_(
            Reservation.check_out_date > date_from,
            and_(Reservation.check_out_date.is_(None), Reservation.check_in_date >= date_from),
        ),
    ).all()

    # daily_info 한번에 조회
    all_daily_info = db.query(ReservationDailyInfo).filter(
        ReservationDailyInfo.reservation_id.in_([r.id for r in all_reservations]),
        ReservationDailyInfo.date >= date_from,
        ReservationDailyInfo.date <= date_to,
    ).all() if all_reservations else []

    # date -> {res_id: party_type}
    daily_info_map: dict[str, dict[int, str]] = {}
    for di in all_daily_info:
        daily_info_map.setdefault(di.date, {})[di.reservation_id] = di.party_type or ""

    # 날짜별 인원 계산
    current = dt_from
    while current <= dt_to:
        d = current.strftime("%Y-%m-%d")
        total = 0
        di_for_date = daily_info_map.get(d, {})
        for r in all_reservations:
            # 해당 날짜에 숙박 중인지 체크
            if r.check_out_date:
                if not (r.check_in_date <= d < r.check_out_date):
                    continue
            else:
                if r.check_in_date != d:
                    continue
            # 스테이블 파티 타입 체크 (unstable 제외)
            if r.section == 'unstable':
                continue
            party_type = di_for_date.get(r.id) or r.party_type
            if party_type in PARTY_TYPE_VALUES:
                total += (r.male_count or 0) + (r.female_count or 0)
        participants_by_date[d] = total
        current += timedelta(days=1)

    def get_participants(date: str) -> int:
        return participants_by_date.get(date, 0)

    # 5. 진행자별 집계
    result_hosts: list[HostSummary] = []

    # 진행자가 없는 날짜도 포함하기 위해 모든 날짜 수집
    all_dates_with_data = set(sales_by_date.keys()) | set(auction_map.keys())
    assigned_dates = set()
    for dates in host_map.values():
        assigned_dates.update(dates)
    unassigned_dates = sorted(all_dates_with_data - assigned_dates)

    for username, dates in sorted(host_map.items()):
        dates_sorted = sorted(dates)
        date_details: list[DateDetail] = []
        total_sales = 0
        total_auction = 0
        total_participants = 0

        for d in dates_sorted:
            day_sales = sales_by_date.get(d, [])
            day_sales_total = sum(s.amount for s in day_sales)
            day_auction = auction_map.get(d)
            day_participants = get_participants(d)

            total_sales += day_sales_total
            total_auction += (day_auction or 0)
            total_participants += day_participants

            date_details.append(DateDetail(
                date=d,
                participants=day_participants,
                sales_total=day_sales_total,
                auction_amount=day_auction,
                items=[
                    SalesItemDetail(
                        item_name=s.item_name,
                        amount=s.amount,
                        created_at=s.created_at.isoformat() if s.created_at else None,
                    )
                    for s in day_sales
                ],
            ))

        total_revenue = total_sales + total_auction
        days_count = len(dates_sorted)

        result_hosts.append(HostSummary(
            host_username=username,
            days_count=days_count,
            total_sales=total_sales,
            total_auction=total_auction,
            total_revenue=total_revenue,
            total_participants=total_participants,
            avg_per_person=round(total_revenue / total_participants, 0) if total_participants > 0 else 0,
            daily_avg=round(total_revenue / days_count, 0) if days_count > 0 else 0,
            dates=date_details,
        ))

    # 진행자 미지정 날짜
    if unassigned_dates:
        date_details = []
        total_sales = 0
        total_auction = 0
        total_participants = 0

        for d in unassigned_dates:
            day_sales = sales_by_date.get(d, [])
            day_sales_total = sum(s.amount for s in day_sales)
            day_auction = auction_map.get(d)
            day_participants = get_participants(d)

            total_sales += day_sales_total
            total_auction += (day_auction or 0)
            total_participants += day_participants

            date_details.append(DateDetail(
                date=d,
                participants=day_participants,
                sales_total=day_sales_total,
                auction_amount=day_auction,
                items=[
                    SalesItemDetail(
                        item_name=s.item_name,
                        amount=s.amount,
                        created_at=s.created_at.isoformat() if s.created_at else None,
                    )
                    for s in day_sales
                ],
            ))

        total_revenue = total_sales + total_auction
        result_hosts.append(HostSummary(
            host_username="(미지정)",
            days_count=len(unassigned_dates),
            total_sales=total_sales,
            total_auction=total_auction,
            total_revenue=total_revenue,
            total_participants=total_participants,
            avg_per_person=round(total_revenue / total_participants, 0) if total_participants > 0 else 0,
            daily_avg=round(total_revenue / len(unassigned_dates), 0) if unassigned_dates else 0,
            dates=date_details,
        ))

    # daily_avg 높은 순 정렬
    result_hosts.sort(key=lambda h: h.daily_avg, reverse=True)

    grand_total = sum(h.total_revenue for h in result_hosts)
    grand_participants = sum(h.total_participants for h in result_hosts)

    return SalesReportResponse(
        hosts=result_hosts,
        grand_total_revenue=grand_total,
        grand_total_participants=grand_participants,
    )

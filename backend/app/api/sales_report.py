"""
Sales Report API - 진행자별 매출 분석 + 날짜별 상세
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from pydantic import BaseModel
from typing import Optional, List
from app.api.deps import get_tenant_scoped_db
from app.auth.dependencies import get_current_user
from app.db.models import (
    Reservation, ReservationStatus, ReservationDailyInfo,
    OnsiteSale, DailyHost, OnsiteAuction, User,
    DailyReviewCount, OnsiteFemaleInvite,
)

router = APIRouter(prefix="/api/sales-report", tags=["sales-report"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class SalesItemDetail(BaseModel):
    item_name: str
    amount: int
    payment_method: Optional[str] = None
    created_at: Optional[str] = None

class DateDetail(BaseModel):
    date: str
    participants: int
    sales_total: int
    auction_amount: Optional[int] = None
    auction_payment_method: Optional[str] = None
    reviews_count: int = 0
    invited_females: int = 0  # 그날 진행자에게 귀속된 여자초대수
    sales_by_payment: dict = {}  # {"카드": 25000, "이체": 12000, ...}
    items: List[SalesItemDetail]

class HostSummary(BaseModel):
    host_username: str
    days_count: int
    total_sales: int          # 현장판매 합계
    total_auction: int        # 경매 합계
    total_revenue: int        # 판매 + 경매
    total_participants: int
    total_reviews: int = 0
    total_invited_females: int = 0
    sales_by_payment: dict = {}    # 진행자 운영일들의 결제방식별 현장판매 합
    auction_by_payment: dict = {}  # 진행자 운영일들의 결제방식별 경매 합
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

    # 3. 경매 (기간 내) — 날짜당 1건
    auctions = db.query(OnsiteAuction).filter(
        OnsiteAuction.date >= date_from, OnsiteAuction.date <= date_to,
    ).all()
    auction_map = {a.date: a for a in auctions}  # date -> OnsiteAuction obj

    # 3-1. 리뷰수 (기간 내)
    reviews = db.query(DailyReviewCount).filter(
        DailyReviewCount.date >= date_from, DailyReviewCount.date <= date_to,
    ).all()
    reviews_by_date: dict[str, int] = {r.date: r.count for r in reviews}

    # 3-2. 여자초대수 (기간 내) — host_username 기준 직접 귀속
    invites = db.query(OnsiteFemaleInvite).filter(
        OnsiteFemaleInvite.date >= date_from, OnsiteFemaleInvite.date <= date_to,
    ).all()
    invites_by_host: dict[str, int] = {}  # host -> total count
    invites_by_date_host: dict[tuple[str, str], int] = {}  # (date, host) -> count
    for inv in invites:
        invites_by_host[inv.host_username] = invites_by_host.get(inv.host_username, 0) + inv.count
        invites_by_date_host[(inv.date, inv.host_username)] = invites_by_date_host.get((inv.date, inv.host_username), 0) + inv.count

    # 4. 파티 참여 인원 (전체 파티 예약자의 male+female 합계 — 체크인 여부 무관)
    PARTY_TYPE_VALUES = {'1', '2', '2차만'}

    from datetime import datetime, timedelta
    dt_from = datetime.strptime(date_from, "%Y-%m-%d")
    dt_to = datetime.strptime(date_to, "%Y-%m-%d")
    participants_by_date: dict[str, int] = {}

    all_reservations = db.query(Reservation).filter(
        Reservation.status == ReservationStatus.CONFIRMED,
        Reservation.check_in_date <= date_to,
        or_(
            Reservation.check_out_date > date_from,
            and_(Reservation.check_out_date.is_(None), Reservation.check_in_date >= date_from),
        ),
    ).all()

    all_daily_info = db.query(ReservationDailyInfo).filter(
        ReservationDailyInfo.reservation_id.in_([r.id for r in all_reservations]),
        ReservationDailyInfo.date >= date_from,
        ReservationDailyInfo.date <= date_to,
    ).all() if all_reservations else []

    daily_info_map: dict[str, dict[int, str]] = {}
    for di in all_daily_info:
        daily_info_map.setdefault(di.date, {})[di.reservation_id] = di.party_type or ""

    current = dt_from
    while current <= dt_to:
        d = current.strftime("%Y-%m-%d")
        total = 0
        di_for_date = daily_info_map.get(d, {})
        for r in all_reservations:
            if r.check_out_date and r.check_out_date != r.check_in_date:
                if not (r.check_in_date <= d < r.check_out_date):
                    continue
            else:
                if r.check_in_date != d:
                    continue
            if r.section == 'unstable':
                continue
            party_type = di_for_date.get(r.id) or r.party_type
            if party_type in PARTY_TYPE_VALUES:
                total += (r.male_count or 0) + (r.female_count or 0)
        participants_by_date[d] = total
        current += timedelta(days=1)

    def get_participants(date: str) -> int:
        return participants_by_date.get(date, 0)

    # ── helper: 한 날짜에 대한 DateDetail 빌드 ──
    def build_date_detail(d: str, host_for_invite: Optional[str]) -> DateDetail:
        day_sales = sales_by_date.get(d, [])
        day_sales_total = sum(s.amount for s in day_sales)
        sales_pm: dict[str, int] = {}
        for s in day_sales:
            pm = s.payment_method or '기타'
            sales_pm[pm] = sales_pm.get(pm, 0) + s.amount

        day_auction = auction_map.get(d)
        day_invites = invites_by_date_host.get((d, host_for_invite), 0) if host_for_invite else 0

        return DateDetail(
            date=d,
            participants=get_participants(d),
            sales_total=day_sales_total,
            auction_amount=day_auction.final_amount if day_auction else None,
            auction_payment_method=day_auction.payment_method if day_auction else None,
            reviews_count=reviews_by_date.get(d, 0),
            invited_females=day_invites,
            sales_by_payment=sales_pm,
            items=[
                SalesItemDetail(
                    item_name=s.item_name,
                    amount=s.amount,
                    payment_method=s.payment_method,
                    created_at=s.created_at.isoformat() if s.created_at else None,
                )
                for s in day_sales
            ],
        )

    # 5. 진행자별 집계
    result_hosts: list[HostSummary] = []

    # 진행자 풀 = DailyHost ∪ OnsiteFemaleInvite (운영일 없어도 초대만으로 등장 가능)
    all_hosts = set(host_map.keys()) | set(invites_by_host.keys())

    # 미지정 날짜: 매출/경매는 있는데 DailyHost 없는 날짜
    all_dates_with_data = set(sales_by_date.keys()) | set(auction_map.keys())
    assigned_dates = set()
    for dates in host_map.values():
        assigned_dates.update(dates)
    unassigned_dates = sorted(all_dates_with_data - assigned_dates)

    for username in sorted(all_hosts):
        dates_sorted = sorted(host_map.get(username, []))
        date_details: list[DateDetail] = []
        total_sales = 0
        total_auction = 0
        total_participants = 0
        total_reviews = 0
        sales_pm_total: dict[str, int] = {}
        auction_pm_total: dict[str, int] = {}

        for d in dates_sorted:
            dd = build_date_detail(d, username)
            total_sales += dd.sales_total
            total_auction += (dd.auction_amount or 0)
            total_participants += dd.participants
            total_reviews += dd.reviews_count
            for pm, amt in dd.sales_by_payment.items():
                sales_pm_total[pm] = sales_pm_total.get(pm, 0) + amt
            if dd.auction_amount and dd.auction_payment_method:
                auction_pm_total[dd.auction_payment_method] = auction_pm_total.get(dd.auction_payment_method, 0) + dd.auction_amount
            date_details.append(dd)

        total_invites = invites_by_host.get(username, 0)
        total_revenue = total_sales + total_auction
        days_count = len(dates_sorted)

        result_hosts.append(HostSummary(
            host_username=username,
            days_count=days_count,
            total_sales=total_sales,
            total_auction=total_auction,
            total_revenue=total_revenue,
            total_participants=total_participants,
            total_reviews=total_reviews,
            total_invited_females=total_invites,
            sales_by_payment=sales_pm_total,
            auction_by_payment=auction_pm_total,
            avg_per_person=round(total_revenue / total_participants, 0) if total_participants > 0 else 0,
            daily_avg=round(total_revenue / days_count, 0) if days_count > 0 else 0,
            dates=date_details,
        ))

    # 진행자 미지정 날짜 (운영 진행자 없이 매출/경매만 있는 경우)
    if unassigned_dates:
        date_details = []
        total_sales = 0
        total_auction = 0
        total_participants = 0
        total_reviews = 0
        sales_pm_total: dict[str, int] = {}
        auction_pm_total: dict[str, int] = {}

        for d in unassigned_dates:
            dd = build_date_detail(d, None)
            total_sales += dd.sales_total
            total_auction += (dd.auction_amount or 0)
            total_participants += dd.participants
            total_reviews += dd.reviews_count
            for pm, amt in dd.sales_by_payment.items():
                sales_pm_total[pm] = sales_pm_total.get(pm, 0) + amt
            if dd.auction_amount and dd.auction_payment_method:
                auction_pm_total[dd.auction_payment_method] = auction_pm_total.get(dd.auction_payment_method, 0) + dd.auction_amount
            date_details.append(dd)

        total_revenue = total_sales + total_auction
        result_hosts.append(HostSummary(
            host_username="(미지정)",
            days_count=len(unassigned_dates),
            total_sales=total_sales,
            total_auction=total_auction,
            total_revenue=total_revenue,
            total_participants=total_participants,
            total_reviews=total_reviews,
            total_invited_females=0,
            sales_by_payment=sales_pm_total,
            auction_by_payment=auction_pm_total,
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

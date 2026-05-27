from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from app.api.deps import get_tenant_scoped_db
from app.auth.dependencies import require_admin_or_above
from app.db.models import DailyHost, User

router = APIRouter(prefix="/api/daily-host", tags=["daily-host"])


_SALES_FIELDS = [
    "auction_cash", "auction_transfer", "auction_card",
    "pocha_cash", "pocha_transfer", "pocha_card",
    "uns_cash", "uns_transfer", "uns_card",
]


class DailyHostUpsert(BaseModel):
    date: str  # YYYY-MM-DD
    host_username: str
    auction_cash: Optional[int] = None
    auction_transfer: Optional[int] = None
    auction_card: Optional[int] = None
    pocha_cash: Optional[int] = None
    pocha_transfer: Optional[int] = None
    pocha_card: Optional[int] = None
    uns_cash: Optional[int] = None
    uns_transfer: Optional[int] = None
    uns_card: Optional[int] = None


class DailyHostResponse(BaseModel):
    id: int
    date: str
    host_username: str
    auction_cash: Optional[int]
    auction_transfer: Optional[int]
    auction_card: Optional[int]
    pocha_cash: Optional[int]
    pocha_transfer: Optional[int]
    pocha_card: Optional[int]
    uns_cash: Optional[int]
    uns_transfer: Optional[int]
    uns_card: Optional[int]
    created_at: Optional[str]

    class Config:
        from_attributes = True


def _serialize(host: DailyHost) -> dict:
    data = {
        "id": host.id,
        "date": host.date,
        "host_username": host.host_username,
        "created_at": host.created_at.isoformat() if host.created_at else None,
    }
    for f in _SALES_FIELDS:
        data[f] = getattr(host, f)
    return data


@router.get("", response_model=Optional[DailyHostResponse])
async def get_daily_host(
    date: str,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(require_admin_or_above),
):
    """특정 날짜의 진행자 조회"""
    host = db.query(DailyHost).filter(DailyHost.date == date).first()
    if not host:
        return None
    return _serialize(host)


@router.put("", response_model=DailyHostResponse)
async def upsert_daily_host(
    req: DailyHostUpsert,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(require_admin_or_above),
):
    """진행자 저장 (upsert: 날짜당 1명)"""
    existing = (
        db.query(DailyHost)
        .filter(DailyHost.date == req.date)
        .with_for_update()
        .first()
    )
    if existing:
        existing.host_username = req.host_username
        for f in _SALES_FIELDS:
            setattr(existing, f, getattr(req, f))
        db.commit()
        db.refresh(existing)
        host = existing
    else:
        host = DailyHost(
            date=req.date,
            host_username=req.host_username,
            **{f: getattr(req, f) for f in _SALES_FIELDS},
        )
        db.add(host)
        db.commit()
        db.refresh(host)
    return _serialize(host)

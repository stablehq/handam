from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from app.api.deps import get_tenant_scoped_db
from app.auth.dependencies import get_current_user
from app.db.models import DailyHost, User

router = APIRouter(prefix="/api/daily-host", tags=["daily-host"])


class DailyHostUpsert(BaseModel):
    date: str  # YYYY-MM-DD
    host_username: str


class DailyHostResponse(BaseModel):
    id: int
    date: str
    host_username: str
    created_at: Optional[str]

    class Config:
        from_attributes = True


@router.get("", response_model=Optional[DailyHostResponse])
async def get_daily_host(
    date: str,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
):
    """특정 날짜의 진행자 조회"""
    host = db.query(DailyHost).filter(DailyHost.date == date).first()
    if not host:
        return None
    return {
        "id": host.id,
        "date": host.date,
        "host_username": host.host_username,
        "created_at": host.created_at.isoformat() if host.created_at else None,
    }


@router.put("", response_model=DailyHostResponse)
async def upsert_daily_host(
    req: DailyHostUpsert,
    db: Session = Depends(get_tenant_scoped_db),
    current_user: User = Depends(get_current_user),
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
        db.commit()
        db.refresh(existing)
        host = existing
    else:
        host = DailyHost(date=req.date, host_username=req.host_username)
        db.add(host)
        db.commit()
        db.refresh(host)
    return {
        "id": host.id,
        "date": host.date,
        "host_username": host.host_username,
        "created_at": host.created_at.isoformat() if host.created_at else None,
    }
